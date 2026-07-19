"""
data_api/database.py
====================
Gestionnaire de connexions PostgreSQL pour le data-api.

Ce module est le **seul** endroit du projet autorisé à appeler
``psycopg2.connect()``. Il récupère ``DATABASE_URL`` depuis la
configuration centralisée ``src.config`` afin d'éviter toute
duplication de variables d'environnement.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg2
from loguru import logger

from src.config import DATABASE_URL


@contextmanager
def get_db_connection() -> Generator:
    """
    Ouvre une connexion PostgreSQL, la yield, puis la ferme.

    Yields
    ------
    psycopg2.extensions.connection
        Connexion prête à l'emploi. L'appelant doit ouvrir un curseur.
    """
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
    except psycopg2.OperationalError as exc:
        logger.error(f"Impossible de se connecter à la base : {exc}")
        raise
    finally:
        if conn is not None:
            conn.close()