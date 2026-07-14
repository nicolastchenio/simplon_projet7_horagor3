"""Nœuds du graphe multi-agent HorRAGor.

Ce module implémente la logique métier de chaque agent spécialisé.
Chaque fonction est une *node* LangGraph : elle reçoit l'état courant,
exécute sa mission, et retourne un dictionnaire de mise à jour (patch)
que le moteur fusionnera dans l'``AgentState`` global.

.. note::
    Seul ``rag_node`` est présent pour l'étape 3.1. Les nœuds
    ``scraper_node`` et ``narration_node`` seront ajoutés aux
    étapes 3.3 et 3.4.
"""

from langchain_core.messages import AIMessage

from src.models.state import AgentState
from src.tools.rag_tool import search_local_horror_lore
from src.tools.rag_tool import query_movie_metadata  # outil structuré défini en Phase 1
from src.tools.scraper_tool import enrich_from_web
from langchain_core.messages import AIMessage


def rag_node(state: AgentState) -> dict:
    """
    Agent RAG — Le Chercheur Local.

    Interroge simultanément le savoir vectoriel (FAISS) et le savoir
    structuré (métadonnées films) pour constituer le dossier brut
    lié à la requête de l'utilisateur.

    Le nœud écrit ses découvertes dans ``state["rag_results"]`` et
    notifie l'historique via un ``AIMessage`` résumé. La donnée brute
    n'est jamais injectée dans ``messages`` afin d'éviter la saturation
    du contexte (*prompt drowning*).

    :param state: État partagé du graphe. Doit contenir au minimum la
        clé ``query`` avec la question de l'utilisateur.
    :returns: Dictionnaire de patch LangGraph contenant :

        - ``rag_results`` : conteneur hybride ``{"vectorial": ..., "structured": ...}`` ;
        - ``metadata`` : métriques de traçabilité (compteurs, titres trouvés) ;
        - ``messages`` : résumé de la fouille sous forme d'``AIMessage``.

    .. admonition:: Décision de traçabilité
        :class: note

        Le champ ``metadata`` est enrichi mais jamais remplacé
        entièrement. On récupère la valeur existante via
        ``state.get("metadata", {})`` pour préserver d'éventuelles
        métadonnées posées par un pré-traitement futur.
    """
    # ------------------------------------------------------------------
    # 1. Extraction de la requête utilisateur
    # ------------------------------------------------------------------
    user_query: str = state["query"]

    # ------------------------------------------------------------------
    # 2. Double interrogation du savoir local
    # ------------------------------------------------------------------
    # L'agent RAG croise deux silos :
    #   - Vectoriel : chunks sémantiques pour le lore et les anecdotes.
    #   - Structuré : fiches films pour les dates, réalisateurs, etc.
    # Les deux appels sont synchrones (séquentiels) car il s'agit d'un MVP.
    # Une optimisation future pourrait les lancer via asyncio.gather.

    vectorial_results = search_local_horror_lore(user_query)
    structured_results = query_movie_metadata(user_query)

    # ------------------------------------------------------------------
    # 3. Assemblage du conteneur rag_results
    # ------------------------------------------------------------------
    # Ce format est attendu par le routeur (étape 3.2) et par le nœud
    # de narration (étape 3.4). Le routeur s'appuiera sur la richesse
    # de ces deux clés pour décider du basculement vers le scraper.

    rag_results = {
        "vectorial": vectorial_results,
        "structured": structured_results,
    }

    # ------------------------------------------------------------------
    # 4. Mise à jour des métadonnées de traçabilité
    # ------------------------------------------------------------------
    # On fusionne avec les métadonnées déjà présentes pour ne pas
    # écraser d'autres traces (ex. horodatage posé par un middleware).

    metadata = state.get("metadata", {})
    metadata.update(
        {
            "rag_node_executed": True,
            "vectorial_chunks_count": (
                len(vectorial_results) if isinstance(vectorial_results, list) else 0
            ),
            "structured_records_count": (
                len(structured_results) if isinstance(structured_results, list) else 0
            ),
            "films_found": [
                record.get("title")
                for record in structured_results
                if isinstance(record, dict) and record.get("title")
            ]
            if isinstance(structured_results, list)
            else [],
        }
    )

    # ------------------------------------------------------------------
    # 5. Synthèse pour l'historique de conversation
    # ------------------------------------------------------------------
    # Le résumé permet au routeur (et aux humains en debug) de comprendre
    # ce qui a été trouvé sans ingérer la donnée brute complète.

    films_identifies = metadata["films_found"]

    if films_identifies:
        resume = (
            f"Recherche RAG effectuée pour « {user_query} ». "
            f"{metadata['vectorial_chunks_count']} fragment(s) vectoriel(s) et "
            f"{metadata['structured_records_count']} fiche(s) structurée(s) récupéré(s). "
            f"Film(s) identifié(s) : {', '.join(films_identifies)}."
        )
    else:
        resume = (
            f"Recherche RAG effectuée pour « {user_query} ». "
            f"Aucune correspondance structurée ; "
            f"{metadata['vectorial_chunks_count']} fragment(s) vectoriel(s) seul(s)."
        )

    ai_summary = AIMessage(content=resume)

    # ------------------------------------------------------------------
    # 6. Retour du patch d'état
    # ------------------------------------------------------------------
    # LangGraph fusionne ce dictionnaire dans l'état global.
    # Grâce au reducer ``add_messages`` sur ``messages``, le résumé
    # est *ajouté* à la liste existante.

    return {
        "rag_results": rag_results,
        "metadata": metadata,
        "messages": [ai_summary],
    }
    
    
def scraper_node(state: AgentState) -> dict:
    """
    Node 2 : Agent Scraper (Peer-to-Peer).
    Se déclenche uniquement sur décision du router.
    Lit rag_results ou query pour identifier le film, appelle enrich_from_web,
    et écrit le résultat structuré dans scraped_data.
    Edge fixe vers narration_node.
    """
    print(">>> Scraper Node")

    query: str = state.get("query", "")
    rag_results = state.get("rag_results", {})

    # ── Identification du film ambigu / incomplet ──
    movie_title: str | None = None

    # Priorité 1 : titre depuis le résultat structuré (même partiel)
    if isinstance(rag_results, dict):
        structured = rag_results.get("structured", {})
        if isinstance(structured, dict):
            movies = structured.get("movies", [])
            if movies:
                movie_title = movies[0].get("title")
                print(f"[Scraper] Titre extrait du SQL structuré : {movie_title}")

    # Priorité 2 : fallback sur la query brute
    if not movie_title:
        movie_title = query.strip()
        print(f"[Scraper] Titre fallback depuis query : {movie_title}")

    # ── Appel outil web ──
    raw_content = enrich_from_web(movie_title)

    scraped_data = {
        "title": movie_title,
        "content": raw_content,
        "success": bool(raw_content),
    }

    summary = (
        f"🔍 Scraping exécuté pour « {movie_title} » — "
        f"contenu récupéré : {'oui' if scraped_data['success'] else 'non'}"
    )

    return {
        "scraped_data": scraped_data,
        "messages": [AIMessage(content=summary)],
    }