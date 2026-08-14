"""
tests/test_integration_chat.py
================================
Tests d'intégration (Phase 10.2) : flux complet à travers l'API
Intelligence réelle (``src.main.app``), lifespan compris.

Contrairement aux tests unitaires (``test_nodes.py``, ``test_router.py``),
ici on n'appelle plus les nœuds directement : on invoque le vrai graphe
compilé (``build_horragor_graph``) via l'endpoint HTTP ``/chat``, pour
valider le câblage RAG → Router → (Scraper) → Narration de bout en bout.

Seules les frontières externes réelles sont mockées (LLM Ollama, FAISS,
Wikipédia) — la logique de routage, l'authentification JWT et
l'extraction des sources sont, elles, testées pour de vrai.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src import config
from src.auth import security
from src.graph import nodes
from src.main import app


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _fake_llm(content: str = "Une chronique gothique complète.") -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content=content)
    return llm


@pytest.fixture
def access_token() -> str:
    return security.create_access_token(subject="testuser")


# ═══════════════════════════════════════════════════════════════
# Flux RAG → Narration (direct)
# ═══════════════════════════════════════════════════════════════

class TestFluxRagVersNarration:
    def test_flux_direct_sans_scraper(self, monkeypatch, access_token):
        monkeypatch.setattr(
            nodes,
            "search_local_horror_lore",
            lambda query, **kw: [
                {"score": 0.9, "text": "Regan est possédée...", "source": "lore_exorcist.txt"}
            ],
        )
        monkeypatch.setattr(
            nodes,
            "query_movie_metadata",
            lambda query, **kw: [{"id": 1, "title": "The Exorcist", "year": 1973}],
        )
        monkeypatch.setattr(nodes, "_get_narrator_llm", lambda: _fake_llm())
        enrich_mock = MagicMock()
        monkeypatch.setattr(nodes, "enrich_from_web", enrich_mock)

        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"message": "Parle-moi de The Exorcist"},
                headers=_auth_headers(access_token),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["response"] == "Une chronique gothique complète."
        assert body["used_web"] is False
        assert {"type": "sql", "id": 1, "title": "The Exorcist", "year": 1973} in body["sources"]
        faiss_sources = [s for s in body["sources"] if s["type"] == "faiss"]
        assert faiss_sources and faiss_sources[0]["title"] == "lore_exorcist.txt"
        enrich_mock.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# Flux RAG → Scraper → Narration
# ═══════════════════════════════════════════════════════════════

class TestFluxRagVersScraperVersNarration:
    def test_flux_avec_enrichissement_web(self, monkeypatch, access_token):
        monkeypatch.setattr(nodes, "search_local_horror_lore", lambda query, **kw: [])
        monkeypatch.setattr(nodes, "query_movie_metadata", lambda query, **kw: [])
        monkeypatch.setattr(
            nodes, "enrich_from_web", lambda title: "Contenu Wikipédia trouvé."
        )
        monkeypatch.setattr(nodes, "_get_narrator_llm", lambda: _fake_llm())

        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"message": "Le film avec un clown qui tue des enfants dans les égouts"},
                headers=_auth_headers(access_token),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["used_web"] is True
        assert any(s["type"] == "web" for s in body["sources"])


# ═══════════════════════════════════════════════════════════════
# Protection JWT sur /chat
# ═══════════════════════════════════════════════════════════════

class TestChatProtectionJWT:
    def test_sans_header_authorization(self):
        with TestClient(app) as client:
            response = client.post("/chat", json={"message": "peu importe"})
        assert response.status_code == 401

    def test_avec_token_invalide(self):
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"message": "peu importe"},
                headers=_auth_headers("ceci-nest-pas-un-jwt"),
            )
        assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════
# Flux d'authentification complet : login → accès protégé → refresh
# ═══════════════════════════════════════════════════════════════

class TestFluxAuthentificationComplet:
    def test_login_puis_chat_puis_refresh_puis_chat(self, monkeypatch):
        import bcrypt

        username, password = "testuser", "testpass123"
        monkeypatch.setattr(config, "AUTH_USERNAME", username)
        monkeypatch.setattr(
            config,
            "AUTH_PASSWORD_HASH",
            bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        )
        monkeypatch.setattr(nodes, "search_local_horror_lore", lambda query, **kw: [])
        monkeypatch.setattr(
            nodes, "query_movie_metadata", lambda query, **kw: [{"id": 1, "title": "It"}]
        )
        monkeypatch.setattr(nodes, "_get_narrator_llm", lambda: _fake_llm())

        with TestClient(app) as client:
            # 1. Login
            login_resp = client.post(
                "/auth/login", json={"username": username, "password": password}
            )
            assert login_resp.status_code == 200
            tokens = login_resp.json()

            # 2. Accès protégé avec l'access_token obtenu
            chat_resp = client.post(
                "/chat",
                json={"message": "Parle-moi de It"},
                headers=_auth_headers(tokens["access_token"]),
            )
            assert chat_resp.status_code == 200

            # 3. Refresh
            refresh_resp = client.post(
                "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert refresh_resp.status_code == 200
            new_access_token = refresh_resp.json()["access_token"]
            # Remarque : à la même seconde, un JWT re-émis pour le même
            # sujet est légitimement identique (mêmes claims sub/type/iat/exp) —
            # on vérifie donc sa validité, pas une différence de valeur.
            assert security.decode_token(new_access_token, "access")["sub"] == username

            # 4. Le nouvel access_token donne aussi accès à /chat
            chat_resp_2 = client.post(
                "/chat",
                json={"message": "Encore It"},
                headers=_auth_headers(new_access_token),
            )
            assert chat_resp_2.status_code == 200

            # 5. Un refresh_token n'est pas un access_token valide sur /chat
            chat_resp_3 = client.post(
                "/chat",
                json={"message": "Tentative avec un refresh_token"},
                headers=_auth_headers(tokens["refresh_token"]),
            )
            assert chat_resp_3.status_code == 401


# ═══════════════════════════════════════════════════════════════
# /health
# ═══════════════════════════════════════════════════════════════

def test_health_check_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
