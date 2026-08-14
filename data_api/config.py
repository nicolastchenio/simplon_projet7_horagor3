"""
data_api/config.py
===================
Configuration centralisée du micro-service data-api.

Ce module est volontairement indépendant de ``src/config.py`` : l'image
Docker de data_api (voir ``docker/data_api.Dockerfile``) ne copie que
``data_api/`` (+ ``src/config.py`` pour ``DATABASE_URL``, cf.
``data_api/database.py``), jamais ``src/observability/``. La configuration
de journalisation doit donc être portée par ce fichier, pas partagée.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════
# Chargement du .env (racine du projet)
# ═══════════════════════════════════════════════════════════════
# __file__ = data_api/config.py  →  remonte d'un niveau = racine
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=True)

PROJECT_ROOT: Path = _PROJECT_ROOT

# ═══════════════════════════════════════════════════════════════
# Loguru — Journalisation structurée (Phase 8.2)
# ═══════════════════════════════════════════════════════════════
# Mêmes variables d'environnement que src/config.py (même fichier .env
# partagé), afin que les logs des deux services soient configurés de
# façon cohérente.
# ═══════════════════════════════════════════════════════════════

# Niveau de log : DEBUG (dev local), INFO (prod)
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")

# Répertoire de persistance des fichiers logs (partagé avec src/)
LOG_DIR: Path = Path(os.getenv("LOG_DIR", PROJECT_ROOT / "logs"))

# Format des logs : JSON (structuré) ou texte (lisible)
LOG_JSON: bool = os.getenv("LOG_JSON", "true").lower() in ("true", "1", "yes")

# Rotation des fichiers logs : taille max avant création d'un nouveau
LOG_FILE_MAX_BYTES: int = int(os.getenv("LOG_FILE_MAX_BYTES", "52428800"))  # 50 MB

# Nombre max de fichiers logs à conserver avant suppression des anciens
LOG_FILE_BACKUP_COUNT: int = int(os.getenv("LOG_FILE_BACKUP_COUNT", "5"))

# Créer le répertoire logs s'il n'existe pas
LOG_DIR.mkdir(parents=True, exist_ok=True)
