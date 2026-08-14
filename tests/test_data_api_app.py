"""
tests/test_data_api_app.py
============================
Tests unitaires de l'application data-api elle-même
(``data_api/main.py``, ``data_api/config.py``, ``data_api/models.py``),
non couverts par ``test_data_api_films.py`` (qui monte le router seul
sur une app FastAPI jetable, sans jamais importer ``data_api.main``).

Stratégie de mock :
- ``data_api.main`` est importé pour de vrai (déclenche ``setup_logging()``,
  le montage du router et l'instrumentation Prometheus) ; seul
  ``get_db_connection`` est mocké (comme dans ``test_data_api_films.py``)
  pour éviter toute vraie connexion PostgreSQL.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import data_api.config as data_api_config
import data_api.main as data_api_main
from data_api.models import (
    FilmDetail,
    FilmSearchResponse,
    SimilarityRequest,
    SimilarityResult,
)
from data_api.routers import films

# ═══════════════════════════════════════════════════════════════
# data_api/config.py
# ═══════════════════════════════════════════════════════════════

class TestDataApiConfig:
    def test_constantes_exposees_avec_defauts_coherents(self):
        assert isinstance(data_api_config.LOG_DIR, type(data_api_config.PROJECT_ROOT))
        assert data_api_config.LOG_LEVEL in ("DEBUG", "INFO", "WARNING", "ERROR")
        assert isinstance(data_api_config.LOG_JSON, bool)
        assert data_api_config.LOG_FILE_MAX_BYTES > 0
        assert data_api_config.LOG_FILE_BACKUP_COUNT >= 1
        assert data_api_config.LOG_DIR.exists()


# ═══════════════════════════════════════════════════════════════
# data_api/models.py
# ═══════════════════════════════════════════════════════════════

class TestFilmDetail:
    def test_instanciation_minimale_applique_les_defauts(self):
        film = FilmDetail(id_film=1, titre="The Exorcist")

        assert film.genres == []
        assert film.casting == []
        assert film.annee_sortie is None

    def test_id_film_manquant_leve_validation_error(self):
        with pytest.raises(ValidationError):
            FilmDetail(titre="The Exorcist")


class TestSimilarityRequest:
    def test_embedding_valide_avec_limit_par_defaut(self):
        request = SimilarityRequest(embedding=[0.1] * 768)

        assert request.limit == 5
        assert request.exclude_id_film is None

    def test_embedding_taille_invalide_leve_validation_error(self):
        with pytest.raises(ValidationError):
            SimilarityRequest(embedding=[0.1] * 10)

    @pytest.mark.parametrize("limit", [0, 21])
    def test_limit_hors_bornes_leve_validation_error(self, limit):
        with pytest.raises(ValidationError):
            SimilarityRequest(embedding=[0.1] * 768, limit=limit)


class TestSimilarityResult:
    def test_herite_de_film_detail_et_exige_similarite(self):
        result = SimilarityResult(id_film=2, titre="It", similarite=0.87)

        assert result.similarite == 0.87
        assert result.genres == []

        with pytest.raises(ValidationError):
            SimilarityResult(id_film=2, titre="It")


class TestFilmSearchResponse:
    def test_construction_avec_liste_de_films(self):
        response = FilmSearchResponse(
            results=[FilmDetail(id_film=1, titre="It")],
            total=1,
            query="It",
            limit=10,
        )

        assert response.total == 1
        assert response.results[0].titre == "It"


# ═══════════════════════════════════════════════════════════════
# data_api/main.py
# ═══════════════════════════════════════════════════════════════

class FakeCursor:
    """Curseur factice minimal (cf. test_data_api_films.py)."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)

    def execute(self, sql: str, params: tuple | None = None) -> None:
        pass

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
    return TestClient(data_api_main.app)


class TestHealthEndpoint:
    def test_health_check_ok(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "data-api"}


class TestFilmsRouterMonteSurLaVraieApp:
    def test_recherche_films_via_app_reelle(self, client, monkeypatch):
        cursor = FakeCursor(
            responses=[
                [
                    {
                        "id_film": 1,
                        "titre": "The Exorcist",
                        "annee_sortie": 1973,
                        "realisateur_nom": "William Friedkin",
                        "genres_liste": ["Horror"],
                        "casting_liste": ["Actor A"],
                    }
                ]
            ]
        )
        monkeypatch.setattr(films, "get_db_connection", lambda: FakeConnection(cursor))

        response = client.get("/films/search", params={"q": "Exorcist"})

        assert response.status_code == 200
        assert response.json()[0]["titre"] == "The Exorcist"


class TestMetricsEndpoint:
    def test_metrics_expose_par_instrumentator(self, client):
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.text
