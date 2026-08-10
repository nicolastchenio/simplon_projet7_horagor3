"""Routeur FastAPI : endpoints d'authentification (Phase 7.2).

Ce module expose deux routes :
  - POST /auth/login   : échange username + password → access_token + refresh_token
  - POST /auth/refresh : échange refresh_token → nouveau access_token

C'est le seul point d'entrée pour obtenir des tokens valides.

Traçabilité
-----------
Toutes les tentatives d'authentification (réussies et échouées) sur
``/auth/login`` et ``/auth/refresh`` sont journalisées à des fins de
sécurité (détection de brute-force, audit d'accès). Les logs ne
contiennent **jamais** de secrets en clair : ni mot de passe, ni
access_token, ni refresh_token complet. Seuls le username, la durée
de traitement et la raison d'échec sont tracés.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from src import config
from src.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)

# ═══════════════════════════════════════════════════════════════
# Routeur
# ═══════════════════════════════════════════════════════════════
router = APIRouter(prefix="/auth", tags=["auth"])

# ═══════════════════════════════════════════════════════════════
# Schémas Pydantic (req/resp)
# ═══════════════════════════════════════════════════════════════
class LoginRequest(BaseModel):
    """Corps de requête pour POST /auth/login."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Réponse contenant les tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Corps de requête pour POST /auth/refresh."""

    refresh_token: str


# ═══════════════════════════════════════════════════════════════
# POST /auth/login
# ═══════════════════════════════════════════════════════════════
@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(req: LoginRequest) -> TokenResponse:
    """Authentifie l'utilisateur et retourne les tokens.

    **Flux** :
      1. Vérifie que le username correspond à ``AUTH_USERNAME``
      2. Vérifie que le password correspond au hash ``AUTH_PASSWORD_HASH``
      3. Crée un *access_token* (15 min) et un *refresh_token* (7 jours)
      4. Retourne les deux

    **Erreurs** :
      - 401 : username ou password incorrect
      - 500 : hash du mot de passe non configuré (``AUTH_PASSWORD_HASH`` vide)

    :param req: ``LoginRequest`` contenant ``username`` et ``password``.
    :returns: ``TokenResponse`` avec les deux tokens signés.
    """
    start = time.perf_counter()
    logger.info(f"[Auth] Tentative de login : username='{req.username}'")

    # Vérifie l'identité
    if req.username != config.AUTH_USERNAME:
        logger.warning(
            f"[Auth] Échec login — username inconnu : '{req.username}'"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect.",
        )

    # Vérifie le mot de passe
    if not config.AUTH_PASSWORD_HASH:
        logger.error(
            "[Auth] Configuration serveur invalide — AUTH_PASSWORD_HASH "
            "non défini. Impossible de vérifier le mot de passe."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_PASSWORD_HASH non configuré. Vérifiez le .env",
        )

    if not verify_password(req.password, config.AUTH_PASSWORD_HASH):
        logger.warning(
            f"[Auth] Échec login — mot de passe incorrect pour '{req.username}'"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect.",
        )

    # Crée les tokens
    access_token = create_access_token(subject=req.username)
    refresh_token = create_refresh_token(subject=req.username)

    elapsed = (time.perf_counter() - start) * 1000
    logger.success(
        f"[Auth] Login réussi pour '{req.username}' — tokens émis, "
        f"durée={elapsed:.2f}ms"
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


# ═══════════════════════════════════════════════════════════════
# POST /auth/refresh
# ═══════════════════════════════════════════════════════════════
@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh(req: RefreshRequest) -> TokenResponse:
    """Rafraîchit l'access token à partir du refresh token.

    **Flux** :
      1. Décode et valide le refresh_token (type="refresh", non expiré)
      2. Extrait l'identité (claim "sub")
      3. Crée un nouvel access_token avec la même identité
      4. Retourne le nouvel access_token + le refresh_token inchangé

    **Erreurs** :
      - 401 : refresh_token invalide, expiré, ou mauvais type

    :param req: ``RefreshRequest`` contenant le ``refresh_token``.
    :returns: ``TokenResponse`` avec un nouvel access_token et le même refresh_token.
    """
    start = time.perf_counter()
    token_preview = (req.refresh_token or "")[:10] + "..."
    logger.info("[Auth] Tentative de refresh token")
    logger.debug(f"[Auth] Refresh token (tronqué) : '{token_preview}'")

    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except Exception as exc:
        logger.warning(
            f"[Auth] Échec refresh — token invalide ou expiré : {exc}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Refresh token invalide ou expiré : {exc}",
        ) from exc

    # Récupère l'identité du payload
    username = payload.get("sub")

    # Crée un nouvel access_token avec la même identité
    new_access_token = create_access_token(subject=username)

    elapsed = (time.perf_counter() - start) * 1000
    logger.success(
        f"[Auth] Refresh réussi pour '{username}' — nouvel access_token émis, "
        f"durée={elapsed:.2f}ms"
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=req.refresh_token,  # Inchangé
    )