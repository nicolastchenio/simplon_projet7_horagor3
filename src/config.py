"""
src/config.py
=============
Configuration centralisée du projet HorRAGor.

Ce module constit la **source unique de vérité** pour l'ensemble de
l'application. Il charge les variables d'environnement depuis le
fichier ``.env`` situé à la racine du projet et expose des constantes
typées utilisées par le backend, les outils et le frontend.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════
# Chargement du .env (racine du projet)
# ═══════════════════════════════════════════════════════════════
# __file__ = src/config.py  →  remonte d'un niveau = racine
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=True)

# ═══════════════════════════════════════════════════════════════
# Chemins
# ═══════════════════════════════════════════════════════════════
PROJECT_ROOT: Path = _PROJECT_ROOT
DATA_DIR: Path = Path(os.getenv("HORRAGOR_DATA_DIR", PROJECT_ROOT / "data"))
FAISS_INDEX_DIR: Path = Path(
    os.getenv("FAISS_INDEX_DIR", DATA_DIR / "faiss_index")
)

# ═══════════════════════════════════════════════════════════════
# LLM local (Ollama)
# ═══════════════════════════════════════════════════════════════
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
OLLAMA_EMBEDDING_MODEL: str = os.getenv(
    "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
)

# ═══════════════════════════════════════════════════════════════
# Base de données PostgreSQL / Supabase
# ═══════════════════════════════════════════════════════════════
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://horragor:horragor@localhost:5432/horragor",
)

# ═══════════════════════════════════════════════════════════════
# Serveur FastAPI (Phase 4)
# ═══════════════════════════════════════════════════════════════
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
API_TIMEOUT: int = int(os.getenv("API_TIMEOUT", "30"))

# URL complète exposée au frontend (générée automatiquement par défaut)
API_BASE_URL: str = os.getenv("API_BASE_URL", f"http://localhost:{API_PORT}")

# ═══════════════════════════════════════════════════════════════
# Outils externes (Scraper, etc.)
# ═══════════════════════════════════════════════════════════════
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
WIKIPEDIA_LANG: str = os.getenv("WIKIPEDIA_LANG", "fr")

# ═══════════════════════════════════════════════════════════════
# Hyper-paramètres métier (Router & RAG)
# ═══════════════════════════════════════════════════════════════
FAISS_TOP_K: int = int(os.getenv("FAISS_TOP_K", "5"))
FAISS_COSINE_THRESHOLD: float = float(
    os.getenv("FAISS_COSINE_THRESHOLD", "0.55")
)

# ═══════════════════════════════════════════════════════════════
# Hyper-paramètres des scripts de maintenance (batchs)
# ═══════════════════════════════════════════════════════════════
BATCH_SIZE_PGVECTOR: int = int(os.getenv("BATCH_SIZE_PGVECTOR", "500"))