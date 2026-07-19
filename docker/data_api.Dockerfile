# docker/data_api.Dockerfile
# ==========================
# Image du micro-service d'accès aux données (FastAPI + Supabase/pgvector).

FROM python:3.12-slim

# Empêche Python d'écrire des .pyc et assure que les logs sortent immédiatement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── 1. Installer uv (cohérent avec ton workflow local) ──
RUN pip install --no-cache-dir uv

# ── 2. Dépendances ──
# On copie SEULEMENT le pyproject.toml pour profiter du cache Docker.
# Si plus tard tu utilises uv.lock, copie-le aussi ici.
COPY pyproject.toml .
RUN uv pip install --system .

# ── 3. Code source minimal ──
# data_api/ : le microservice lui-même.
# src/      : on recrée la structure minimum pour que les imports fonctionnent.
#             Seul config.py est nécessaire ici, mais on copie aussi __init__.py
#             (même vide) pour que Python reconnaisse le package "src".
COPY data_api/ data_api/
RUN mkdir -p src
COPY src/__init__.py src/
COPY src/config.py src/

# ── 4. Port exposé ──
EXPOSE 8001

# ── 5. Démarrage ──
CMD ["uvicorn", "data_api.main:app", "--host", "0.0.0.0", "--port", "8001"]