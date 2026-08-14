"""
data_api/models.py
==================
Schémas Pydantic pour la validation des requêtes et des réponses.

Garantit que l'API interne parle toujours un langage fortement typé,
que ce soit en entrée (embedding, filtres) ou en sortie (fiches films).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FilmDetail(BaseModel):
    """
    Fiche cinématographique complète retournée par la base.
    """
    id_film: int
    titre: str
    annee_sortie: int | None = None
    langue_originale: str | None = None
    synopsis: str | None = None
    tagline: str | None = None
    duree: int | None = Field(
        default=None,
        description="Durée en minutes.",
    )
    budget: float | None = None
    revenue: float | None = None
    realisateur: str | None = Field(
        default=None,
        description="Nom du réalisateur (agrégation SQL).",
    )
    genres: list[str] = Field(
        default_factory=list,
        description="Liste des genres associés.",
    )
    casting: list[str] = Field(
        default_factory=list,
        description="Liste des acteurs principaux agrégés.",
    )


class SimilarityRequest(BaseModel):
    """
    Corps de la requête POST /films/similar (recherche pgvector).
    """
    embedding: list[float] = Field(
        ...,
        min_length=768,
        max_length=768,
        description="Vecteur de similarité (768 dims, nomic-embed-text).",
    )
    exclude_id_film: int | None = Field(
        default=None,
        description="Identifiant du film à exclure (généralement la source).",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Nombre maximum de voisins à retourner.",
    )


class SimilarityResult(FilmDetail):
    """
    Résultat de recherche vectoriel : un film + son score de similarité.
    """
    similarite: float = Field(
        ...,
        description="Score cosinus (1 - distance pgvector), entre 0 et 1.",
    )


class FilmSearchResponse(BaseModel):
    """
    Réponse paginée pour la recherche textuelle simple.
    """
    results: list[FilmDetail]
    total: int
    query: str
    limit: int