"""
tests/test_rag_tool.py
========================
Tests unitaires des outils RAG (``src/tools/rag_tool.py``).

Stratégie de mock :
- FAISS : les singletons module-level (``_faiss_index``, ``_faiss_metadata``,
  ``_ollama_embedder``) sont remplacés directement par des fakes en mémoire
  (aucun vrai fichier ``.faiss``/``.pkl`` chargé, aucun appel Ollama réel),
  sauf dans ``TestLoadFaissResources`` qui teste le chargement disque
  lui-même via un ``tmp_path``.
- data-api : ``httpx.Client`` est remplacé par un faux client
  (``FakeHttpxClient``/``FakeHttpxResponse``) rejouant des réponses
  construites à la main — aucune vraie requête HTTP n'est émise.
"""
from __future__ import annotations

import pickle
from typing import Any

import httpx
import numpy as np
import pytest

from src.tools import rag_tool

# ═══════════════════════════════════════════════════════════════
# Fakes communs
# ═══════════════════════════════════════════════════════════════

class FakeFaissIndex:
    """Index FAISS factice : ``search()`` rejoue des distances/indices fixés."""

    def __init__(self, distances: list[float], indices: list[int]):
        self._distances = np.array([distances], dtype=np.float32)
        self._indices = np.array([indices], dtype=np.int64)
        self.ntotal = len(indices)
        self.d = 768

    def search(self, query_np, top_k):
        return self._distances, self._indices


class FakeEmbedder:
    """Embedder Ollama factice : renvoie un vecteur fixe ou lève une erreur."""

    def __init__(self, vector: list[float] | None = None, raise_exc: Exception | None = None):
        self._vector = vector if vector is not None else [0.1] * 768
        self._raise_exc = raise_exc

    def embed_query(self, text: str):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._vector


class FakeHttpxResponse:
    """Réponse ``httpx`` factice : ``raise_for_status()`` lève une vraie
    ``httpx.HTTPStatusError`` si le code simulé est une erreur."""

    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.request = httpx.Request("GET", "http://data-api.test")

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=self
            )


class FakeHttpxClient:
    """Client ``httpx`` factice : rejoue une réponse ou lève une exception
    réseau pré-configurée, et journalise les appels ``get()`` reçus."""

    def __init__(
        self,
        response: FakeHttpxResponse | None = None,
        raise_exc: Exception | None = None,
    ):
        self._response = response
        self._raise_exc = raise_exc
        self.calls: list[tuple[str, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self, url: str, params: dict | None = None):
        self.calls.append((url, params))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


def _patch_httpx_client(monkeypatch, fake_client: FakeHttpxClient) -> None:
    monkeypatch.setattr(rag_tool.httpx, "Client", lambda **kwargs: fake_client)


# ═══════════════════════════════════════════════════════════════
# _load_faiss_resources (chargement disque + singleton)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_faiss_singleton():
    """Réinitialise les singletons FAISS avant/après chaque test pour
    garantir l'isolation (le module les garde en mémoire entre appels)."""
    rag_tool._faiss_index = None
    rag_tool._faiss_metadata = None
    rag_tool._ollama_embedder = None
    yield
    rag_tool._faiss_index = None
    rag_tool._faiss_metadata = None
    rag_tool._ollama_embedder = None


class TestLoadFaissResources:
    def test_cache_hit_ne_touche_pas_le_disque(self, monkeypatch):
        fake_index = FakeFaissIndex(distances=[0.9], indices=[0])
        fake_metas = [{"titre": "The Exorcist"}]
        fake_embedder = FakeEmbedder()
        rag_tool._faiss_index = fake_index
        rag_tool._faiss_metadata = fake_metas
        rag_tool._ollama_embedder = fake_embedder

        called = []
        monkeypatch.setattr(
            rag_tool.faiss, "read_index", lambda path: called.append(path)
        )

        index, metas, embedder = rag_tool._load_faiss_resources()

        assert index is fake_index
        assert metas is fake_metas
        assert embedder is fake_embedder
        assert called == []

    def test_index_manquant_leve_file_not_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rag_tool, "FAISS_INDEX_DIR", tmp_path)

        with pytest.raises(FileNotFoundError):
            rag_tool._load_faiss_resources()

    def test_metadata_manquante_leve_file_not_found(self, monkeypatch, tmp_path):
        (tmp_path / "horror_index.faiss").write_bytes(b"")
        monkeypatch.setattr(rag_tool, "FAISS_INDEX_DIR", tmp_path)

        with pytest.raises(FileNotFoundError):
            rag_tool._load_faiss_resources()

    def test_chargement_reussi_peuple_les_singletons(self, monkeypatch, tmp_path):
        (tmp_path / "horror_index.faiss").write_bytes(b"")
        (tmp_path / "metadata.pkl").write_bytes(b"")
        monkeypatch.setattr(rag_tool, "FAISS_INDEX_DIR", tmp_path)

        fake_index = FakeFaissIndex(distances=[0.9], indices=[0])
        fake_metas = [{"titre": "The Exorcist"}]
        fake_embedder = FakeEmbedder()
        monkeypatch.setattr(rag_tool.faiss, "read_index", lambda path: fake_index)
        monkeypatch.setattr(pickle, "load", lambda fh: fake_metas)
        monkeypatch.setattr(
            rag_tool, "OllamaEmbeddings", lambda **kwargs: fake_embedder
        )

        index, metas, embedder = rag_tool._load_faiss_resources()

        assert index is fake_index
        assert metas is fake_metas
        assert embedder is fake_embedder
        assert rag_tool._faiss_index is fake_index
        assert rag_tool._faiss_metadata is fake_metas
        assert rag_tool._ollama_embedder is fake_embedder


