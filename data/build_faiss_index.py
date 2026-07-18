"""
Script one-shot de construction de l'index FAISS pour HorRAGor.

Ce script se connecte directement à la base PostgreSQL de Supabase via
``psycopg2`` (URL de connexion dans ``DATABASE_URL``). Il récupère
l'intégralité du catalogue horreur avec leurs genres agrégés en une
seule requête SQL native.

Pour chaque film, il construit un texte enrichi, génère un embedding
via ``nomic-embed-text`` (Ollama local), puis persiste :

  * l'index vectoriel FAISS (``horror_index.faiss``)
  * les métadonnées associées (``metadata.pkl``)

Usage::
    uv run python data/build_faiss_index.py

Prérequis:
    * Ollama démarré localement avec le modèle ``nomic-embed-text``.
    * Variable ``DATABASE_URL`` définie dans le ``.env``.
    * Dépendance : ``uv add psycopg2-binary langchain-ollama faiss-cpu``
"""

from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import psycopg2
import psycopg2.extensions
from dotenv import load_dotenv
from langchain_ollama import OllamaEmbeddings
from loguru import logger
from src.config import OLLAMA_EMBEDDING_MODEL, OLLAMA_BASE_URL

# -----------------------------------------------------------------------------
# Constantes
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
"""Racine du projet déduite de l'emplacement du script."""

OUTPUT_DIR = PROJECT_ROOT / "data" / "faiss_index"
"""Répertoire de destination des artefacts FAISS et métadonnées."""

EMBEDDING_BATCH_SIZE = 50
"""Taille des lots pour la vectorisation afin de ne pas saturer la mémoire."""


# -----------------------------------------------------------------------------
# 1. Connexion PostgreSQL
# -----------------------------------------------------------------------------
def create_postgres_connection() -> psycopg2.extensions.connection:
    """
    Établit une connexion SSL vers Supabase PostgreSQL.

    Lit la variable d'environnement ``DATABASE_URL`` depuis le fichier ``.env``
    situé à la racine du projet. Supabase impose obligatoirement le mode SSL ;
    si le paramètre ``sslmode`` est absent du DSN, il est injecté
    automatiquement.

    Returns:
        Objet connexion ``psycopg2`` prêt à l'emploi.

    Raises:
        SystemExit: Si ``DATABASE_URL`` est manquante ou si la connexion échoue.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL non définie dans le .env")
        sys.exit(1)

    # Supabase exige SSL obligatoirement pour les connexions externes
    if "sslmode" not in dsn:
        dsn += "?sslmode=require"

    try:
        conn = psycopg2.connect(dsn)
        logger.info("Connexion PostgreSQL (Supabase) établie avec succès.")
        return conn
    except psycopg2.Error as exc:
        logger.error(f"Échec connexion PostgreSQL : {exc}")
        sys.exit(1)


# -----------------------------------------------------------------------------
# 2. Requêtage natif du catalogue
# -----------------------------------------------------------------------------
def fetch_films_with_genres(
    pg_conn: psycopg2.extensions.connection,
) -> list[dict[str, Any]]:
    """
    Récupère l'intégralité du catalogue film avec leurs genres agrégés.

    Exécute une requête SQL native joignant les tables ``film``,
    ``film_genre`` et ``genre``. Les genres sont concaténés sous forme
    de chaîne unique ordonnée alphabétiquement via ``string_agg``.

    Args:
        pg_conn: Connexion psycopg2 active vers Supabase.

    Returns:
        Liste de dictionnaires où chaque clé correspond à une colonne
        du résultat SQL (``id_film``, ``titre``, ``tagline``,
        ``synopsis``, ``annee_sortie``, ``genres``).
    """
    query = """
        SELECT
            f.id_film,
            f.titre,
            f.tagline,
            f.synopsis,
            f.annee_sortie,
            COALESCE(string_agg(g.nom, ', ' ORDER BY g.nom), '') AS genres
        FROM film f
        LEFT JOIN film_genre fg ON f.id_film = fg.id_film
        LEFT JOIN genre g ON fg.id_genre = g.id_genre
        GROUP BY f.id_film, f.titre, f.tagline, f.synopsis, f.annee_sortie
        ORDER BY f.id_film;
    """
    logger.info("Récupération du catalogue et des genres via SQL...")

    with pg_conn.cursor() as cursor:
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    films = [dict(zip(columns, row)) for row in rows]
    logger.info(f"{len(films)} films récupérés depuis la base.")
    return films


# -----------------------------------------------------------------------------
# 3. Préparation du corpus textuel
# -----------------------------------------------------------------------------
def prepare_corpus(
    films: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Construit les documents textuels enrichis et leurs métadonnées associées.

    Chaque film est transformé en un bloc de texte structuré regroupant
    le titre, la tagline, l'année, les genres et le synopsis. Les champs
    potentiellement ``NULL`` en base (``tagline``, ``synopsis``) sont
    neutralisés. Les films dépourvus de titre ou de synopsis sont
    ignorés car non vectorisables.

    Args:
        films: Liste brute issue de :func:`fetch_films_with_genres`.

    Returns:
        Tuple contenant deux éléments ordonnés identiquement :

        1. ``documents_textes`` -- liste des chaînes destinées à être
           embeddingées.
        2. ``documents_meta`` -- liste des dictionnaires de métadonnées
           (``id_film``, ``titre``, ``annee_sortie``, ``genres``).
    """
    documents_textes: list[str] = []
    documents_meta: list[dict[str, Any]] = []

    for film in films:
        # Neutralisation des NULL PostgreSQL pour éviter AttributeError
        id_film = film.get("id_film")
        titre = (film.get("titre") or "").strip()
        tagline = (film.get("tagline") or "").strip()
        synopsis = (film.get("synopsis") or "").strip()
        genres = (film.get("genres") or "").strip()
        annee = film.get("annee_sortie")

        # Filtrage minimal : un film sans titre ou synopsis est inindexable
        if not titre or not synopsis:
            continue

        # Assemblage du texte enrichi
        parties = [f"Titre: {titre}"]
        if tagline:
            parties.append(f"Tagline: {tagline}")
        if annee:
            parties.append(f"Année: {annee}")
        if genres:
            parties.append(f"Genres: {genres}")
        parties.append(f"Synopsis: {synopsis}")

        texte = "\n".join(parties)

        documents_textes.append(texte)
        documents_meta.append(
            {
                "id_film": id_film,
                "titre": titre,
                "annee_sortie": annee,
                "genres": genres,
            }
        )

    total_initial = len(films)
    total_final = len(documents_textes)
    logger.info(f"{total_final} documents valides préparés pour l'indexation.")
    if total_final != total_initial:
        logger.warning(
            f"{total_initial - total_final} film(s) ignoré(s) "
            "car titre ou synopsis manquant."
        )

    return documents_textes, documents_meta


