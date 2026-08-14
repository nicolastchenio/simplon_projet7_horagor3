"""
data_api/database.py
====================
Gestionnaire de connexions PostgreSQL pour le data-api.

Ce module est le **seul** endroit du projet autorisé à appeler
``psycopg2.connect()``. Il récupère ``DATABASE_URL`` depuis la
configuration centralisée ``src.config`` afin d'éviter toute
duplication de variables d'environnement.

Journalisation (Phase 8.2) : la connexion retournée par
``get_db_connection()`` est enveloppée dans ``_LoggingConnection``, dont
``.cursor(...)`` produit un curseur ``_LoggingCursor`` qui journalise
automatiquement chaque ``execute()`` (opération SQL, durée, lignes
affectées). Cela trace toutes les requêtes émises par
``data_api/routers/*.py`` sans devoir modifier ces derniers.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg2
from loguru import logger

from src.config import DATABASE_URL

#: Mots-clés SQL reconnus comme opérations de données (Phase 8.2, item 15).
_KNOWN_OPERATIONS = ("SELECT", "INSERT", "UPDATE", "DELETE")


def _extract_operation(query: str) -> str:
    """
    Extrait le premier mot-clé d'une requête SQL (``SELECT``, ``INSERT``…).

    :param query: Requête SQL brute (éventuellement paramétrée).
    :returns: Le mot-clé en majuscules s'il est reconnu, sinon ``"AUTRE"``.
    """
    first_word = query.strip().split(None, 1)[0].upper() if query.strip() else ""
    return first_word if first_word in _KNOWN_OPERATIONS else "AUTRE"


class _LoggingCursor:
    """
    Enveloppe transparente d'un curseur psycopg2.

    Journalise chaque ``execute()`` (opération, durée, ``rowcount``) puis
    délègue tout le reste (``fetchall``, ``fetchone``, itération…) au
    curseur réel via ``__getattr__``, de sorte que le comportement soit
    identique du point de vue de l'appelant (``data_api/routers/*.py``).
    """

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(self, query: str, vars: Any = None) -> Any:
        """Exécute la requête et journalise opération/durée/rowcount."""
        operation = _extract_operation(query)
        start = time.perf_counter()
        try:
            result = self._cursor.execute(query, vars)
        except Exception as exc:
            logger.bind(operation=operation).error(
                f"[DB] {operation} échoué : {exc}"
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        logger.bind(
            operation=operation,
            duration_ms=round(duration_ms, 2),
            rowcount=self._cursor.rowcount,
        ).debug(
            f"[DB] {operation} exécuté en {duration_ms:.2f} ms "
            f"({self._cursor.rowcount} ligne(s))"
        )
        return result

    def __enter__(self) -> _LoggingCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._cursor.close()

    def __iter__(self) -> Any:
        return iter(self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _LoggingConnection:
    """
    Enveloppe transparente d'une connexion psycopg2.

    Seule ``.cursor(...)`` est interceptée (pour retourner un
    ``_LoggingCursor``) ; tout le reste (``commit``, ``close``,
    ``rollback``…) est délégué à la connexion réelle.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> _LoggingCursor:
        return _LoggingCursor(self._conn.cursor(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@contextmanager
def get_db_connection() -> Generator:
    """
    Ouvre une connexion PostgreSQL, la yield (enveloppée pour la
    journalisation), puis la ferme.

    Yields
    ------
    _LoggingConnection
        Connexion prête à l'emploi ; ``.cursor(...)`` journalise
        automatiquement chaque requête exécutée.
    """
    conn = None
    start = time.perf_counter()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.debug("[DB] Connexion PostgreSQL ouverte")
        yield _LoggingConnection(conn)
    except psycopg2.OperationalError as exc:
        logger.error(f"[DB] Impossible de se connecter à la base : {exc}")
        raise
    finally:
        if conn is not None:
            conn.close()
            duration_ms = (time.perf_counter() - start) * 1000
            logger.debug(f"[DB] Connexion PostgreSQL fermée ({duration_ms:.2f} ms)")