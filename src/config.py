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

# ═══════════════════════════════════════════════════════════════
# Service interne data-api (Phase 6)
# ═══════════════════════════════════════════════════════════════
# URL complète vers le micro-service d'accès aux données.
# En dev c'est localhost:8001, en Docker ce sera http://data-api:8001
# sur le réseau interne.
# ═══════════════════════════════════════════════════════════════
DATA_API_URL: str = os.getenv("DATA_API_URL", "http://localhost:8001")

# ═══════════════════════════════════════════════════════════════
# Authentification JWT (Phase 7.2)
# ═══════════════════════════════════════════════════════════════
# Système d'authentification par Refresh Tokens verrouillant les
# échanges entre l'IHM Streamlit et l'API Intelligence, tel qu'exigé
# par le cahier des charges (Épilogue MLOps, Couche Intelligence).
#
# Pour un projet de formation, un utilisateur UNIQUE est défini via
# ces variables d'environnement (pas de gestion multi-utilisateurs).
# ═══════════════════════════════════════════════════════════════

# Clé secrète servant à SIGNER les JWT (HMAC-SHA256).
# Doit rester strictement confidentielle : quiconque la connaît peut
# forger des tokens valides.
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_EN_PRODUCTION")

# Algorithme de signature symétrique (le standard pour un secret unique).
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

# Durée de vie de l'access_token en MINUTES (court : sécurité renforcée).
# Si volé, il n'est exploitable que quelques minutes.
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
)

# Durée de vie du refresh_token en JOURS (long : confort utilisateur).
# Il permet de régénérer des access_token sans se reconnecter.
REFRESH_TOKEN_EXPIRE_DAYS: int = int(
    os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
)

# Identifiant de l'unique utilisateur autorisé
AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "admin")

# Hash bcrypt du mot de passe (JAMAIS le mot de passe en clair).
# La vérification se fait via bcrypt.checkpw().
AUTH_PASSWORD_HASH: str = os.getenv("AUTH_PASSWORD_HASH", "")

# ⚠️ VALIDATION : Vérifier que les secrets critiques sont configurés
if not JWT_SECRET_KEY or JWT_SECRET_KEY == "CHANGE_ME_EN_PRODUCTION":
    raise ValueError(
        "❌ JWT_SECRET_KEY non définie ou par défaut ! "
        "Ajoute une valeur dans .env"
    )

if not AUTH_PASSWORD_HASH:
    raise ValueError(
        "❌ AUTH_PASSWORD_HASH non définie ! "
        "Ajoute une valeur dans .env"
    )