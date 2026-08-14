"""
tests/test_data_api_database.py
=================================
Tests unitaires du wrapper de journalisation PostgreSQL
(``data_api/database.py``), jamais exercé par ``test_data_api_films.py``
puisque ce dernier remplace ``get_db_connection`` entièrement par des
fakes qui court-circuitent ``_LoggingCursor``/``_LoggingConnection``.

Ici on enveloppe de faux curseur/connexion *psycopg2* (``FakeRawCursor``/
``FakeRawConnection``) avec le vrai code du module, et on mocke
uniquement ``psycopg2.connect`` pour ``get_db_connection``.
"""
from __future__ import annotations

from typing import Any

import psycopg2
import pytest

from data_api import database

# ═══════════════════════════════════════════════════════════════
# Fakes communs (simulent l'API psycopg2 réelle, pas le wrapper)
# ═══════════════════════════════════════════════════════════════

class FakeRawCursor:
    def __init__(self, rowcount: int = 1, raise_exc: Exception | None = None):
        self.rowcount = rowcount
        self.closed = False
        self._raise_exc = raise_exc
        self.executed: list[tuple] = []

    def execute(self, query: str, vars: Any = None) -> None:
        self.executed.append((query, vars))
        if self._raise_exc is not None:
            raise self._raise_exc

    def close(self) -> None:
        self.closed = True

    def __iter__(self):
        return iter([("row1",), ("row2",)])

    def fetchall(self):
        return [("row1",), ("row2",)]


class FakeRawConnection:
    def __init__(self):
        self.closed = False
        self.committed = False
        self.cursor_calls: list[tuple] = []
        self._cursor_to_return: FakeRawCursor | None = None

    def cursor(self, *args, **kwargs) -> FakeRawCursor:
        self.cursor_calls.append((args, kwargs))
        self._cursor_to_return = self._cursor_to_return or FakeRawCursor()
        return self._cursor_to_return

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.committed = True


# ═══════════════════════════════════════════════════════════════
# _extract_operation
# ═══════════════════════════════════════════════════════════════

class TestExtractOperation:
    @pytest.mark.parametrize(
        "query, attendu",
        [
            ("SELECT * FROM film", "SELECT"),
            ("insert into film values (1)", "INSERT"),
            ("Update film set titre = 'x'", "UPDATE"),
            ("delete from film where id_film = 1", "DELETE"),
        ],
    )
    def test_operations_connues_normalisees_en_majuscules(self, query, attendu):
        assert database._extract_operation(query) == attendu

    def test_operation_inconnue_retourne_autre(self):
        assert database._extract_operation("DROP TABLE film") == "AUTRE"

    def test_chaine_vide_retourne_autre(self):
        assert database._extract_operation("   ") == "AUTRE"


# ═══════════════════════════════════════════════════════════════
# _LoggingCursor
# ═══════════════════════════════════════════════════════════════

class TestLoggingCursor:
    def test_execute_succes_delegue_au_curseur_reel(self):
        raw = FakeRawCursor(rowcount=3)
        cursor = database._LoggingCursor(raw)

        cursor.execute("SELECT * FROM film", ("x",))

        assert raw.executed == [("SELECT * FROM film", ("x",))]

    def test_execute_echec_est_propage(self):
        raw = FakeRawCursor(raise_exc=RuntimeError("connexion perdue"))
        cursor = database._LoggingCursor(raw)

        with pytest.raises(RuntimeError, match="connexion perdue"):
            cursor.execute("SELECT * FROM film")

    def test_context_manager_ferme_le_curseur_reel(self):
        raw = FakeRawCursor()
        with database._LoggingCursor(raw) as cursor:
            assert cursor is not None

        assert raw.closed is True

    def test_iteration_delegue_au_curseur_reel(self):
        raw = FakeRawCursor()
        cursor = database._LoggingCursor(raw)

        assert list(cursor) == [("row1",), ("row2",)]

    def test_getattr_delegue_un_attribut_non_intercepte(self):
        raw = FakeRawCursor()
        cursor = database._LoggingCursor(raw)

        assert cursor.fetchall() == [("row1",), ("row2",)]


# ═══════════════════════════════════════════════════════════════
# _LoggingConnection
# ═══════════════════════════════════════════════════════════════

class TestLoggingConnection:
    def test_cursor_retourne_un_logging_cursor(self):
        raw_conn = FakeRawConnection()
        conn = database._LoggingConnection(raw_conn)

        cursor = conn.cursor()

        assert isinstance(cursor, database._LoggingCursor)
        assert len(raw_conn.cursor_calls) == 1

    def test_getattr_delegue_a_la_connexion_reelle(self):
        raw_conn = FakeRawConnection()
        conn = database._LoggingConnection(raw_conn)

        conn.commit()
        conn.close()

        assert raw_conn.committed is True
        assert raw_conn.closed is True


# ═══════════════════════════════════════════════════════════════
# get_db_connection
# ═══════════════════════════════════════════════════════════════

class TestGetDbConnection:
    def test_succes_yield_une_logging_connection_et_ferme_a_la_sortie(self, monkeypatch):
        raw_conn = FakeRawConnection()
        monkeypatch.setattr(database.psycopg2, "connect", lambda url: raw_conn)

        with database.get_db_connection() as conn:
            assert isinstance(conn, database._LoggingConnection)
            assert raw_conn.closed is False

        assert raw_conn.closed is True

    def test_echec_connexion_est_propage(self, monkeypatch):
        def fake_connect(url):
            raise psycopg2.OperationalError("base injoignable")

        monkeypatch.setattr(database.psycopg2, "connect", fake_connect)

        with pytest.raises(psycopg2.OperationalError):
            with database.get_db_connection():
                pass

    def test_erreur_pendant_utilisation_est_propagee_et_connexion_fermee(
        self, monkeypatch
    ):
        raw_conn = FakeRawConnection()
        monkeypatch.setattr(database.psycopg2, "connect", lambda url: raw_conn)

        with pytest.raises(psycopg2.OperationalError):
            with database.get_db_connection():
                raise psycopg2.OperationalError("connexion perdue en cours d'usage")

        assert raw_conn.closed is True
