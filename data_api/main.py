"""
data_api/main.py
================
Point d'entrée du micro-service d'accès aux données.

Lance un serveur FastAPI sur le port défini par ``DATA_API_PORT``
(ou 8001 par défaut). Ce service est destiné à rester **interne**
au cluster et ne doit pas être exposé directement sur Internet.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────
# Configuration du logging Loguru — en premier pour capter toute
# l'initialisation du module, avant l'import des routers (qui
# déclenche l'import de data_api/database.py et psycopg2).
# ─────────────────────────────────────────────────────────────────
from data_api.observability.logging_config import setup_logging

setup_logging()

from fastapi import FastAPI
from loguru import logger

from data_api.routers import films

app = FastAPI(
    title="HorRAGor Data API",
    description="Service interne d'encapsulation PostgreSQL / pgvector.",
    version="1.0.0",
)

logger.info("[data_api] Application FastAPI initialisée.")

# Enregistrement du router métiers
app.include_router(films.router, prefix="/films", tags=["films"])


@app.get("/health", tags=["Santé"])
def health_check():
    """
    Endpoint minimal pour le monitoring (liveness probe).
    """
    logger.debug("[health_check] Health check appelé")
    return {"status": "ok", "service": "data-api"}