"""Module de sécurité : gestion des mots de passe et des tokens JWT.

Ce module centralise toute la logique cryptographique de l'application :

* vérification du mot de passe utilisateur (via bcrypt) ;
* création des *access tokens* (courte durée) et *refresh tokens* (longue durée) ;
* décodage et validation des tokens JWT.

Aucun autre module ne doit manipuler directement les JWT ou bcrypt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from src import config


# ─────────────────────────────────────────────────────────────
# Mots de passe (bcrypt)
# ─────────────────────────────────────────────────────────────
def verify_password(plain_password: str, password_hash: str) -> bool:
    """Vérifie qu'un mot de passe correspond à son hash bcrypt.

    :param plain_password: Le mot de passe en clair saisi par l'utilisateur.
    :param password_hash: Le hash bcrypt stocké (variable ``AUTH_PASSWORD_HASH``).
    :returns: ``True`` si le mot de passe est correct, ``False`` sinon.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


# ─────────────────────────────────────────────────────────────
# Création des tokens JWT
# ─────────────────────────────────────────────────────────────
def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    """Fabrique un JWT signé (fonction interne partagée).

    :param subject: L'identité encodée dans le token (ex. le nom d'utilisateur).
    :param token_type: ``"access"`` ou ``"refresh"``, pour distinguer les deux.
    :param expires_delta: Durée de validité avant expiration.
    :returns: Le token JWT encodé sous forme de chaîne.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        payload,
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )


def create_access_token(subject: str) -> str:
    """Crée un *access token* de courte durée.

    :param subject: L'identité de l'utilisateur (ex. son nom).
    :returns: Un access token JWT signé.
    """
    return _create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    """Crée un *refresh token* de longue durée.

    :param subject: L'identité de l'utilisateur (ex. son nom).
    :returns: Un refresh token JWT signé.
    """
    return _create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
    )


# ─────────────────────────────────────────────────────────────
# Décodage / validation des tokens JWT
# ─────────────────────────────────────────────────────────────
def decode_token(token: str, expected_type: str) -> dict:
    """Décode et valide un JWT, en vérifiant son type.

    :param token: Le token JWT à décoder.
    :param expected_type: Le type attendu (``"access"`` ou ``"refresh"``).
    :raises jwt.InvalidTokenError: Si le token est invalide, expiré,
        ou si son type ne correspond pas à ``expected_type``.
    :returns: Le *payload* décodé (dictionnaire des claims).
    """
    payload = jwt.decode(
        token,
        config.JWT_SECRET_KEY,
        algorithms=[config.JWT_ALGORITHM],
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"Type de token invalide : attendu '{expected_type}', "
            f"reçu '{payload.get('type')}'."
        )
    return payload

# ═══════════════════════════════════════════════════════════════
# VALIDATION DU TOKEN (Phase 7.2)
# ═══════════════════════════════════════════════════════════════

def verify_access_token(token: str) -> str:
    """Valide un access_token JWT et extrait le username.

    :param token: Le JWT à valider (sans le préfixe "Bearer ").
    :returns: Le username contenu dans le token (claim "sub").
    :raises ValueError: Si le token est invalide, expiré ou n'est pas un access_token.
    """
    try:
        # Utilise decode_token() qui fait déjà la validation
        payload = decode_token(token, expected_type="access")
        
        # Extrait le username (obligatoire)
        username: str | None = payload.get("sub")
        if not username:
            raise ValueError("Token ne contient pas de 'sub' (username)")
        
        return username
        
    except jwt.ExpiredSignatureError:
        raise ValueError("❌ Token expiré")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"❌ Token invalide : {e}")
    except Exception as e:
        raise ValueError(f"❌ Erreur lors de la validation du token : {e}")