# -----------------------------------------------------------------------------
# 4. Génération des embeddings (Ollama local)
# -----------------------------------------------------------------------------
def generate_embeddings(texts: list[str]) -> tuple[np.ndarray, int]:
    """
    Produire les vecteurs denses via Ollama.

    Cette fonction utilise le modèle et l'endpoint définis dans
    ``src.config`` afin de garantir la cohérence stricte avec
    ``src.tools.rag_tool`` (même modèle et même endpoint pour
    l'indexation et la recherche sémantique).

    Paramètres
    ----------
    texts : list[str]
        Liste des documents bruts à encoder.

    Retourne
    -------
    tuple[np.ndarray, int]
        * ``vectors`` : tableau NumPy float32 de forme (n_texts, dim).
        * ``dim`` : dimension de chaque vecteur dense.
    """
    # Initialisation de l'embedder avec les paramètres centralisés.
    # Cela évite toute divergence entre la construction de l'index
    # et son utilisation en runtime.
    embedder = OllamaEmbeddings(
        model=OLLAMA_EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    logger.info(
        f"Génération de {len(texts)} embeddings avec le modèle "
        f"'{OLLAMA_EMBEDDING_MODEL}' sur l'endpoint '{OLLAMA_BASE_URL}'"
    )

    # Appel bloquant à Ollama (embedding batché côté LC).
    vectors = embedder.embed_documents(texts)
    embedding_dim = len(vectors[0])

    return np.array(vectors, dtype=np.float32), embedding_dim


# -----------------------------------------------------------------------------
# 5. Construction et persistance de l'index FAISS
# -----------------------------------------------------------------------------
def build_and_save_faiss_index(
    embeddings: np.ndarray,
    metadatas: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    """
    Assemble l'index FAISS et persiste les artefacts sur disque.

    L'index utilise la métrique ``InnerProduct`` (produit scalaire) sur
    des vecteurs préalablement normalisés en L2, ce qui équivaut
    mathématiquement à une recherche par similarité cosinus.

    Les fichiers produits sont :

    * ``horror_index.faiss`` -- index binaire FAISS.
    * ``metadata.pkl`` -- liste Python sérialisée des métadonnées.

    Args:
        embeddings: Matrice numpy ``(N, D)`` en ``float32``.
        metadatas: Liste ordonnée identiquement aux lignes d'``embeddings``.
        output_dir: Répertoire cible (créé récursivement si absent).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dimension = embeddings.shape[1]

    logger.info(
        f"Création de l'index FAISS "
        f"(dimension={dimension}, métrique=InnerProduct)..."
    )
    index = faiss.IndexFlatIP(dimension)

    # Normalisation L2 → InnerProduct = Cosine Similarity
    faiss.normalize_L2(embeddings)
    index.add(embeddings)

    logger.info(f"Nombre de vecteurs indexés dans FAISS : {index.ntotal}")

    # Persistance binaire
    chemin_index = output_dir / "horror_index.faiss"
    chemin_meta = output_dir / "metadata.pkl"

    faiss.write_index(index, str(chemin_index))
    logger.info(f"Index FAISS sauvegardé : {chemin_index}")

    with open(chemin_meta, "wb") as f:
        pickle.dump(metadatas, f)
    logger.info(f"Métadonnées sérialisées sauvegardées : {chemin_meta}")


# -----------------------------------------------------------------------------
# Point d'entrée principal
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Étape 1 : Connexion et extraction
    films_catalogue: list[dict[str, Any]] = []
    pg_conn = create_postgres_connection()
    try:
        films_catalogue = fetch_films_with_genres(pg_conn)
    finally:
        pg_conn.close()
        logger.info("Connexion PostgreSQL fermée.")

    if not films_catalogue:
        logger.error("Catalogue vide. Abandon.")
        sys.exit(1)

    # Étape 2 : Préparation du corpus
    documents_textes, documents_meta = prepare_corpus(films_catalogue)

    if not documents_textes:
        logger.error("Aucun document valide après nettoyage. Abandon.")
        sys.exit(1)

    # Étape 3 : Vectorisation
    vecteurs, dim = generate_embeddings(documents_textes)

    # Étape 4 : Indexation FAISS
    build_and_save_faiss_index(vecteurs, documents_meta, OUTPUT_DIR)

    logger.success(
        "=== Index FAISS généré et sauvegardé avec succès ===\n"
        f"Chemin : {OUTPUT_DIR}"
    )