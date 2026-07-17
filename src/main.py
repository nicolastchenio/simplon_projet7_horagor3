"""
src/main.py
===========
Serveur FastAPI pour l'agent HorRAGor.
Charge le graphe LangGraph compilé au démarrage et expose un endpoint /chat.
"""

from __future__ import annotations
from datetime import datetime

import asyncio
import uuid
from langchain_core.messages import HumanMessage
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# MODÈLES PYDANTIC — Contrat d'entrée/sortie de l'API
# ═══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """Requête envoyée par le client pour discuter avec HorRAGor.

    Attributs:
        message: La question ou le sujet demandé par l'utilisateur.
        thread_id: Identifiant de conversation pour la mémoire à long terme
            gérée par le checkpointer LangGraph. Si absent, un nouvel UUID
            est généré automatiquement à chaque appel.
    """

    message: str = Field(
        ...,
        min_length=1,
        description="Question ou sujet sur un film d'horreur.",
        examples=["Parle-moi de The Exorcist et de son impact"],
    )
    thread_id: str | None = Field(
        default=None,
        description="Identifiant de thread existant (optionnel).",
    )


class ChatResponse(BaseModel):
    """Réponse structurée renvoyée par l'agent HorRAGor.

    Attributs:
        response: Texte final généré par le nœud de narration.
        sources: Liste des sources exploitées (FAISS, SQL, web, etc.).
        used_web: Indique si le scraper web a été sollicité pendant le traitement.
        thread_id: Identifiant du thread utilisé (utile pour le suivi côté client).
    """

    response: str = Field(..., description="Chronique générée par l'agent.")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Sources ayant servi à construire la réponse.",
    )
    used_web: bool = Field(
        default=False,
        description="True si des données web ont été récupérées.",
    )
    thread_id: str = Field(..., description="Identifiant de la conversation.")


# ═══════════════════════════════════════════════════════════════
# LIFESPAN — Chargement du graphe LangGraph compilé au boot
# ═══════════════════════════════════════════════════════════════

# Variable globale privée qui stockera l'application compilée.
# Le lifespan la nourrit au démarrage ; les endpoints la consomment.
_compiled_graph: Any | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gère le cycle de vie du serveur FastAPI.

    Au démarrage :
        1. Importe et compile le graphe HorRAGor (build_horragor_graph).
        2. Stocke le graphe compilé dans _compiled_graph.
    À l'arrêt :
        Libère la référence pour permettre le garbage collection propre.
    """
    global _compiled_graph

    print("[lifespan] Compilation du graphe LangGraph en cours...")
    from src.graph.pipeline import build_horragor_graph

    _compiled_graph = build_horragor_graph()
    print("[lifespan] Graphe compilé et prêt.")

    yield

    print("[lifespan] Arrêt du serveur, nettoyage du graphe.")
    _compiled_graph = None


app = FastAPI(
    title="HorRAGor API",
    description="API backend multi-agent pour le chroniqueur de cinéma d'horreur.",
    version="0.4.0",
    lifespan=lifespan,
)


# ═══════════════════════════════════════════════════════════════
# ENDPOINT PRINCIPAL
# ═══════════════════════════════════════════════════════════════

@app.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Interroge l'agent HorRAGor sur un film d'horreur.",
)
async def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    """Traite une requête utilisateur via le graphe multi-agent.

    Le graphe exécute séquentiellement :
        rag_node → router → [scraper_node] → narration_node.

    Le thread_id permet de reprendre une conversation si le client le
    renvoie, grâce au checkpointer MemorySaver configuré dans pipeline.py.

    Args:
        payload: Modèle validé contenant le message et le thread_id optionnel.

    Returns:
        ChatResponse avec la chronique, les sources et l'indicateur web.

    Raises:
        HTTPException: 503 si le graphe n'est pas initialisé,
            500 si le graphe lève une exception non gérée.
    """
    global _compiled_graph

    # --- 1. Vérification de l'état du graphe ---
    if _compiled_graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Le graphe n'est pas encore initialisé. Réessayez dans quelques secondes.",
        )

    # --- 2. Préparation de l'état initial ---
    # On génère un thread_id unique si le client n'en fournit pas.
    thread_id = payload.thread_id or str(uuid.uuid4())

    from src.models.state import AgentState

    initial_state: AgentState = {
        "query": payload.message,
        "messages": [HumanMessage(content=payload.message)],
        "rag_results": None,
        "scraped_data": None,
        "needs_enrichment": None,
        "final_answer": None,
        "sources": None,
        "metadata": {"session_id": str(uuid.uuid4())},
    }

    config = {"configurable": {"thread_id": thread_id}}

    # --- 3. Invocation du graphe (hors du thread async principal) ---
    try:
        # graph.invoke est bloquant (I/O CPU avec Ollama).
        # to_thread évite de figer le serveur FastAPI pendant la génération.
        final_state: AgentState = await asyncio.to_thread(
            _compiled_graph.invoke,
            initial_state,
            config,
        )
    except Exception as exc:
        # Toute erreur dans le pipeline (Ollama down, bug de node, etc.)
        # est capturée et renvoyée proprement au client.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Échec du traitement agentique : {exc}",
        ) from exc

    # --- 4. Extraction des sources pour le client ---
    # On reconstitue une liste propre à partir de rag_results et scraped_data.
    sources: list[dict[str, Any]] = []
    used_web = False

    rag_results = final_state.get("rag_results") or {}

    # 4-a. Sources vectorielles (FAISS
    faiss_hits = rag_results.get("faiss", {}).get("hits", []) if isinstance(rag_results, dict) else []
    for hit in faiss_hits:
        meta = hit.get("metadata", {})
        sources.append(
            {
                "type": "faiss",
                "score": hit.get("score"),
                "title": meta.get("titre"),
                "year": meta.get("annee"),
                "preview": (hit.get("chunk") or "")[:200],
            }
        )

    # 4-b. Sources structurées (SQL / PostgreSQL)
    structured_movies = rag_results.get("structured", {}).get("movies", []) if isinstance(rag_results, dict) else []
    for movie in structured_movies:
        sources.append(
            {
                "type": "sql",
                "id": movie.get("id"),
                "title": movie.get("title"),
                "year": movie.get("year"),
            }
        )

    # 4-c. Source web (si le scraper a tourné)
    scraped_data = final_state.get("scraped_data")
    if scraped_data is not None:
        used_web = True
        web_title = scraped_data.get("title") if isinstance(scraped_data, dict) else None
        sources.append(
            {
                "type": "web",
                "title": web_title or "Page Wikipédia consultée",
            }
        )

    # --- 5. Construction de la réponse ---
    answer = final_state.get("final_answer") or "L'agent n'a pu générer de réponse."

    return ChatResponse(
        response=answer,
        sources=sources,
        used_web=used_web,
        thread_id=thread_id,
    )
    
@app.get("/health")
async def health_check():
    """Endpoint minimal pour le monitoring (Uptime Kuma, Phase 8)."""
    return {
        "status": "ok",
        "service": "horragor-api",
        "timestamp": datetime.utcnow().isoformat()
    }