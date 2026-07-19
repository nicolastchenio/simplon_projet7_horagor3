"""
Outils RAG (Retrieval-Augmented Generation) pour HorRAGor.

Ce module centralise les capacités de recherche sémantique et
métadonnées utilisées par l'agent conversationnel. Il s'appuie sur :

* Un index FAISS local (embeddings ``nomic-embed-text``) pour la
  recherche sémantique dans les synopsis enrichis.
* Le micro-service **data-api** (HTTP) pour les requêtes structurées,
  la similarité ``pgvector`` et le fuzzy matching.
* ``rapidfuzz`` reste utilisé côté data-api ; ce module ne fait
  qu'exploiter les résultats normalisés.

Les ressources FAISS sont chargées une seule fois en mémoire via un
mécanisme de singleton (module-level) afin d'éviter les I/O répétées.
"""

from __future__ import annotations

import pickle
from typing import Any

import faiss
import httpx
import numpy as np
from langchain_ollama import OllamaEmbeddings
from loguru import logger

from src.config import (
    DATA_API_URL,
    FAISS_INDEX_DIR,
    FAISS_TOP_K,
    OLLAMA_BASE_URL,
    OLLAMA_EMBEDDING_MODEL,
)

# ── Singletons module-level ────────────────────────────────────────────
_faiss_index: faiss.Index | None = None
"""Instance FAISS en mémoire (IndexFlatIP)."""

_faiss_metadata: list[dict[str, Any]] | None = None
"""Liste des métadonnées associées à chaque vecteur de l'index."""

_ollama_embedder: OllamaEmbeddings | None = None
"""Client Ollama pour générer les embeddings à la volée."""


# ═══════════════════════════════════════════════════════════════════════
# PARTIE 1 — FAISS LOCAL (inchangé)
# ═══════════════════════════════════════════════════════════════════════

