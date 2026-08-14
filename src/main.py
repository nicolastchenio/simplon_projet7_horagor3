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
import time
from langchain_core.messages import HumanMessage
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from fastapi import FastAPI, HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

# ─────────────────────────────────────────────────────────────────
# Configuration du logging Loguru — en premier pour capter toute
# l'initialisation du module et du lifespan (avant même la création
# de l'app FastAPI, avant le premier import lourd comme langgraph).
# ─────────────────────────────────────────────────────────────────
from src.observability.logging_config import setup_logging

setup_logging()

from src.api.auth import router as auth_router
from src.auth.security import verify_access_token

# ═══════════════════════════════════════════════════════════════
# Observabilité (Phase 8) — import non bloquant
# ═══════════════════════════════════════════════════════════════
# Ce module ne lève jamais d'exception : si Langfuse est indisponible,
# get_langfuse_handler() retourne None et l'agent fonctionne normalement.
from src.observability.langfuse_client import (
    flush_langfuse,
    get_langfuse_handler,
)

# ═══════════════════════════════════════════════════════════════
# MODÈLES PYDANTIC — Contrat d'entrée/sortie de l'API
# ═══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """Requête envoyée par le client pour discuter avec HorRAGor.

    Les champs sont documentés individuellement via leur ``Field(description=...)``
    ci-dessous (``thread_id`` : mémoire à long terme gérée par le checkpointer
    LangGraph ; si absent, un nouvel UUID est généré automatiquement).
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

    Les champs sont documentés individuellement via leur ``Field(description=...)``
    ci-dessous.
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
        1. Importe et compile le graphe HorRAGor (``build_horragor_graph``).
        2. Stocke le graphe compilé dans ``_compiled_graph``.
        3. Initialise l'observabilité Langfuse (Phase 8) afin que le log
           « Langfuse actif / désactivé » apparaisse dès le boot, et non
           à la première requête utilisateur.

    À l'arrêt :
        1. Vide le buffer Langfuse (``flush_langfuse``). Le SDK accumule
           les traces en mémoire et les envoie par lots en tâche de fond ;
           sans ce vidage, les dernières traces seraient perdues lors de
           l'extinction du conteneur.
        2. Libère la référence au graphe pour permettre un garbage
           collection propre.
    """
    global _compiled_graph

    # ── DÉMARRAGE ──
    # Hors requête HTTP : pas de request_id disponible, log sans bind.
    logger.info("[lifespan] Compilation du graphe LangGraph en cours...")
    from src.graph.pipeline import build_horragor_graph

    _compiled_graph = build_horragor_graph()
    logger.info("[lifespan] Graphe compilé et prêt.")

    # Initialisation anticipée de l'observabilité.
    # L'appel est volontairement ignoré (le handler est mis en cache dans
    # le module) : on ne cherche ici qu'à déclencher le log de statut.
    get_langfuse_handler()

    yield  # ─── L'application sert les requêtes ici ───

    # ── EXTINCTION ──
    flush_langfuse()
    logger.info("[lifespan] Arrêt du serveur, nettoyage du graphe.")

    _compiled_graph = None


app = FastAPI(
    title="HorRAGor API",
    description="API backend multi-agent pour le chroniqueur de cinéma d'horreur.",
    version="0.4.0",
    lifespan=lifespan,
)


# ═══════════════════════════════════════════════════════════════
# MIDDLEWARE HTTP — Journalisation des requêtes avec request_id
# ═══════════════════════════════════════════════════════════════

@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    """Middleware de logging pour chaque requête HTTP entrante.

    Ce middleware génère un identifiant unique (UUIDv4) pour chaque requête,
    le stocke dans ``request.state.request_id`` et l'ajoute au header de
    réponse ``X-Request-ID``. Il journalise :

    - La requête entrante (méthode HTTP, chemin, adresse client).
    - La réponse sortante (code de statut HTTP, durée en millisecondes).
    - Les exceptions levées pendant le traitement (via logger.exception).

    Args:
        request: L'objet Request FastAPI représentant la requête HTTP.
        call_next: Le prochain middleware ou handler de route dans la chaîne.

    Returns:
        La réponse HTTP avec le header ``X-Request-ID`` ajouté.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    client_ip = request.client.host if request.client else "inconnu"
    logger.bind(request_id=request_id, client_ip=client_ip).info(
        f"→ Requête entrante : {request.method} {request.url.path}"
    )

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.bind(request_id=request_id, client_ip=client_ip).exception(
            f"✗ Exception durant le traitement de {request.method} {request.url.path}"
        )
        raise

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.bind(request_id=request_id).info(
        f"← Réponse : {response.status_code} ({duration_ms:.2f} ms)"
    )

    response.headers["X-Request-ID"] = request_id
    return response


# Enregistre le routeur d'authentification
app.include_router(auth_router)


# ═══════════════════════════════════════════════════════════════
# DÉPENDANCE DE SÉCURITÉ — Valide le JWT automatiquement
# ═══════════════════════════════════════════════════════════════

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> str:
    """Valide le token JWT et retourne le username.

    Lève 401 automatiquement si le token est manquant ou invalide.
    """
    try:
        username = verify_access_token(credentials.credentials)
        return username
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalide ou expiré : {str(e)}"
        )


