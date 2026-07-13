"""
Outils RAG (Retrieval-Augmented Generation) pour HorRAGor.

Ce module centralise les capacités de recherche sémantique et
métadonnées utilisées par l'agent conversationnel. Il s'appuie sur :

* Un index FAISS local (embeddings ``nomic-embed-text``) pour la
  recherche sémantique dans les synopsis enrichis.
* Une connexion PostgreSQL directe pour les requêtes structurées
  (métadonnées, casting, notes).
* L'extension ``pgvector`` pour la similarité cosinus directe en base.
* ``rapidfuzz`` (optionnel) pour corriger les saisies approximatives.

Les ressources FAISS sont chargées une seule fois en mémoire via un
mécanisme de singleton (module-level) afin d'éviter les I/O répétées.
"""

from __future__ import annotations


import os
import pickle
from pathlib import Path
from typing import Any
from rapidfuzz import process, fuzz

from dotenv import load_dotenv


import faiss
import numpy as np
import psycopg2
import psycopg2.extensions
from langchain_ollama import OllamaEmbeddings
from loguru import logger


# ── Définition de la racine du projet ──────────────────────────────
# __file__ = src/tools/rag_tool.py  →  remonte 3 niveaux = racine
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Charge le .env situé à la racine (avant toute utilisation d'os.environ)
load_dotenv(PROJECT_ROOT / ".env")

# -----------------------------------------------------------------------------
# Constantes de chemins et de configuration
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
"""Racine du projet (trois niveaux au-dessus de src/tools/)."""

FAISS_INDEX_PATH = PROJECT_ROOT / "data" / "faiss_index" / "horror_index.faiss"
"""Chemin vers l'index vectoriel généré par ``build_faiss_index.py``."""

FAISS_META_PATH = PROJECT_ROOT / "data" / "faiss_index" / "metadata.pkl"
"""Chemin vers le Pickle contenant la liste des métadonnées alignées."""

OLLAMA_BASE_URL = "http://localhost:11434"
"""URL du serveur Ollama local."""

OLLAMA_MODEL = "nomic-embed-text"
"""Nom du modèle d'embedding identique à celui utilisé lors de la construction."""

# -----------------------------------------------------------------------------
# Singletons module-level
# -----------------------------------------------------------------------------
_faiss_index: faiss.Index | None = None
"""Instance FAISS en mémoire (IndexFlatIP)."""

_faiss_metadata: list[dict[str, Any]] | None = None
"""Liste des métadonnées associées à chaque vecteur de l'index."""

_ollama_embedder: OllamaEmbeddings | None = None
"""Client Ollama pour générer les embeddings à la volée."""


def _load_faiss_resources() -> tuple[faiss.Index, list[dict[str, Any]], OllamaEmbeddings]:
    """
    Charge et met en cache l'index FAISS, ses métadonnées et l'embedder Ollama.

    Cette fonction suit le pattern *singleton* : si les ressources sont déjà
    présentes en mémoire, elle les retourne immédiatement sans nouvelle I/O.

    Returns:
        Un tuple ``(index_faiss, liste_metadata, embedder_ollama)``.

    Raises:
        FileNotFoundError: Si les fichiers FAISS ou Pickle sont absents.
        RuntimeError: Si Ollama n'est pas accessible (levé plus tard par
            ``langchain_ollama``).
    """
    global _faiss_index, _faiss_metadata, _ollama_embedder

    if _faiss_index is not None and _faiss_metadata is not None and _ollama_embedder is not None:
        logger.debug("Ressources FAISS déjà en mémoire (cache hit).")
        return _faiss_index, _faiss_metadata, _ollama_embedder

    # 1. Vérification des artefacts sur disque
    if not FAISS_INDEX_PATH.exists():
        logger.error(f"Index FAISS introuvable : {FAISS_INDEX_PATH}")
        raise FileNotFoundError(f"Index FAISS manquant : {FAISS_INDEX_PATH}")
    if not FAISS_META_PATH.exists():
        logger.error(f"Métadonnées introuvables : {FAISS_META_PATH}")
        raise FileNotFoundError(f"Métadonnées manquantes : {FAISS_META_PATH}")

    # 2. Chargement binaire FAISS
    logger.info(f"Chargement de l'index FAISS : {FAISS_INDEX_PATH}")
    _faiss_index = faiss.read_index(str(FAISS_INDEX_PATH))

    # 3. Désérialisation des métadonnées
    logger.info(f"Chargement des métadonnées : {FAISS_META_PATH}")
    with open(FAISS_META_PATH, "rb") as fh:
        _faiss_metadata = pickle.load(fh)

    # 4. Initialisation de l'embedder (strictement le même modèle que build)
    logger.info(
        f"Initialisation Ollama pour les requêtes : {OLLAMA_MODEL} "
        f"({OLLAMA_BASE_URL})"
    )
    _ollama_embedder = OllamaEmbeddings(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    logger.success(
        f"Ressources prêtes — Index: {_faiss_index.ntotal} vecteurs, "
        f"Dim: {_faiss_index.d}"
    )
    return _faiss_index, _faiss_metadata, _ollama_embedder

def search_local_horror_lore(
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    Recherche sémantique dans le corpus horreur indexé localement (FAISS).

    L'algorithme suit les étapes suivantes :

    1. Préfixe la requête avec ``"search_query: "`` pour respecter le format
       d'instruction du modèle ``nomic-embed-text`` (optimisé pour distinguer
       les requêtes des documents).
    2. Génère l'embedding de la question via Ollama.
    3. Normalise le vecteur requête en L2 pour préserver l'équivalence
       *InnerProduct* = *Cosine Similarity*.
    4. Interroge l'index FAISS et croise les indices retournés avec les
       métadonnées en mémoire.

    Args:
        query: Question ou phrase clé saisie par l'utilisateur.
        top_k: Nombre maximum de documents voisins à retourner.

    Returns:
        Une liste ordonnée par pertinence décroissante. Chaque élément est un
        dictionnaire contenant :

        - ``chunk`` (*str*) : extrait / reconstruction du contenu indexé.
        - ``metadata`` (*dict*) : sous-dictionnaire avec ``titre``,
          ``annee_sortie`` et ``source`` (valeur fixe ``"faiss_local"``).
        - ``score`` (*float*) : similarité cosinus entre 0 et 1.
    """
    index, metas, embedder = _load_faiss_resources()

    # ------------------------------------------------------------------
    # 1. Formatage conforme au modèle d'embedding Nomic
    # ------------------------------------------------------------------
    formatted_query = f"search_query: {query.strip()}"
    logger.debug(f"Requête formatée : {formatted_query[:80]}...")

    # ------------------------------------------------------------------
    # 2. Vectorisation puis normalisation L2
    # ------------------------------------------------------------------
    query_vector = embedder.embed_query(formatted_query)
    query_np = np.array([query_vector], dtype=np.float32)
    faiss.normalize_L2(query_np)

    # ------------------------------------------------------------------
    # 3. Recherche des k plus proches voisins
    # ------------------------------------------------------------------
    distances, indices = index.search(query_np, top_k)
    # distances[0]  : scores (float32), shape == (top_k,)
    # indices[0]    : positions dans l'index, shape == (top_k,)

    results: list[dict[str, Any]] = []
    for dist, idx in zip(distances[0], indices[0]):
        # Sécurité : idx == -1 si l'index ne trouve rien (ne devrait pas
        # arriver ici car l'index contient 7391 vecteurs et top_k <= 7391).
        if idx < 0 or idx >= len(metas):
            logger.warning(f"Indice FAISS invalide ignoré : {idx}")
            continue

        meta = metas[idx]

        # Reconstruction minimale du chunk depuis les métadonnées disponibles.
        # Si l'index avait stocké le texte intégral sous la clé "text",
        # on pourrait l'injecter ici directement.
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

def _get_db_connection() -> psycopg2.extensions.connection:
    """
    Établit une connexion PostgreSQL vers Supabase.

    Ordre de priorité :
    1. ``DATABASE_URL`` (chaîne complète postgresql://…) ;
    2. Variables séparées ``SUPABASE_HOST``, ``SUPABASE_DB``,
       ``SUPABASE_USER``, ``SUPABASE_PASSWORD``.
    """
    import os

    # ── Priorité 1 : chaîne complète (celle de ton .env) ──────────
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            conn = psycopg2.connect(database_url)
            logger.debug("Connexion PostgreSQL établie via DATABASE_URL.")
            return conn
        except Exception as exc:  # pragma: no cover
            logger.warning(
                f"DATABASE_URL présente mais connexion échouée : {exc}"
            )

    # ── Priorité 2 : variables séparées ────────────────────────────
    required = [
        "SUPABASE_HOST",
        "SUPABASE_DB",
        "SUPABASE_USER",
        "SUPABASE_PASSWORD",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Variables d'environnement manquantes : {missing}. "
            "Définissez DATABASE_URL ou les 4 variables : "
            "SUPABASE_HOST, SUPABASE_DB, SUPABASE_USER, SUPABASE_PASSWORD."
        )

    conn = psycopg2.connect(
        host=os.environ["SUPABASE_HOST"],
        database=os.environ["SUPABASE_DB"],
        user=os.environ["SUPABASE_USER"],
        password=os.environ["SUPABASE_PASSWORD"],
        port=os.environ.get("SUPABASE_PORT", "5432"),
    )
    return conn

def query_movie_metadata(
    titre: str | None = None,
    id_film: int | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Récupère les métadonnées structurées d'un film depuis Supabase.
    Requête entièrement paramétrée.
    """
    if not any([titre, id_film]):
        raise ValueError("Il faut fournir au moins 'titre' ou 'id_film'.")

    conn = _get_db_connection()
    cur = conn.cursor()

    sql = """
        SELECT
            f.id_film,
            f.titre,
            f.annee_sortie,
            f.langue_originale,
            f.synopsis,
            f.tagline,
            f.duree,
            f.budget,
            f.revenue,
            r.nom AS realisateur_nom,
            COALESCE(
                array_agg(DISTINCT g.nom)
                FILTER (WHERE g.nom IS NOT NULL),
                ARRAY[]::text[]
            ) AS genres,
            COALESCE(
                array_agg(DISTINCT a.nom)
                FILTER (WHERE a.nom IS NOT NULL),
                ARRAY[]::text[]
            ) AS casting
        FROM film f
        LEFT JOIN realisateur r ON r.id_realisateur = f.id_realisateur
        LEFT JOIN film_genre fg ON fg.id_film = f.id_film
        LEFT JOIN genre g ON g.id_genre = fg.id_genre
        LEFT JOIN film_acteur fa ON fa.id_film = f.id_film
        LEFT JOIN acteur a ON a.id_acteur = fa.id_acteur
        WHERE {where_clause}
        GROUP BY 
            f.id_film, f.titre, f.annee_sortie, f.langue_originale,
            f.synopsis, f.tagline, f.duree, f.budget, f.revenue,
            r.nom
        LIMIT %s
    """

    if id_film is not None:
        where = "f.id_film = %s"
        params: list[Any] = [id_film]
    else:
        where = "f.titre ILIKE %s"
        params = [f"%{titre}%"]

    sql = sql.format(where_clause=where)
    params.append(top_k)

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    colnames = [
        "id_film", "titre", "annee_sortie", "langue_originale",
        "synopsis", "tagline", "duree", "budget", "revenue",
        "realisateur_nom", "genres", "casting",
    ]

    results = []
    for row in rows:
        d = dict(zip(colnames, row))

        realisateur = (d.get("realisateur_nom") or "").strip() or "Inconnu"
        genres = d.get("genres") or []
        casting_list = d.get("casting") or []
        casting_str = ", ".join(casting_list) if casting_list else "Non renseigné"

        results.append({
            "id_film": d["id_film"],
            "titre": d["titre"],
            "annee_sortie": d.get("annee_sortie"),
            "langue_originale": d.get("langue_originale"),
            "synopsis": d.get("synopsis"),
            "tagline": d.get("tagline"),
            "duree": d.get("duree"),
            "budget": d.get("budget"),
            "revenue": d.get("revenue"),
            "realisateur": realisateur,
            "genres": genres,
            "casting": casting_str,
        })

# ========== DÉBUT : ROBUSTESSE DONNÉES (sans toucher Supabase) ==========

    # 1. Dédoublonnage : on garde le premier (id_film le plus petit) par (titre, année)
    seen = set()
    unique_results = []
    for film in results:
        # Clé de dédoublonnage : titre normalisé + année
        titre_clean = str(film.get("titre") or "").strip().lower()
        annee = film.get("annee_sortie")
        key = (titre_clean, annee)
        
        if key not in seen:
            seen.add(key)
            unique_results.append(film)
    
    results = unique_results

    # 2. Masquage des réalisateurs "Inconnu" ou manquants
    for film in results:
        real = film.get("realisateur")
        if not real or str(real).strip().lower() == "inconnu":
            film["realisateur"] = "Non spécifié"
        
        # Sécurité supplémentaire sur les champs listes/texte
        if not film.get("genres"):
            film["genres"] = []
        if not film.get("casting"):
            film["casting"] = "Non disponible"

    # 3. Respect de top_k après dédoublonnage
    results = results[:top_k]

    # ========== FIN : ROBUSTESSE DONNÉES ==========

    return results

def find_similar_horror_movies(id_film: int, k: int = 5) -> list[dict[str, Any]]:
    """
    Recherche les films les plus similaires à un film donné via pgvector.

    Utilise l'opérateur de distance cosinus ``<=>`` fourni par l'extension
    ``pgvector``. Comme les embeddings générés par ``nomic-embed-text``
    sont normalisés (norme L2 = 1), la relation suivante est valable :

        ``similarité_cosinus = 1 - distance_cosinus``

    Args:
        id_film: Identifiant du film de référence (doit posséder un
            embedding dans la colonne ``film.embedding``).
        k: Nombre de voisins les plus proches à retourner.

    Returns:
        Liste ordonnée par pertinence décroissante. Chaque dict contient
        les mêmes métadonnées structurées que ``query_movie_metadata``,
        plus la clé ``similarite`` (float entre 0 et 1).

    Raises:
        RuntimeError: Si le film n'existe pas ou si sa colonne
            ``embedding`` est ``NULL`` (étape 0.3 non jouée ou incomplète).
    """
    conn = _get_db_connection()
    cur = conn.cursor()

    # ── Vérification préalable : le film de référence a-t-il un embedding ? ──
    cur.execute(
        "SELECT embedding IS NOT NULL FROM film WHERE id_film = %s",
        (id_film,),
    )
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        raise RuntimeError(f"Film id={id_film} introuvable en base.")
    if not row[0]:
        cur.close()
        conn.close()
        raise RuntimeError(
            f"Film id={id_film} trouvé, mais sa colonne embedding est NULL. "
            "Avez-vous lancé le script de génération / ingestion des embeddings (étape 0.3) ?"
        )

    # ── Requête pgvector paramétrée ────────────────────────────────────────
    sql = """
        SELECT
            f.id_film,
            f.titre,
            f.annee_sortie,
            f.langue_originale,
            f.synopsis,
            f.tagline,
            f.duree,
            f.budget,
            f.revenue,
            r.nom AS realisateur_nom,
            COALESCE(
                array_agg(DISTINCT g.nom)
                FILTER (WHERE g.nom IS NOT NULL),
                ARRAY[]::text[]
            ) AS genres,
            COALESCE(
                array_agg(DISTINCT a.nom)
                FILTER (WHERE a.nom IS NOT NULL),
                ARRAY[]::text[]
            ) AS casting,
            1 - (f.embedding <=> (
                SELECT ref.embedding FROM film ref WHERE ref.id_film = %s
            )) AS similarite
        FROM film f
        LEFT JOIN realisateur r ON r.id_realisateur = f.id_realisateur
        LEFT JOIN film_genre fg ON fg.id_film = f.id_film
        LEFT JOIN genre g ON g.id_genre = fg.id_genre
        LEFT JOIN film_acteur fa ON fa.id_film = f.id_film
        LEFT JOIN acteur a ON a.id_acteur = fa.id_acteur
        WHERE f.id_film != %s
          AND f.embedding IS NOT NULL
          AND f.embedding <=> (SELECT ref.embedding FROM film ref WHERE ref.id_film = %s) > 0
        GROUP BY 
            f.id_film, f.titre, f.annee_sortie, f.langue_originale,
            f.synopsis, f.tagline, f.duree, f.budget, f.revenue,
            r.nom
        ORDER BY f.embedding <=> (
            SELECT ref.embedding FROM film ref WHERE ref.id_film = %s
        )
        LIMIT %s;
    """

    try:
        cur.execute(sql, (id_film, id_film, id_film, id_film, k))
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    colnames = [
        "id_film", "titre", "annee_sortie", "langue_originale",
        "synopsis", "tagline", "duree", "budget", "revenue",
        "realisateur_nom", "genres", "casting", "similarite",
    ]

    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(zip(colnames, row))

        real = (d.get("realisateur_nom") or "").strip()
        realisateur = real if real else "Non spécifié"

        genres = d.get("genres") or []
        casting_list = d.get("casting") or []
        casting = ", ".join(casting_list) if casting_list else "Non renseigné"

        results.append({
            "id_film": d["id_film"],
            "titre": d["titre"],
            "annee_sortie": d.get("annee_sortie"),
            "langue_originale": d.get("langue_originale"),
            "synopsis": d.get("synopsis"),
            "tagline": d.get("tagline"),
            "duree": d.get("duree"),
            "budget": d.get("budget"),
            "revenue": d.get("revenue"),
            "realisateur": realisateur,
            "genres": genres,
            "casting": casting,
            "similarite": round(float(d["similarite"]), 4),
        })

    logger.info(
        f"pgvector similarity : {len(results)} voisin(s) trouvé(s) pour id_film={id_film}"
    )
    
    return results

def fuzzy_find_film(raw_title: str, score_cutoff: float = 60.0) -> dict | None:
    """
    Corrige un titre mal orthographié via rapidfuzz.
    Retourne {"id_film", "titre", "score"} ou None.
    """
    conn = _get_db_connection()
    cur = conn.cursor()

    try:
        # Optionnel : pré-filtre qui ne garde que les films ayant un mot en commun
        # (désactivé ici car rapidfuzz est déjà très rapide sur <50k lignes,
        # mais tu peux le décommenter si ta base grossit)
        #
        # words = [w for w in raw_title.lower().split() if len(w) > 2]
        # if words:
        #     cond = " OR ".join(["titre ILIKE %s"] * len(words))
        #     cur.execute(f"SELECT id_film, titre FROM film WHERE titre IS NOT NULL AND ({cond})", [f"%{w}%" for w in words])
        # else:
        cur.execute("SELECT id_film, titre FROM film WHERE titre IS NOT NULL")

        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not rows:
        return None

    choices = {titre: id_f for id_f, titre in rows}

    # token_sort_ratio : ignore l'ordre des mots, compare l'ensemble des tokens
    result = process.extractOne(
        raw_title,
        choices.keys(),
        scorer=fuzz.token_sort_ratio,
        processor=str.lower,  # normalise la casse avant comparaison
        score_cutoff=score_cutoff,
    )

    if result is None:
        return None

    best_title, score, _idx = result
    return {
        "id_film": choices[best_title],
        "titre": best_title,
        "score": round(float(score), 2),
    }
    
def resolve_film(raw_query: str, score_cutoff: float = 60.0) -> int:
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