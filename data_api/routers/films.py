"""
data_api/routers/films.py
=========================
Endpoints métiers autour de la table ``film``.

Ce router est consommé exclusivement par l'API Intelligence
(``src/``). Il ne doit jamais être exposé publiquement sans
authentification (en production il sera derrière un réseau interne).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from data_api.database import get_db_connection

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# Schémas Pydantic (contrats d'entrée / sortie)
# ═══════════════════════════════════════════════════════════════

class Film(BaseModel):
    """
    Représentation d'une fiche cinématographique structurée.
    Tous les champs optionnels reflètent les colonnes NULLables de la base.
    """
    id_film: int
    titre: str
    annee_sortie: Optional[int] = None
    realisateur: Optional[str] = None
    genres: Optional[str] = None
    pays: Optional[str] = None
    synopsis: Optional[str] = None
    url_poster: Optional[str] = None


class SimilarityRequest(BaseModel):
    """
    Payload attendu par l'endpoint de recherche vectorielle.
    """

    embedding: List[float]
    limit: int = 5
    exclude_id: Optional[int] = Field(
        default=None,
        description=(
            "Identifiant à exclure (typiquement le film de référence "
            "pour éviter qu'il ne se retourne lui-même)."
        ),
    )


class SimilarityOut(BaseModel):
    """
    Résultat d'une recherche de similarité : film + score.
    """
    film: Film
    similarite: float


# ═══════════════════════════════════════════════════════════════
# Helper privé
# ═══════════════════════════════════════════════════════════════

def _row_to_film(row: dict) -> Film:
    """
    Convertit une ligne ``RealDictRow`` en modèle Pydantic ``Film``.

    Parameters
    ----------
    row : dict
        Ligne brute renvoyée par psycopg2.

    Returns
    -------
    Film
        Objet typé prêt à la sérialisation JSON.
    """
    return Film(
        id_film=row.get("id_film") or row.get("id") or 0,
        titre=row.get("titre", "Inconnu"),
        annee_sortie=row.get("annee_sortie"),
        realisateur=row.get("realisateur"),
        genres=row.get("genres"),
        pays=row.get("pays"),
        synopsis=row.get("synopsis"),
        url_poster=row.get("url_poster"),
    )


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════

@router.get(
    "/search",
    response_model=List[Film],
    summary="Recherche textuelle par titre",
)
def search_films(
    q: str = Query(
        ...,
        min_length=1,
        description="Fragment du titre (insensible à la casse).",
        examples=["conjuring"],
    ),
    limit: int = Query(10, ge=1, le=50, description="Nombre max de résultats."),
):
    """
    Retourne les films dont le titre correspond (``ILIKE``) au fragment
    fourni. La recherche est ordinée par année descendante.
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM film
                WHERE titre ILIKE %s
                ORDER BY annee_sortie DESC NULLS LAST
                LIMIT %s
                """,
                (f"%{q}%", limit),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Aucun film trouvé pour cette recherche.",
        )

    return [_row_to_film(r) for r in rows]


@router.get(
    "/{film_id}",
    response_model=Film,
    summary="Récupère un film par son ID",
)
def get_film(film_id: int):
    """
    Lecture directe d'une fiche via sa clé primaire ``id_film``.
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM film WHERE id_film = %s",
                (film_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Film non trouvé.")

    return _row_to_film(row)


@router.post(
    "/similar",
    response_model=List[SimilarityOut],
    summary="Recherche de similarité (pgvector)",
)
def find_similar(request: SimilarityRequest):
    """
    Exécute une recherche cosinus via l'extension ``pgvector``.

    L'endpoint attend un vecteur de 768 dimensions (``nomic-embed-text``)
    et renvoie les ``limit`` plus proches voisins avec leur score de
    similarité compris entre 0 (étranger) et 1 (identique).
    """
    embedding = request.embedding
    limit = request.limit
    exclude_id = request.exclude_id

    # ── Validation métier ──
    if len(embedding) != 768:
        raise HTTPException(
            status_code=400,
            detail=f"Dimension invalide : attendu 768, reçu {len(embedding)}.",
        )

    # Conversion en littéral PostgreSQL vector
    emb_str = "[" + ",".join(str(v) for v in embedding) + "]"

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if exclude_id is not None:
                cur.execute(
                    """
                    SELECT *, 1 - (embedding <=> %s::vector) AS similarite
                    FROM film
                    WHERE embedding IS NOT NULL
                      AND id_film != %s
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT %s
                    """,
                    (emb_str, exclude_id, emb_str, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT *, 1 - (embedding <=> %s::vector) AS similarite
                    FROM film
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT %s
                    """,
                    (emb_str, emb_str, limit),
                )
            rows = cur.fetchall()

    results: List[SimilarityOut] = []
    for r in rows:
        film = _row_to_film(r)
        # psycopg2 retourne parfois Decimal → cast explicite
        sim = float(r.get("similarite", 0.0))
        results.append(SimilarityOut(film=film, similarite=sim))

    return results