"""
tests/test_security.py
========================
Tests unitaires du module de sécurité (``src/auth/security.py``) :
hash de mots de passe (bcrypt) et cycle de vie des JWT.

Fonctions pures et déterministes (à secret/algorithme fixés) — aucun
mock nécessaire. La clé de signature réelle (``config.JWT_SECRET_KEY``)
est utilisée telle quelle : sa valeur n'a pas besoin d'être connue, seul
le cycle encode/decode est vérifié.
"""
from __future__ import annotations

from datetime import UTC, timedelta

import bcrypt
import jwt
import pytest

from src import config
from src.auth import security

# ═══════════════════════════════════════════════════════════════
# Mots de passe (bcrypt)
# ═══════════════════════════════════════════════════════════════

class TestVerifyPassword:
    def test_mot_de_passe_correct(self):
        password_hash = bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode()
        assert security.verify_password("secret123", password_hash) is True

    def test_mot_de_passe_incorrect(self):
        password_hash = bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode()
        assert security.verify_password("mauvais_mdp", password_hash) is False


# ═══════════════════════════════════════════════════════════════
# Création et décodage des JWT
# ═══════════════════════════════════════════════════════════════

class TestCreateAndDecodeToken:
    def test_access_token_roundtrip(self):
        token = security.create_access_token(subject="alice")
        payload = security.decode_token(token, expected_type="access")
        assert payload["sub"] == "alice"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        token = security.create_refresh_token(subject="alice")
        payload = security.decode_token(token, expected_type="refresh")
        assert payload["sub"] == "alice"
        assert payload["type"] == "refresh"

    def test_decode_avec_type_attendu_incorrect_leve_erreur(self):
        token = security.create_access_token(subject="bob")
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(token, expected_type="refresh")

    def test_decode_signature_alteree_leve_erreur(self):
        token = security.create_access_token(subject="bob")
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(token + "x", expected_type="access")

    def test_decode_token_expire_leve_erreur(self):
        token_expire = security._create_token(
            subject="alice", token_type="access", expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            security.decode_token(token_expire, expected_type="access")


# ═══════════════════════════════════════════════════════════════
# verify_access_token (couche haut-niveau utilisée par le middleware)
# ═══════════════════════════════════════════════════════════════

class TestVerifyAccessToken:
    def test_token_valide_retourne_le_username(self):
        token = security.create_access_token(subject="carol")
        assert security.verify_access_token(token) == "carol"

    def test_token_expire_leve_valueerror(self):
        token_expire = security._create_token(
            subject="carol", token_type="access", expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(ValueError, match="expiré"):
            security.verify_access_token(token_expire)

    def test_refresh_token_utilise_comme_access_leve_valueerror(self):
        refresh_token = security.create_refresh_token(subject="dave")
        with pytest.raises(ValueError):
            security.verify_access_token(refresh_token)

    def test_token_sans_sub_leve_valueerror(self):
        from datetime import datetime

        now = datetime.now(UTC)
        token_sans_sub = jwt.encode(
            {"type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
            config.JWT_SECRET_KEY,
            algorithm=config.JWT_ALGORITHM,
        )
        with pytest.raises(ValueError, match="sub"):
            security.verify_access_token(token_sans_sub)
