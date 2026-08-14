"""
tests/test_data_api_films.py
==============================
Tests unitaires des endpoints ``/films/*`` du service Données
(``data_api/routers/films.py``), avec la connexion PostgreSQL mockée.

``get_db_connection`` est remplacé par une fausse connexion/curseur qui
rejoue des lignes construites à la main — aucune vraie requête Supabase
n'est exécutée.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from data_api.routers import films


class FakeCursor:
    """Curseur factice : chaque appel fetchone()/fetchall() consomme la
    prochaine réponse pré-enregistrée, dans l'ordre où elles ont été
    fournies (reflète l'ordre réel des appels execute() du endpoint)."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.queries: list[tuple] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.queries.append((sql, params))

    def fetchone(self):
        return self._responses.pop(0) if self._responses else None

    def fetchall(self):
        return self._responses.pop(0) if self._responses else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self, *args, **kwargs) -> FakeCursor:
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(films.router, prefix="/films")
    return TestClient(app)


def _mock_db(monkeypatch, responses: list[Any]) -> FakeCursor:
    cursor = FakeCursor(responses)
    monkeypatch.setattr(films, "get_db_connection", lambda: FakeConnection(cursor))
    return cursor


# ═══════════════════════════════════════════════════════════════
# GET /films/search
# ═══════════════════════════════════════════════════════════════

class TestSearchFilms:
    def test_recherche_normalise_les_champs_agreges(self, client, monkeypatch):
        _mock_db(
            monkeypatch,
            responses=[
                [
                    {
                        "id_film": 1,
                        "titre": "The Exorcist",
                        "annee_sortie": 1973,
                        "realisateur_nom": "William Friedkin",
                        "genres_liste": ["Horror"],
                        "casting_liste": ["Actor A", "Actor B"],
                    }
                ]
            ],
        )

        response = client.get("/films/search", params={"q": "Exorcist"})

        assert response.status_code == 200
        film = response.json()[0]
        assert film["realisateur"] == "William Friedkin"
        assert film["genres"] == ["Horror"]
        assert film["casting"] == "Actor A, Actor B"
        assert "realisateur_nom" not in film
        assert "genres_liste" not in film

    def test_recherche_sans_query_param_422(self, client, monkeypatch):
        _mock_db(monkeypatch, responses=[[]])
        response = client.get("/films/search")
        assert response.status_code == 422

    def test_recherche_realisateur_absent_devient_non_specifie(self, client, monkeypatch):
        _mock_db(
            monkeypatch,
            responses=[[{"id_film": 2, "titre": "Film Obscur", "realisateur_nom": None}]],
        )
        response = client.get("/films/search", params={"q": "Obscur"})
        assert response.json()[0]["realisateur"] == "Non spécifié"


# ═══════════════════════════════════════════════════════════════
# GET /films/fuzzy
# ═══════════════════════════════════════════════════════════════

class TestFuzzyFind:
    def test_match_trouve(self, client, monkeypatch):
        _mock_db(
            monkeypatch,
            responses=[[(1, "The Exorcist"), (2, "The Conjuring")]],
        )
        response = client.get(
            "/films/fuzzy", params={"title": "exorcist", "score_cutoff": 50}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id_film"] == 1
        assert body["titre"] == "The Exorcist"

    def test_aucun_film_en_base_404(self, client, monkeypatch):
        _mock_db(monkeypatch, responses=[[]])
        response = client.get("/films/fuzzy", params={"title": "peu importe"})
        assert response.status_code == 404

    def test_aucun_match_au_dessus_du_seuil_404(self, client, monkeypatch):
        _mock_db(monkeypatch, responses=[[(1, "The Exorcist")]])
        response = client.get(
            "/films/fuzzy", params={"title": "zzzzzzzzzz", "score_cutoff": 99}
        )
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════
# GET /films/{film_id}
# ═══════════════════════════════════════════════════════════════

class TestGetFilm:
    def test_film_trouve(self, client, monkeypatch):
        _mock_db(
            monkeypatch,
            responses=[
                {
                    "id_film": 1,
                    "titre": "The Exorcist",
                    "realisateur_nom": "William Friedkin",
                    "genres_liste": ["Horror"],
                    "casting_liste": [],
                }
            ],
        )
        response = client.get("/films/1")
        assert response.status_code == 200
        assert response.json()["titre"] == "The Exorcist"

    def test_film_introuvable_404(self, client, monkeypatch):
        _mock_db(monkeypatch, responses=[None])
        response = client.get("/films/999")
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════
# GET /films/{film_id}/similar
# ═══════════════════════════════════════════════════════════════

class TestGetSimilarFilms:
    def test_similaires_retournes(self, client, monkeypatch):
        _mock_db(
            monkeypatch,
            responses=[
                {"has_embedding": True},
                [
                    {
                        "id_film": 2,
                        "titre": "It",
                        "similarite": 0.91,
                        "realisateur_nom": "Andy Muschietti",
                        "genres_liste": ["Horror"],
                        "casting_liste": [],
                    }
                ],
            ],
        )
        response = client.get("/films/1/similar", params={"k": 3})
        assert response.status_code == 200
        assert response.json()[0]["similarite"] == 0.91

    def test_film_introuvable_404(self, client, monkeypatch):
        _mock_db(monkeypatch, responses=[None])
        response = client.get("/films/999/similar")
        assert response.status_code == 404

    def test_film_sans_embedding_400(self, client, monkeypatch):
        _mock_db(monkeypatch, responses=[{"has_embedding": False}])
        response = client.get("/films/1/similar")
        assert response.status_code == 400
