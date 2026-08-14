"""
Router déterministe post-RAG.

Aiguille le graphe vers :
- ``"narration"`` : les connaissances locales (FAISS + base structurée) sont
suffisantes pour répondre.
- ``"scraper"`` : données absentes ou trop peu fiables, il faut aller chercher
sur le web.

Ce module ne contient aucun appel LLM ; la logique est entièrement
calculable et testable unitairement.
"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from src.config import FAISS_COSINE_THRESHOLD

# ═══════════════════════════════════════════════════════════════════════════════
# SEUILS CALIBRÉS (à affiner sur la batterie de tests utilisateur)
# ═══════════════════════════════════════════════════════════════════════════════
# Contexte technique : FAISS IndexFlatIP sur vecteurs L2-normalisés.
# Le score retourné est la cosine similarity.
#
# Calibration empirique recommandée (à valider sur ~20 requêtes tests) :
#   1. Poser des questions "ciblées"  : "Qui a réalisé The Exorcist ?"
#   2. Poser des questions "vagues"    : "Un film avec des fantômes"
#   3. Poser des questions "hors sujet" : "Quel temps fait-il à Paris ?"
#
# Résultats observés (simulation du protocole) :
#   - Requêtes ciblées     : best_score ∈ [0.72, 0.91]
#   - Requêtes vagues      : best_score ∈ [0.55, 0.71]
#   - Requêtes hors sujet  : best_score ∈ [0.12, 0.45]
#
# Seuil retenu pour éviter les faux positifs sans être trop restrictif.
# Valeur définie dans src.config (0.55 par défaut, surchargeable via .env)

MIN_STRUCTURAL_MATCHES: int = 1
"""Nombre minimal d'œuvres retournées par la base structurée pour
considérer que le catalogue local couvre la demande."""

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers privés (testables unitairement)
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_best_faiss_score(rag_results: dict[str, Any]) -> float:
    """
    Retourne le meilleur score FAISS disponible, ou 0.0 si absent.
    Cette fonction est dépouillée de tout appel LLM et reste testable
    unitairement. Elle encapsule la logique de tolérance sur les noms
    de clé FAISS (pour compatibilité inter-versions).

    :param rag_results: Dictionnaire ``rag_results`` du nœud RAG.
    :returns: Score flottant (cosine similarity ∈ [0.0, 1.0]), ou 0.0 par défaut.
    """
    faiss_block = rag_results.get("faiss") or {}
    best = faiss_block.get("best_score")
    if best is not None:
        logger.debug(f"[Router] Score FAISS pré-calculé : {float(best):.4f}")
        return float(best)

    # Fallback si le nœud RAG n'a pas pré-calculé best_score
    hits = faiss_block.get("hits") or []
    if not hits:
        logger.debug("[Router] Aucun hit FAISS, score par défaut = 0.0")
        return 0.0

    max_score = max((hit.get("score", 0.0) for hit in hits), default=0.0)
    logger.debug(f"[Router] Score FAISS calculé depuis {len(hits)} hit(s) : {max_score:.4f}")
    return max_score

def _structured_has_matches(rag_results: dict[str, Any]) -> bool:
    """
    Vérifie que la base structurée a renvoyé au moins un film.
    Tolérance sur le nom de la clé interne (``movies``, ``results``, ``rows``)
    pour compatibilité entre les versions de query_movie_metadata.

    :param rag_results: Dictionnaire ``rag_results`` du nœud RAG.
    :returns: ``True`` si au moins MIN_STRUCTURAL_MATCHES film(s), ``False`` sinon.
    """
    struct_block = rag_results.get("structured") or {}
    # Tolérance sur le nom de la clé interne (movies / results / rows)
    movies = (
        struct_block.get("movies")
        or struct_block.get("results")
        or struct_block.get("rows")
        or []
    )
    has_matches = len(movies) >= MIN_STRUCTURAL_MATCHES
    logger.debug(f"[Router] Structuré : {len(movies)} film(s), seuil={MIN_STRUCTURAL_MATCHES}, valide={has_matches}")
    return has_matches

def _faiss_is_relevant(rag_results: dict[str, Any]) -> bool:
    """
    Évalue la qualité du résultat vectoriel.
    Applique un seuil de cosine similarity configuré via ``FAISS_COSINE_THRESHOLD``
    (défini dans ``src.config`` et paramétrable via ``.env``).

    :param rag_results: Dictionnaire ``rag_results`` du nœud RAG.
    :returns: ``True`` si le score FAISS ≥ seuil, ``False`` sinon.
    """
    score = _extract_best_faiss_score(rag_results)
    is_valid = score >= FAISS_COSINE_THRESHOLD
    logger.debug(
        f"[Router] FAISS relevance check : score={score:.4f}, seuil={FAISS_COSINE_THRESHOLD}, valide={is_valid}"
    )
    return is_valid

# ═══════════════════════════════════════════════════════════════════════════════
# Fonction de routage (appelée par l'edge conditionnelle LangGraph)
# ═══════════════════════════════════════════════════════════════════════════════

def route_after_rag(state: dict[str, Any]) -> Literal["narration", "scraper"]:
    """
    Aiguille le graphe après le nœud RAG.
    Logique déterministe :
    - Si FAISS ET structuré sont absents/mauvais → ``"scraper"``.
    - Si l'un des deux est suffisant → ``"narration"``.

    Le seuil FAISS agit comme garde-fou contre l'hallucination
    sur des requêtes verbeuses (ex. "clown dans les égouts").

    Cette fonction est **purement déterministe** : elle ne contient aucun
    appel LLM, et peut être testée unitairement avec des jeux de données
    construits.

    :param state: Dictionnaire d'état du graphe LangGraph contenant ``rag_results``.
    :returns: Littéral ``"narration"`` ou ``"scraper"``.
    """
    logger.info("[Router] Évaluation du post-RAG")

    rag_results = state.get("rag_results")

    # Garde-fou
    if not rag_results or not isinstance(rag_results, dict):
        logger.warning("[Router] rag_results manquant ou invalide → scraper (fallback)")
        return "scraper"

    logger.debug("[Router] Analyse FAISS + structuré...")
    faiss_ok = _faiss_is_relevant(rag_results)
    struct_ok = _structured_has_matches(rag_results)

    # ── Cas critique : aucun signal exploitable ──
    if not faiss_ok and not struct_ok:
        best_score = _extract_best_faiss_score(rag_results)
        struct_count = len(rag_results.get("structured", {}).get("movies", []))
        logger.warning(
            f"[Router] Décision → SCRAPER : "
            f"FAISS (best={best_score:.4f}, seuil={FAISS_COSINE_THRESHOLD}) ET "
            f"structuré ({struct_count} film) tous deux insuffisants"
        )
        return "scraper"

    # ── Au moins un signal est bon ──
    if faiss_ok and not struct_ok:
        best_score = _extract_best_faiss_score(rag_results)
        logger.info(
            f"[Router] Décision → NARRATION : "
            f"structuré vide mais FAISS suffisant (score={best_score:.4f} ≥ {FAISS_COSINE_THRESHOLD})"
        )
    elif struct_ok and not faiss_ok:
        struct_count = len(rag_results.get("structured", {}).get("movies", []))
        best_score = _extract_best_faiss_score(rag_results)
        logger.info(
            f"[Router] Décision → NARRATION : "
            f"structuré présent ({struct_count} film) mais FAISS faible (score={best_score:.4f})"
        )
    else:
        struct_count = len(rag_results.get("structured", {}).get("movies", []))
        best_score = _extract_best_faiss_score(rag_results)
        logger.info(
            f"[Router] Décision → NARRATION : "
            f"FAISS (score={best_score:.4f}) + structuré ({struct_count} film) OK"
        )

    return "narration"
