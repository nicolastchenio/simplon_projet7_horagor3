"""
tests/test_auth_endpoints.py
==============================
Tests unitaires des endpoints ``/auth/login`` et ``/auth/refresh``
(``src/api/auth.py``).

Le router est monté sur une application FastAPI minimale et jetable —
on n'importe jamais ``src.main`` (qui compile le graphe LangGraph complet
au démarrage), ce qui garde ces tests rapides et isolés.

``config.AUTH_USERNAME``/``AUTH_PASSWORD_HASH`` sont monkeypatchés avec
un couple utilisateur/mot de passe de test connu : le ``.env`` réel ne
contient que le hash, jamais le mot de passe en clair, donc impossible
de tester le chemin "identifiants corrects" sans ce monkeypatch.
"""
from __future__ import annotations

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import config
from src.api.auth import router as auth_router
from src.auth import security


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


@pytest.fixture
def test_credentials(monkeypatch):
    """Fige un couple utilisateur/mot de passe de test connu."""
    username = "testuser"
    password = "testpass123"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    monkeypatch.setattr(config, "AUTH_USERNAME", username)
    monkeypatch.setattr(config, "AUTH_PASSWORD_HASH", password_hash)
    return {"username": username, "password": password}


# ═══════════════════════════════════════════════════════════════
# POST /auth/login
# ═══════════════════════════════════════════════════════════════

class TestLogin:
    def test_login_reussi_retourne_les_deux_tokens(self, client, test_credentials):
        response = client.post("/auth/login", json=test_credentials)

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert security.decode_token(body["access_token"], "access")["sub"] == "testuser"
        assert security.decode_token(body["refresh_token"], "refresh")["sub"] == "testuser"

    def test_login_username_incorrect_401(self, client, test_credentials):
        response = client.post(
            "/auth/login",
            json={"username": "inconnu", "password": test_credentials["password"]},
        )
        assert response.status_code == 401

    def test_login_password_incorrect_401(self, client, test_credentials):
        response = client.post(
            "/auth/login",
            json={"username": test_credentials["username"], "password": "mauvais_mdp"},
        )
        assert response.status_code == 401

    def test_login_hash_non_configure_500(self, client, monkeypatch):
        monkeypatch.setattr(config, "AUTH_USERNAME", "testuser")
        monkeypatch.setattr(config, "AUTH_PASSWORD_HASH", "")
        response = client.post(
            "/auth/login", json={"username": "testuser", "password": "peu importe"}
        )
        assert response.status_code == 500


# ═══════════════════════════════════════════════════════════════
# POST /auth/refresh
# ═══════════════════════════════════════════════════════════════

class TestRefresh:
    def test_refresh_reussi_retourne_un_nouvel_access_token(self, client):
        refresh_token = security.create_refresh_token(subject="testuser")

        response = client.post("/auth/refresh", json={"refresh_token": refresh_token})

        assert response.status_code == 200
        body = response.json()
        assert body["refresh_token"] == refresh_token
        assert security.decode_token(body["access_token"], "access")["sub"] == "testuser"

    def test_refresh_avec_un_access_token_401(self, client):
        access_token = security.create_access_token(subject="testuser")

        response = client.post("/auth/refresh", json={"refresh_token": access_token})

        assert response.status_code == 401

    def test_refresh_token_invalide_401(self, client):
        response = client.post("/auth/refresh", json={"refresh_token": "ceci-nest-pas-un-jwt"})
        assert response.status_code == 401