# ═══════════════════════════════════════════════════════════════
# ENDPOINT PRINCIPAL (Protégé par JWT - Phase 7.2)
# ═══════════════════════════════════════════════════════════════

@app.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Interroge l'agent HorRAGor sur un film d'horreur.",
)
async def chat_endpoint(
    request: Request,
    payload: ChatRequest,
    username: str = Depends(get_current_user),  # ← UTILISE LA DÉPENDANCE
) -> ChatResponse:
    """Traite une requête utilisateur via le graphe multi-agent.

    🔐 **AUTHENTIFICATION (Phase 7.2)**
    Nécessite un header ``Authorization: Bearer {access_token}`` avec un
    access_token valide.

    Le thread_id permet de reprendre une conversation si le client le
    renvoie, grâce au checkpointer MemorySaver configuré dans pipeline.py.

    Args:
        payload: Modèle validé contenant le message et le thread_id optionnel.
        username: Identité extraite du token JWT valide (injection automatique).

    Returns:
        ChatResponse avec la chronique, les sources et l'indicateur web.

    Raises:
        HTTPException: 401 si le token est invalide ou expiré,
            503 si le graphe n'est pas initialisé,
            500 si le graphe lève une exception non gérée.
    """
    global _compiled_graph

    # Récupère le request_id injecté par le middleware ; None si absent.
    request_id = getattr(request.state, "request_id", None)

    logger.bind(request_id=request_id).info(
        f"✅ Utilisateur authentifié : {username}"
    )

    # --- 1. Vérification de l'état du graphe ---
    if _compiled_graph is None:
        logger.bind(request_id=request_id).warning(
            "[chat_endpoint] Graphe non initialisé — retour 503"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Le graphe n'est pas encore initialisé. Réessayez dans quelques secondes.",
        )

    # --- 2. Préparation de l'état initial ---
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
        "metadata": {"session_id": str(uuid.uuid4()), "username": username},
    }

    # ═══════════════════════════════════════════════════════════════
    # Configuration LangGraph + Observabilité Langfuse
    # ═══════════════════════════════════════════════════════════════
    # `configurable.thread_id` : clé du checkpointer (mémoire de session).
    # `callbacks`              : liste de handlers LangChain. Langfuse y
    #                            observe automatiquement chaque nœud du
    #                            graphe et chaque appel LLM/embedding.
    # `metadata`               : enrichissements visibles dans l'UI
    #                            Langfuse, très utiles pour filtrer les
    #                            traces (par utilisateur, par session).
    # `run_name`               : nom lisible de la trace dans l'UI.
    # ═══════════════════════════════════════════════════════════════
    langfuse_handler = get_langfuse_handler()

    graph_config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "run_name": "horragor-chat",
        "metadata": {
            # Préfixes spéciaux reconnus par Langfuse pour alimenter
            # ses filtres natifs dans l'interface web :
            "langfuse_user_id": username,
            "langfuse_session_id": thread_id,
            "langfuse_tags": ["horragor", "rag", "production"],
        },
    }

    # On n'ajoute la clé `callbacks` que si le handler existe, afin de
    # ne jamais passer [None] à LangGraph (qui lèverait une erreur).
    if langfuse_handler is not None:
        graph_config["callbacks"] = [langfuse_handler]

    # --- 3. Invocation du graphe (hors du thread async principal) ---
    try:
        final_state: AgentState = await asyncio.to_thread(
            _compiled_graph.invoke,
            initial_state,
            graph_config,   # ← anciennement `config`
        )
    except Exception as exc:
        logger.bind(request_id=request_id).exception(
            f"[chat_endpoint] Échec de l'invocation du graphe : {exc}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Échec du traitement agentique : {exc}",
        ) from exc

    # --- 4. Extraction des sources pour le client ---
    sources: list[dict[str, Any]] = []
    used_web = False

    rag_results = final_state.get("rag_results") or {}

    # 4-a. Sources vectorielles (FAISS)
    faiss_hits = rag_results.get("faiss", {}).get("hits", []) if isinstance(rag_results, dict) else []
    logger.bind(request_id=request_id).debug(f"[chat_endpoint] Sources FAISS extraites : {len(faiss_hits)}")
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
async def health_check(request: Request):
    """Endpoint minimal pour le monitoring (Uptime Kuma, Phase 8)."""
    request_id = getattr(request.state, "request_id", None)
    logger.bind(request_id=request_id).debug("[health_check] Health check appelé")
    return {
        "status": "ok",
        "service": "horragor-api",
        "timestamp": datetime.utcnow().isoformat()
    }


# Expose GET /metrics (Phase 8.3) pour le scraping Prometheus.
# /health est exclu du comptage pour ne pas polluer les métriques
# avec le bruit des pings répétés d'Uptime Kuma.
Instrumentator(excluded_handlers=["/health"]).instrument(app).expose(app)
