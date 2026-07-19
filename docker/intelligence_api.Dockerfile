# docker/intelligence_api.Dockerfile
# ==================================
# Image du micro-service Intelligence (FastAPI + LangGraph + FAISS + Ollama client).

FROM python:3.12-slim

# Empêche les .pyc et flush les logs immédiatement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── 1. Dépendances système (libgomp1 est requis par faiss-cpu) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Installer uv ──
RUN pip install --no-cache-dir uv

# ── 3. Dépendances Python ──
COPY pyproject.toml .
# Si tu as un uv.lock, décommente la ligne suivante :
# COPY uv.lock .
RUN uv pip install --system .

# ── 4. Code source ──
# On copie tout le package src/ (config, models, tools, nodes, etc.)
COPY src/ src/

# ── 5. Données statiques : index FAISS ──
# L'index est indispensable au RAG local. Il doit avoir été généré
# avant le build (ex: python -m src.scripts.build_faiss_index).
COPY data/ data/

# ── 6. Variables d'environnement par défaut pour Docker ──
# - DATA_API_URL : nom du service data-api sur le réseau interne Docker
# - OLLAMA_BASE_URL : permet d'atteindre Ollama sur l'hôte Windows/Mac
#   ou un service "ollama" si tu le dockerises plus tard.
ENV DATA_API_URL=http://data-api:8001 \
    OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    HORRAGOR_DATA_DIR=/app/data \
    FAISS_INDEX_DIR=/app/data/faiss_index

# ── 7. Port exposé ──
EXPOSE 8000

# ── 8. Démarrage ──
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]