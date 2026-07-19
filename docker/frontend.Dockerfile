# docker/frontend.Dockerfile
# ==========================
# Image du frontend Streamlit (UI HorRAGor).

FROM python:3.12-slim

# Empêche Python d'écrire des .pyc et assure que les logs sortent immédiatement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# ── Dépendances runtime frontend ──
# httpx     : client HTTP utilisé par app_frontend.py
# streamlit : framework UI
# python-dotenv : utilisé par src/config.py (from dotenv import load_dotenv)
RUN pip install --no-cache-dir streamlit httpx python-dotenv

# ── Config Streamlit (thème Horror) ──
COPY .streamlit/ .streamlit/

# ── Application ──
COPY app_frontend.py .
COPY src/ src/

# Port par défaut de Streamlit
EXPOSE 8501

# Healthcheck natif Streamlit
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# Lancement forcé sur 0.0.0.0 pour être accessible depuis l'extérieur du conteneur
ENTRYPOINT ["streamlit", "run", "app_frontend.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0"]