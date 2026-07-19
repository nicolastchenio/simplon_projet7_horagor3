"""
data_api/routers/films.py
========================
Router FastAPI exposant les opérations métiers sur le catalogue films.

Toutes les requêtes SQL sont centralisées ici ; l'API Intelligence
n'a plus jamais besoin de connaître le schéma PostgreSQL.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from psycopg2.extras import RealDictCursor
from rapidfuzz import fuzz, process

from data_api.database import get_db_connection

router = APIRouter()


# ------------------------------------------------------------------
# Utilitaire interne : normalisation des lignes SQL
# ------------------------------------------------------------------

def _normalize_film_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Transforme une ligne SQL (RealDictCursor) en dictionnaire JSON
    uniforme pour l'API Intelligence.

    Cette fonction gère les différences de noms de colonnes selon
    les requêtes (``realisateur_nom`` vs ``realisateur``, etc.).
    """
    film = dict(row)

    # Extraction défensive des champs agrégés
    real = film.pop("realisateur_nom", None) or film.pop("realisateur", None) or "Non spécifié"
    genres = film.pop("genres_liste", None) or film.pop("genres", None) or []
    cast_list = film.pop("casting_liste", None) or film.pop("casting", None) or []

    # La liste de casting devient une chaîne comme l'attend ``rag_tool.py``
    if isinstance(cast_list, list):
        casting_str = ", ".join(cast_list) if cast_list else "Non renseigné"
    else:
        casting_str = str(cast_list) if cast_list else "Non renseigné"

    film["realisateur"] = real if str(real).strip() else "Non spécifié"
    film["genres"] = genres if isinstance(genres, list) else []
    film["casting"] = casting_str

    # On s'assure que ``similarite`` reste présent si la requête la fournit
    return film


# ------------------------------------------------------------------
# 1. Recherche textuelle (ILIKE) avec jointures complètes
# ------------------------------------------------------------------

@router.get("/search")
def search_films(
    q: str = Query(..., min_length=1, description="Fragment du titre"),
    limit: int = Query(5, ge=1, le=50, description="Nombre maximum de résultats"),
) -> list[dict[str, Any]]:
    """
    Recherche de films par le titre (insensible à la casse).
    Retourne les métadonnées complètes avec réalisateur, genres et casting.
    """
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
            ) AS genres_liste,
            COALESCE(
                array_agg(DISTINCT a.nom)
                FILTER (WHERE a.nom IS NOT NULL),
                ARRAY[]::text[]
            ) AS casting_liste
        FROM film f
        LEFT JOIN realisateur r ON r.id_realisateur = f.id_realisateur
        LEFT JOIN film_genre fg ON fg.id_film = f.id_film
        LEFT JOIN genre g ON g.id_genre = fg.id_genre
        LEFT JOIN film_acteur fa ON fa.id_film = f.id_film
        LEFT JOIN acteur a ON a.id_acteur = fa.id_acteur
        WHERE f.titre ILIKE %s
        GROUP BY 
            f.id_film, f.titre, f.annee_sortie, f.langue_originale,
            f.synopsis, f.tagline, f.duree, f.budget, f.revenue,
            r.nom
        ORDER BY f.titre
        LIMIT %s
    """

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (f"%{q}%", limit))
            rows = cur.fetchall()

    return [_normalize_film_row(r) for r in rows]


# ------------------------------------------------------------------
# 2. Fuzzy matching (STATIC route — déclarée AVANT /{film_id})
# ------------------------------------------------------------------

@router.get("/fuzzy")
def fuzzy_find(
    title: str = Query(..., min_length=1, description="Titre approximatif"),
    score_cutoff: float = Query(60.0, ge=0.0, le=100.0),
) -> dict[str, Any]:
    """
    Corrige une orthographe approximative en comparant avec l'ensemble
    des titres du catalogue via ``rapidfuzz``.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id_film, titre FROM film WHERE titre IS NOT NULL")
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Aucun film disponible pour la comparaison.",
        )

    choices = {titre: id_f for id_f, titre in rows}

    result = process.extractOne(
        title,
        choices.keys(),
        scorer=fuzz.token_sort_ratio,
        processor=str.lower,
        score_cutoff=score_cutoff,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun match trouvé pour « {title} ».",
        )

    best_title, score, _ = result
    return {
        "id_film": choices[best_title],
        "titre": best_title,
        "score": round(float(score), 2),
    }


# ------------------------------------------------------------------
# 3. Lecture directe par ID (DYNAMIC route — déclarée APRÈS les statics)
# ------------------------------------------------------------------

@router.get("/{film_id}")
def get_film(film_id: int) -> dict[str, Any]:
    """
    Retourne la fiche complète d'un film par sa clé primaire.
    """
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
            ) AS genres_liste,
            COALESCE(
                array_agg(DISTINCT a.nom)
                FILTER (WHERE a.nom IS NOT NULL),
                ARRAY[]::text[]
            ) AS casting_liste
        FROM film f
        LEFT JOIN realisateur r ON r.id_realisateur = f.id_realisateur
        LEFT JOIN film_genre fg ON fg.id_film = f.id_film
        LEFT JOIN genre g ON g.id_genre = fg.id_genre
        LEFT JOIN film_acteur fa ON fa.id_film = f.id_film
        LEFT JOIN acteur a ON a.id_acteur = fa.id_acteur
        WHERE f.id_film = %s
        GROUP BY 
            f.id_film, f.titre, f.annee_sortie, f.langue_originale,
            f.synopsis, f.tagline, f.duree, f.budget, f.revenue,
            r.nom
    """

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (film_id,))
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Film non trouvé.")

    return _normalize_film_row(row)


# ------------------------------------------------------------------
# 4. Similarité pgvector par ID
# ------------------------------------------------------------------

@router.get("/{film_id}/similar")
def get_similar_films(
    film_id: int,
    k: int = Query(5, ge=1, le=20, description="Nombre de voisins à retourner"),
) -> list[dict[str, Any]]:
    """
    Retourne les films les plus similaires au film ``film_id`` via
    l'index pgvector (distance cosinus).
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # -- Vérification préalable (CORRECTION : alias has_embedding) --
            cur.execute(
                "SELECT embedding IS NOT NULL AS has_embedding FROM film WHERE id_film = %s",
                (film_id,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Film {film_id} introuvable.",
                )
            if not row["has_embedding"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Film {film_id} trouvé mais colonne embedding NULL.",
                )

            # -- Requête pgvector --
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
                    ) AS genres_liste,
                    COALESCE(
                        array_agg(DISTINCT a.nom)
                        FILTER (WHERE a.nom IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS casting_liste,
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
                GROUP BY 
                    f.id_film, f.titre, f.annee_sortie, f.langue_originale,
                    f.synopsis, f.tagline, f.duree, f.budget, f.revenue,
                    r.nom
                ORDER BY f.embedding <=> (
                    SELECT ref.embedding FROM film ref WHERE ref.id_film = %s
                )
                LIMIT %s
            """
            cur.execute(sql, (film_id, film_id, film_id, k))
            rows = cur.fetchall()

    return [_normalize_film_row(r) for r in rows]