# ═══════════════════════════════════════════════════════════════
# search_local_horror_lore
# ═══════════════════════════════════════════════════════════════

class TestSearchLocalHorrorLore:
    def _set_faiss(self, distances, indices, metas, embedder=None):
        rag_tool._faiss_index = FakeFaissIndex(distances, indices)
        rag_tool._faiss_metadata = metas
        rag_tool._ollama_embedder = embedder or FakeEmbedder()

    def test_resultats_normaux(self):
        self._set_faiss(
            distances=[0.9, 0.5],
            indices=[0, 1],
            metas=[
                {"titre": "The Exorcist", "annee_sortie": 1973, "genres": "Horror"},
                {"titre": "It", "annee_sortie": 2017, "genres": "Horror, Drama"},
            ],
        )

        results = rag_tool.search_local_horror_lore("film de démon")

        assert len(results) == 2
        assert results[0]["score"] == pytest.approx(0.9)
        assert "The Exorcist" in results[0]["chunk"]
        assert "1973" in results[0]["chunk"]
        assert results[0]["metadata"]["source"] == "faiss_local"
        assert results[1]["metadata"]["titre"] == "It"

    def test_indice_invalide_est_ignore(self):
        self._set_faiss(
            distances=[0.9, 0.5],
            indices=[0, 5],
            metas=[{"titre": "The Exorcist", "annee_sortie": 1973}],
        )

        results = rag_tool.search_local_horror_lore("film de démon")

        assert len(results) == 1
        assert results[0]["metadata"]["titre"] == "The Exorcist"

    def test_aucun_resultat_retourne_liste_vide(self):
        self._set_faiss(
            distances=[0.0, 0.0],
            indices=[-1, -1],
            metas=[{"titre": "The Exorcist"}],
        )

        results = rag_tool.search_local_horror_lore("requête sans rapport")

        assert results == []

    def test_echec_embedding_est_propage(self):
        self._set_faiss(
            distances=[0.9],
            indices=[0],
            metas=[{"titre": "The Exorcist"}],
            embedder=FakeEmbedder(raise_exc=RuntimeError("Ollama injoignable")),
        )

        with pytest.raises(RuntimeError, match="Ollama injoignable"):
            rag_tool.search_local_horror_lore("film de démon")


# ═══════════════════════════════════════════════════════════════
# query_movie_metadata
# ═══════════════════════════════════════════════════════════════

class TestQueryMovieMetadata:
    def test_sans_titre_ni_id_leve_value_error(self):
        with pytest.raises(ValueError):
            rag_tool.query_movie_metadata()

    def test_par_id_film_succes(self, monkeypatch):
        fake_client = FakeHttpxClient(
            response=FakeHttpxResponse(200, json_data={"id_film": 1, "titre": "It"})
        )
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.query_movie_metadata(id_film=1)

        assert result == [{"id_film": 1, "titre": "It"}]
        assert fake_client.calls[0][0] == f"{rag_tool.DATA_API_URL}/films/1"

    def test_par_id_film_404_retourne_liste_vide(self, monkeypatch):
        fake_client = FakeHttpxClient(response=FakeHttpxResponse(404))
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.query_movie_metadata(id_film=999)

        assert result == []

    def test_par_id_film_erreur_http_est_propagee(self, monkeypatch):
        fake_client = FakeHttpxClient(response=FakeHttpxResponse(500, text="boom"))
        _patch_httpx_client(monkeypatch, fake_client)

        with pytest.raises(httpx.HTTPStatusError):
            rag_tool.query_movie_metadata(id_film=1)

    def test_par_titre_succes(self, monkeypatch):
        fake_client = FakeHttpxClient(
            response=FakeHttpxResponse(200, json_data=[{"titre": "Halloween"}])
        )
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.query_movie_metadata(titre="Halloween", top_k=3)

        assert result == [{"titre": "Halloween"}]
        assert fake_client.calls[0][1] == {"q": "Halloween", "limit": 3}

    def test_timeout_reseau_est_propage(self, monkeypatch):
        fake_client = FakeHttpxClient(raise_exc=httpx.TimeoutException("timeout"))
        _patch_httpx_client(monkeypatch, fake_client)

        with pytest.raises(httpx.TimeoutException):
            rag_tool.query_movie_metadata(titre="Halloween")


