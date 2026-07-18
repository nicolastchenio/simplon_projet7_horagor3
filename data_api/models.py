"""
data_api/models.py
==================
Schémas Pydantic pour la validation des requêtes et des réponses.

Garantit que l'API interne parle toujours un langage fortement typé,
que ce soit en entrée (embedding, filtres) ou en sortie (fiches films).
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


class FilmDetail(BaseModel):
    """
    Fiche cinématographique complète retournée par la base.
    """
    id_film: int
    titre: str
    annee_sortie: Optional[int] = None
    langue_originale: Optional[str] = None
    synopsis: Optional[str] = None
    tagline: Optional[str] = None
    duree: Optional[int] = Field(
        default=None,
        description="Durée en minutes.",
    )
    budget: Optional[float] = None
    revenue: Optional[float] = None
    realisateur: Optional[str] = Field(
        default=None,
        description="Nom du réalisateur (agrégation SQL).",
    )
    genres: List[str] = Field(
        default_factory=list,
        description="Liste des genres associés.",
    )
    casting: List[str] = Field(
        default_factory=list,
        description="Liste des acteurs principaux agrégés.",
    )


class SimilarityRequest(BaseModel):
    """
    Corps de la requête POST /films/similar (recherche pgvector).
    """
    embedding: List[float] = Field(
        ...,
        min_length=768,
        max_length=768,
        description="Vecteur de similarité (768 dims, nomic-embed-text).",
    )
    exclude_id_film: Optional[int] = Field(
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
    results: List[FilmDetail]
    total: int
    query: str
    limit: int