def _load_faiss_resources() -> tuple[faiss.Index, list[dict[str, Any]], OllamaEmbeddings]:
    """
    Charge et met en cache l'index FAISS, ses métadonnées et l'embedder Ollama.

    Cette fonction suit le pattern *singleton* : si les ressources sont déjà
    présentes en mémoire, elle les retourne immédiatement sans nouvelle I/O.

    Returns
    -------
    tuple
        ``(index_faiss, liste_metadata, embedder_ollama)``.

    Raises
    ------
    FileNotFoundError
        Si les fichiers FAISS ou Pickle sont absents.
    RuntimeError
        Si Ollama n'est pas accessible (levé plus tard par ``langchain_ollama``).
    """
    global _faiss_index, _faiss_metadata, _ollama_embedder

    if _faiss_index is not None and _faiss_metadata is not None and _ollama_embedder is not None:
        logger.debug("Ressources FAISS déjà en mémoire (cache hit).")
        return _faiss_index, _faiss_metadata, _ollama_embedder

    chemin_index = FAISS_INDEX_DIR / "horror_index.faiss"
    chemin_meta = FAISS_INDEX_DIR / "metadata.pkl"

    if not chemin_index.exists():
        logger.error(f"Index FAISS introuvable : {chemin_index}")
        raise FileNotFoundError(f"Index FAISS manquant : {chemin_index}")
    if not chemin_meta.exists():
        logger.error(f"Métadonnées introuvables : {chemin_meta}")
        raise FileNotFoundError(f"Métadonnées manquantes : {chemin_meta}")

    logger.info(f"Chargement de l'index FAISS : {chemin_index}")
    _faiss_index = faiss.read_index(str(chemin_index))

    logger.info(f"Chargement des métadonnées : {chemin_meta}")
    with open(chemin_meta, "rb") as fh:
        _faiss_metadata = pickle.load(fh)

    logger.info(
        f"Initialisation Ollama pour les requêtes : {OLLAMA_EMBEDDING_MODEL} "
        f"({OLLAMA_BASE_URL})"
    )
    _ollama_embedder = OllamaEmbeddings(
        model=OLLAMA_EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    logger.success(
        f"Ressources prêtes — Index: {_faiss_index.ntotal} vecteurs, "
        f"Dim: {_faiss_index.d}"
    )
    return _faiss_index, _faiss_metadata, _ollama_embedder


def search_local_horror_lore(
    query: str,
    top_k: int = FAISS_TOP_K,
) -> list[dict[str, Any]]:
    """
    Recherche sémantique dans le corpus horreur indexé localement (FAISS).

    L'algorithme suit les étapes suivantes :

    1. Préfixe la requête avec ``"search_query: "`` pour respecter le format
       d'instruction du modèle ``nomic-embed-text``.
    2. Génère l'embedding de la question via Ollama.
    3. Normalise le vecteur requête en L2 pour préserver l'équivalence
       *InnerProduct* = *Cosine Similarity*.
    4. Interroge l'index FAISS et croise les indices retournés avec les
       métadonnées en mémoire.

    Parameters
    ----------
    query :
        Question ou phrase clé saisie par l'utilisateur.
    top_k :
        Nombre maximum de documents voisins à retourner.

    Returns
    -------
    list[dict[str, Any]]
        Résultats ordonnés par pertinence décroissante. Chaque élément
        contient ``chunk``, ``metadata`` et ``score``.
    """
    index, metas, embedder = _load_faiss_resources()

    formatted_query = f"search_query: {query.strip()}"
    logger.debug(f"Requête formatée : {formatted_query[:80]}...")

    query_vector = embedder.embed_query(formatted_query)
    query_np = np.array([query_vector], dtype=np.float32)
    faiss.normalize_L2(query_np)

    distances, indices = index.search(query_np, top_k)

    results: list[dict[str, Any]] = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(metas):
            logger.warning(f"Indice FAISS invalide ignoré : {idx}")
            continue

        meta = metas[idx]

        chunk_parts = [f"Titre: {meta.get('titre', 'Inconnu')}"]
        if meta.get("annee_sortie"):
            chunk_parts.append(f"Année: {meta['annee_sortie']}")
        if meta.get("genres"):
            chunk_parts.append(f"Genres: {meta['genres']}")
        chunk = " | ".join(chunk_parts)

        results.append(
            {
                "score": float(dist),
                "chunk": chunk,
                "metadata": {
                    "titre": meta.get("titre"),
                    "annee": meta.get("annee_sortie"),
                    "source": "faiss_local",
                },
            }
        )

    logger.info(
        f"Recherche FAISS : {len(results)} résultat(s) pour "
        f"'{query[:40]}...'"
    )
    return results


# ═══════════════════════════════════════════════════════════════════════
# PARTIE 2 — APPELS HTTP VERS data-api (remplace psycopg2)
# ═══════════════════════════════════════════════════════════════════════

def query_movie_metadata(
    titre: str | None = None,
    id_film: int | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Récupère les métadonnées structurées d'un film via le data-api.

    Selon les arguments fournis, appelle soit l'endpoint de recherche
    textuelle (``/films/search``), soit la lecture directe par ID
    (``/films/{id}``).

    Parameters
    ----------
    titre :
        Fragment du titre pour une recherche ILIKE.
    id_film :
        Identifiant exact pour une lecture directe.
    top_k :
        Nombre maximum de résultats (uniquement pour la recherche par titre).

    Returns
    -------
    list[dict[str, Any]]
        Liste de fiches normalisées (réalisateur, genres, casting, etc.).

    Raises
    ------
    ValueError
        Si ni ``titre`` ni ``id_film`` n'est fourni.
    RuntimeError
        Si le data-api retourne une erreur inattendue.
    """
    if not any([titre, id_film]):
        raise ValueError("Il faut fournir au moins 'titre' ou 'id_film'.")

    with httpx.Client(timeout=10.0) as client:
        if id_film is not None:
            url = f"{DATA_API_URL}/films/{id_film}"
            resp = client.get(url)

            if resp.status_code == 404:
                logger.warning(f"Film id={id_film} non trouvé sur data-api.")
                return []
            resp.raise_for_status()
            return [resp.json()]

        # Recherche textuelle
        url = f"{DATA_API_URL}/films/search"
        params = {"q": titre, "limit": top_k}
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def find_similar_horror_movies(
    id_film: int,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Recherche les films les plus similaires à un film donné via pgvector.

    Délegue l'opérateur de distance cosinus ``<=>`` au data-api.
    Comme les embeddings sont normalisés, la similarité retournée est
    comprise entre 0 (étranger) et 1 (identique).

    Parameters
    ----------
    id_film :
        Identifiant du film de référence.
    k :
        Nombre de voisins à retourner.

    Returns
    -------
    list[dict[str, Any]]
        Fiches des films voisins avec la clé ``similarite``.

    Raises
    ------
    RuntimeError
        Si le film n'existe pas ou si son embedding est NULL.
    """
    url = f"{DATA_API_URL}/films/{id_film}/similar"
    params = {"k": k}

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, params=params)

        if resp.status_code == 404:
            raise RuntimeError(f"Film id={id_film} introuvable en base.")
        if resp.status_code == 400:
            detail = resp.json().get("detail", "Colonne embedding NULL ou erreur métier.")
            raise RuntimeError(detail)
        resp.raise_for_status()
        data = resp.json()

    logger.info(
        f"pgvector similarity (via data-api) : {len(data)} voisin(s) "
        f"trouvé(s) pour id_film={id_film}"
    )
    return data


def fuzzy_find_film(
    raw_title: str,
    score_cutoff: float = 60.0,
) -> dict[str, Any] | None:
    """
    Corrige un titre mal orthographié en interrogeant le data-api.

    Le data-api exécute ``rapidfuzz`` sur l'ensemble du catalogue et
    retourne le meilleur candidat.

    Parameters
    ----------
    raw_title :
        Titre potentiellement mal orthographié.
    score_cutoff :
        Seuil de confiance minimum (0–100).

    Returns
    -------
    dict | None
        ``{"id_film": int, "titre": str, "score": float}`` ou ``None``.
    """
    url = f"{DATA_API_URL}/films/fuzzy"
    params = {"title": raw_title, "score_cutoff": score_cutoff}

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, params=params)

        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def resolve_film(raw_query: str, score_cutoff: float = 60.0) -> int:
    """
    Résout une requête textuelle approximative en identifiant technique.

    Parameters
    ----------
    raw_query :
        Titre potentiellement mal orthographié.
    score_cutoff :
        Seuil de confiance minimum.

    Returns
    -------
    int
        ``id_film`` du meilleur candidat.

    Raises
    ------
    RuntimeError
        Si aucun film ne correspond suffisamment.
    """
    match = fuzzy_find_film(raw_query, score_cutoff=score_cutoff)
    if match is None:
        raise RuntimeError(
            f"Aucun film trouvé pour « {raw_query} ». Vérifiez l'orthographe."
        )
    logger.info(
        f"Fuzzy match : « {raw_query} » → « {match['titre']} » "
        f"(score={match['score']}, id={match['id_film']})"
    )
    return match["id_film"]