# ═══════════════════════════════════════════════════════════════
# find_similar_horror_movies
# ═══════════════════════════════════════════════════════════════

class TestFindSimilarHorrorMovies:
    def test_succes_retourne_les_voisins(self, monkeypatch):
        fake_client = FakeHttpxClient(
            response=FakeHttpxResponse(
                200,
                json_data=[
                    {"id_film": 2, "titre": "It", "similarite": 0.87},
                    {"id_film": 3, "titre": "It Chapter Two", "similarite": 0.81},
                ],
            )
        )
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.find_similar_horror_movies(id_film=1, k=2)

        assert len(result) == 2
        assert result[0]["titre"] == "It"

    def test_film_introuvable_leve_runtime_error(self, monkeypatch):
        fake_client = FakeHttpxClient(response=FakeHttpxResponse(404))
        _patch_httpx_client(monkeypatch, fake_client)

        with pytest.raises(RuntimeError, match="introuvable"):
            rag_tool.find_similar_horror_movies(id_film=999)

    def test_embedding_null_leve_runtime_error_avec_detail(self, monkeypatch):
        fake_client = FakeHttpxClient(
            response=FakeHttpxResponse(
                400, json_data={"detail": "Colonne embedding NULL"}
            )
        )
        _patch_httpx_client(monkeypatch, fake_client)

        with pytest.raises(RuntimeError, match="embedding NULL"):
            rag_tool.find_similar_horror_movies(id_film=1)

    def test_liste_vide_ne_plante_pas(self, monkeypatch):
        fake_client = FakeHttpxClient(response=FakeHttpxResponse(200, json_data=[]))
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.find_similar_horror_movies(id_film=1)

        assert result == []


# ═══════════════════════════════════════════════════════════════
# fuzzy_find_film
# ═══════════════════════════════════════════════════════════════

class TestFuzzyFindFilm:
    def test_succes_retourne_le_candidat(self, monkeypatch):
        fake_client = FakeHttpxClient(
            response=FakeHttpxResponse(
                200, json_data={"id_film": 42, "titre": "Halloween", "score": 95.0}
            )
        )
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.fuzzy_find_film("Hallowen")

        assert result == {"id_film": 42, "titre": "Halloween", "score": 95.0}

    def test_aucun_candidat_retourne_none(self, monkeypatch):
        fake_client = FakeHttpxClient(response=FakeHttpxResponse(404))
        _patch_httpx_client(monkeypatch, fake_client)

        result = rag_tool.fuzzy_find_film("xxxxxxxxx")

        assert result is None

    def test_erreur_http_est_propagee(self, monkeypatch):
        fake_client = FakeHttpxClient(response=FakeHttpxResponse(500))
        _patch_httpx_client(monkeypatch, fake_client)

        with pytest.raises(httpx.HTTPStatusError):
            rag_tool.fuzzy_find_film("Halloween")


# ═══════════════════════════════════════════════════════════════
# resolve_film
# ═══════════════════════════════════════════════════════════════

class TestResolveFilm:
    def test_match_trouve_retourne_id_film(self, monkeypatch):
        monkeypatch.setattr(
            rag_tool,
            "fuzzy_find_film",
            lambda raw_title, score_cutoff=60.0: {
                "id_film": 7,
                "titre": "Saw",
                "score": 88.0,
            },
        )

        assert rag_tool.resolve_film("Sawe") == 7

    def test_aucun_match_leve_runtime_error(self, monkeypatch):
        monkeypatch.setattr(
            rag_tool, "fuzzy_find_film", lambda raw_title, score_cutoff=60.0: None
        )

        with pytest.raises(RuntimeError, match="Aucun film trouvé"):
            rag_tool.resolve_film("zzzzzzzz")
