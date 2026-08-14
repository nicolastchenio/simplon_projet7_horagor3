"""
tests/test_frontend.py
========================
Tests unitaires de l'UI Streamlit (``app_frontend.py``).

Stratégie de mock :
- Hors ``streamlit run``, ``st.*`` fonctionne en « bare mode » : les
  affichages (``st.markdown``, ``st.caption``, ``st.spinner``...) et
  ``st.session_state`` no-opent/persistent sans lever d'exception
  (vérifié empiriquement). Aucun besoin de ``streamlit.testing.v1.AppTest``.
- ``httpx.Client`` est mocké (mêmes fakes que ``test_rag_tool.py``, adaptés
  à ``.post()``) pour toutes les fonctions réseau (``login``,
  ``refresh_access_token``, ``call_chat_api``).
- Les fonctions d'interaction (``st.button``, ``st.text_input``,
  ``st.chat_input``, ``st.sidebar.button``, ``st.rerun``) sont mockées au
  cas par cas pour simuler une saisie/un clic utilisateur.
- ``st.session_state`` étant un singleton persistant en process, une
  fixture ``autouse`` le réinitialise avant/après chaque test.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

import app_frontend

# ═══════════════════════════════════════════════════════════════
# Fixtures & fakes communs
# ═══════════════════════════════════════════════════════════════

_SESSION_KEYS = ["access_token", "refresh_token", "user", "messages", "thread_id"]


@pytest.fixture(autouse=True)
def _reset_session_state():
    for key in _SESSION_KEYS:
        if key in app_frontend.st.session_state:
            del app_frontend.st.session_state[key]
    yield
    for key in _SESSION_KEYS:
        if key in app_frontend.st.session_state:
            del app_frontend.st.session_state[key]


class Recorder:
    """Remplace une fonction ``st.*`` et journalise ses appels."""

    def __init__(self, return_value: Any = None):
        self.calls: list[tuple] = []
        self.return_value = return_value

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value


def _make_fake_jwt(payload: dict) -> str:
    """Construit un JWT factice (signature non vérifiée par le code testé)."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.signature"


class FakeHttpxResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        json_exc: Exception | None = None,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self._json_exc = json_exc
        self.request = httpx.Request("POST", "http://intelligence-api.test")

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=self
            )


class FakeHttpxClient:
    def __init__(
        self,
        responses: list[FakeHttpxResponse] | None = None,
        raise_exc: Exception | None = None,
    ):
        self._responses = list(responses) if responses else []
        self._raise_exc = raise_exc
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, json: Any = None, headers: Any = None):
        self.calls.append((url, json, headers))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._responses.pop(0)


def _patch_httpx_client(monkeypatch, fake_client: FakeHttpxClient) -> None:
    monkeypatch.setattr(app_frontend.httpx, "Client", lambda **kwargs: fake_client)


# ═══════════════════════════════════════════════════════════════
# JWT : decode_jwt_payload / get_token_expiration /
# is_token_expired_soon / get_token_remaining_time
# ═══════════════════════════════════════════════════════════════

class TestDecodeJwtPayload:
    def test_token_valide_est_decode(self):
        token = _make_fake_jwt({"sub": "admin", "exp": 123456})

        assert app_frontend.decode_jwt_payload(token) == {"sub": "admin", "exp": 123456}

    def test_token_malforme_retourne_none(self):
        assert app_frontend.decode_jwt_payload("deux.parties") is None

    def test_payload_invalide_retourne_none(self):
        assert app_frontend.decode_jwt_payload("a.####.c") is None


class TestGetTokenExpiration:
    def test_avec_exp_retourne_datetime(self):
        exp_ts = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
        token = _make_fake_jwt({"exp": exp_ts})

        result = app_frontend.get_token_expiration(token)

        assert isinstance(result, datetime)
        assert abs(result.timestamp() - exp_ts) < 1

    def test_sans_exp_retourne_none(self):
        token = _make_fake_jwt({"sub": "admin"})

        assert app_frontend.get_token_expiration(token) is None

    def test_token_invalide_retourne_none(self):
        assert app_frontend.get_token_expiration("invalide") is None


class TestIsTokenExpiredSoon:
    def test_expiration_lointaine_retourne_false(self):
        token = _make_fake_jwt(
            {"exp": (datetime.utcnow() + timedelta(minutes=30)).timestamp()}
        )

        assert app_frontend.is_token_expired_soon(token, threshold_seconds=300) is False

    def test_expiration_proche_retourne_true(self):
        token = _make_fake_jwt(
            {"exp": (datetime.utcnow() + timedelta(seconds=60)).timestamp()}
        )

        assert app_frontend.is_token_expired_soon(token, threshold_seconds=300) is True

    def test_token_invalide_retourne_true(self):
        assert app_frontend.is_token_expired_soon("invalide") is True


class TestGetTokenRemainingTime:
    def test_minutes_et_secondes(self):
        token = _make_fake_jwt(
            {"exp": (datetime.utcnow() + timedelta(minutes=2, seconds=30)).timestamp()}
        )

        result = app_frontend.get_token_remaining_time(token)

        assert re.match(r"^⏱️ \d+m \d+s$", result)

    def test_secondes_seules(self):
        token = _make_fake_jwt(
            {"exp": (datetime.utcnow() + timedelta(seconds=45)).timestamp()}
        )

        result = app_frontend.get_token_remaining_time(token)

        assert re.match(r"^⏱️ \d+s$", result)

    def test_token_expire(self):
        token = _make_fake_jwt(
            {"exp": (datetime.utcnow() - timedelta(seconds=10)).timestamp()}
        )

        assert app_frontend.get_token_remaining_time(token) == "⏰ EXPIRÉ"

    def test_token_invalide(self):
        assert (
            app_frontend.get_token_remaining_time("invalide")
            == "❓ Impossible à déterminer"
        )


# ═══════════════════════════════════════════════════════════════
# init_session_state
# ═══════════════════════════════════════════════════════════════

class TestInitSessionState:
    def test_premier_appel_pose_les_defauts(self):
        app_frontend.init_session_state()

        assert app_frontend.st.session_state.access_token is None
        assert app_frontend.st.session_state.refresh_token is None
        assert app_frontend.st.session_state.user is None
        assert app_frontend.st.session_state.messages == []
        assert isinstance(app_frontend.st.session_state.thread_id, str)

    def test_deuxieme_appel_ne_ecrase_pas(self):
        app_frontend.init_session_state()
        app_frontend.st.session_state.user = "admin"
        thread_id_avant = app_frontend.st.session_state.thread_id

        app_frontend.init_session_state()

        assert app_frontend.st.session_state.user == "admin"
        assert app_frontend.st.session_state.thread_id == thread_id_avant


# ═══════════════════════════════════════════════════════════════
# login / refresh_access_token / logout
# ═══════════════════════════════════════════════════════════════

class TestLogin:
    def test_succes_stocke_les_tokens(self, monkeypatch):
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[
                    FakeHttpxResponse(
                        200,
                        json_data={
                            "access_token": "acc123",
                            "refresh_token": "ref456",
                        },
                    )
                ]
            ),
        )

        result = app_frontend.login("admin", "motdepasse")

        assert result is True
        assert app_frontend.st.session_state.access_token == "acc123"
        assert app_frontend.st.session_state.refresh_token == "ref456"
        assert app_frontend.st.session_state.user == "admin"

    def test_echec_http_avec_detail_json(self, monkeypatch):
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[
                    FakeHttpxResponse(401, json_data={"detail": "Mot de passe invalide"})
                ]
            ),
        )
        st_error = Recorder()
        monkeypatch.setattr(app_frontend.st, "error", st_error)

        result = app_frontend.login("admin", "mauvais_mdp")

        assert result is False
        assert "access_token" not in app_frontend.st.session_state
        assert "Mot de passe invalide" in st_error.calls[0][0][0]

    def test_echec_http_avec_corps_json_illisible(self, monkeypatch):
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[
                    FakeHttpxResponse(401, json_exc=ValueError("corps illisible"))
                ]
            ),
        )
        st_error = Recorder()
        monkeypatch.setattr(app_frontend.st, "error", st_error)

        result = app_frontend.login("admin", "mauvais_mdp")

        assert result is False
        assert "Identifiant ou mot de passe incorrect" in st_error.calls[0][0][0]

    def test_exception_generique_retourne_false(self, monkeypatch):
        _patch_httpx_client(
            monkeypatch, FakeHttpxClient(raise_exc=httpx.ConnectError("hors ligne"))
        )
        monkeypatch.setattr(app_frontend.st, "error", Recorder())

        assert app_frontend.login("admin", "motdepasse") is False


class TestRefreshAccessToken:
    def test_sans_refresh_token_retourne_false(self):
        app_frontend.st.session_state.refresh_token = None

        assert app_frontend.refresh_access_token() is False

    def test_succes_met_a_jour_les_tokens(self, monkeypatch):
        app_frontend.st.session_state.refresh_token = "ancien_refresh"
        app_frontend.st.session_state.user = "admin"
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[
                    FakeHttpxResponse(
                        200,
                        json_data={
                            "access_token": "nouveau_acc",
                            "refresh_token": "nouveau_refresh",
                        },
                    )
                ]
            ),
        )

        result = app_frontend.refresh_access_token()

        assert result is True
        assert app_frontend.st.session_state.access_token == "nouveau_acc"
        assert app_frontend.st.session_state.refresh_token == "nouveau_refresh"

    def test_succes_sans_nouveau_refresh_token(self, monkeypatch):
        app_frontend.st.session_state.refresh_token = "ancien_refresh"
        app_frontend.st.session_state.user = "admin"
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[FakeHttpxResponse(200, json_data={"access_token": "nouveau_acc"})]
            ),
        )

        app_frontend.refresh_access_token()

        assert app_frontend.st.session_state.refresh_token == "ancien_refresh"

    def test_echec_reseau_retourne_false(self, monkeypatch):
        app_frontend.st.session_state.refresh_token = "ancien_refresh"
        app_frontend.st.session_state.user = "admin"
        _patch_httpx_client(
            monkeypatch, FakeHttpxClient(raise_exc=httpx.ConnectError("hors ligne"))
        )

        assert app_frontend.refresh_access_token() is False


class TestLogout:
    def test_reinitialise_la_session(self):
        app_frontend.st.session_state.access_token = "acc"
        app_frontend.st.session_state.refresh_token = "ref"
        app_frontend.st.session_state.user = "admin"
        app_frontend.st.session_state.messages = [{"role": "user", "content": "hello"}]
        ancien_thread_id = "thread-1"
        app_frontend.st.session_state.thread_id = ancien_thread_id

        app_frontend.logout()

        assert app_frontend.st.session_state.access_token is None
        assert app_frontend.st.session_state.refresh_token is None
        assert app_frontend.st.session_state.user is None
        assert app_frontend.st.session_state.messages == []
        assert app_frontend.st.session_state.thread_id != ancien_thread_id


# ═══════════════════════════════════════════════════════════════
# call_chat_api
# ═══════════════════════════════════════════════════════════════

class TestCallChatApi:
    def test_refresh_proactif_reussi_puis_appel_normal(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok_bientot_expire"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: True)
        monkeypatch.setattr(app_frontend, "refresh_access_token", lambda: True)
        monkeypatch.setattr(app_frontend.st, "info", Recorder())
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(responses=[FakeHttpxResponse(200, json_data={"response": "ok"})]),
        )

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result == {"response": "ok"}

    def test_refresh_proactif_echoue_deconnecte(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok_bientot_expire"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: True)
        monkeypatch.setattr(app_frontend, "refresh_access_token", lambda: False)
        logout_recorder = Recorder()
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "logout", logout_recorder)
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)
        monkeypatch.setattr(app_frontend.st, "error", Recorder())

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result is None
        assert len(logout_recorder.calls) == 1
        assert len(rerun_recorder.calls) == 1

    def test_appel_direct_succes(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(responses=[FakeHttpxResponse(200, json_data={"response": "ok"})]),
        )

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result == {"response": "ok"}

    def test_401_puis_refresh_ok_puis_retry_succes(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        monkeypatch.setattr(app_frontend, "refresh_access_token", lambda: True)
        monkeypatch.setattr(app_frontend.st, "info", Recorder())
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[
                    FakeHttpxResponse(401),
                    FakeHttpxResponse(200, json_data={"response": "ok apres retry"}),
                ]
            ),
        )

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result == {"response": "ok apres retry"}

    def test_401_puis_refresh_ok_puis_retry_echoue(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        monkeypatch.setattr(app_frontend, "refresh_access_token", lambda: True)
        monkeypatch.setattr(app_frontend.st, "info", Recorder())
        logout_recorder = Recorder()
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "logout", logout_recorder)
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)
        monkeypatch.setattr(app_frontend.st, "error", Recorder())
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(responses=[FakeHttpxResponse(401), FakeHttpxResponse(500)]),
        )

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result is None
        assert len(logout_recorder.calls) == 1
        assert len(rerun_recorder.calls) == 1

    def test_401_puis_refresh_echoue(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        monkeypatch.setattr(app_frontend, "refresh_access_token", lambda: False)
        monkeypatch.setattr(app_frontend.st, "info", Recorder())
        logout_recorder = Recorder()
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "logout", logout_recorder)
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)
        monkeypatch.setattr(app_frontend.st, "error", Recorder())
        _patch_httpx_client(
            monkeypatch, FakeHttpxClient(responses=[FakeHttpxResponse(401)])
        )

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result is None
        assert len(logout_recorder.calls) == 1
        assert len(rerun_recorder.calls) == 1

    def test_autre_erreur_http_retourne_none(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        st_error = Recorder()
        monkeypatch.setattr(app_frontend.st, "error", st_error)
        _patch_httpx_client(
            monkeypatch,
            FakeHttpxClient(
                responses=[FakeHttpxResponse(500, json_data={"detail": "Erreur interne"})]
            ),
        )

        result = app_frontend.call_chat_api("Question ?", "thread-1")

        assert result is None
        assert "Erreur interne" in st_error.calls[0][0][0]

    def test_connect_error_retourne_none(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        monkeypatch.setattr(app_frontend.st, "error", Recorder())
        _patch_httpx_client(
            monkeypatch, FakeHttpxClient(raise_exc=httpx.ConnectError("hors ligne"))
        )

        assert app_frontend.call_chat_api("Question ?", "thread-1") is None

    def test_exception_generique_retourne_none(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        monkeypatch.setattr(app_frontend, "is_token_expired_soon", lambda *a, **kw: False)
        monkeypatch.setattr(app_frontend.st, "error", Recorder())
        _patch_httpx_client(monkeypatch, FakeHttpxClient(raise_exc=RuntimeError("boom")))

        assert app_frontend.call_chat_api("Question ?", "thread-1") is None


# ═══════════════════════════════════════════════════════════════
# _render_source
# ═══════════════════════════════════════════════════════════════

class TestRenderSource:
    def _patch_display(self, monkeypatch):
        markdown = Recorder()
        caption = Recorder()
        divider = Recorder()
        monkeypatch.setattr(app_frontend.st, "markdown", markdown)
        monkeypatch.setattr(app_frontend.st, "caption", caption)
        monkeypatch.setattr(app_frontend.st, "divider", divider)
        return markdown, caption, divider

    def test_source_complete(self, monkeypatch):
        markdown, caption, divider = self._patch_display(monkeypatch)
        source = {
            "type": "faiss_local",
            "title": "The Exorcist",
            "year": 1973,
            "score": 0.873,
            "preview": "Une famille est terrorisée.",
        }

        app_frontend._render_source(source, 1)

        assert "1. The Exorcist" in markdown.calls[0][0][0]
        assert any("Année : 1973" in c[0][0] and "Score : 0.873" in c[0][0] for c in caption.calls)
        assert any("Une famille est terrorisée." in c[0][0] for c in caption.calls)
        assert len(divider.calls) == 1

    def test_titre_absent_genere_un_titre_par_defaut(self, monkeypatch):
        markdown, _, _ = self._patch_display(monkeypatch)

        app_frontend._render_source({"type": "web"}, 2)

        assert "Source 2 (web)" in markdown.calls[0][0][0]

    def test_preview_longue_est_tronquee(self, monkeypatch):
        _, caption, _ = self._patch_display(monkeypatch)
        preview = "x" * 400

        app_frontend._render_source({"preview": preview}, 1)

        rendered = next(c[0][0] for c in caption.calls if c[0][0].startswith("> "))
        assert rendered.endswith("...")
        assert len(rendered) == len("> ") + 297 + 3

    def test_aucune_metadonnee_affiche_message_par_defaut(self, monkeypatch):
        _, caption, _ = self._patch_display(monkeypatch)

        app_frontend._render_source({}, 1)

        assert any("Aucun aperçu disponible" in c[0][0] for c in caption.calls)
        assert len(caption.calls) == 1


# ═══════════════════════════════════════════════════════════════
# display_chat_history
# ═══════════════════════════════════════════════════════════════

class FakeChatMessageCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestDisplayChatHistory:
    def _patch_common(self, monkeypatch):
        chat_message = Recorder(return_value=FakeChatMessageCM())
        markdown = Recorder()
        caption = Recorder()
        expander = Recorder(return_value=FakeChatMessageCM())
        render_source = Recorder()
        monkeypatch.setattr(app_frontend.st, "chat_message", chat_message)
        monkeypatch.setattr(app_frontend.st, "markdown", markdown)
        monkeypatch.setattr(app_frontend.st, "caption", caption)
        monkeypatch.setattr(app_frontend.st, "expander", expander)
        monkeypatch.setattr(app_frontend, "_render_source", render_source)
        return chat_message, markdown, caption, expander, render_source

    def test_historique_vide_ne_rend_rien(self, monkeypatch):
        chat_message, *_ = self._patch_common(monkeypatch)
        app_frontend.st.session_state.messages = []

        app_frontend.display_chat_history()

        assert chat_message.calls == []

    def test_message_assistant_avec_sources_dict(self, monkeypatch):
        chat_message, markdown, caption, expander, render_source = self._patch_common(
            monkeypatch
        )
        app_frontend.st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Bonjour",
                "metadata": {"enriched_from_web": True},
                "sources": [{"title": "A"}, {"title": "B"}],
            }
        ]

        app_frontend.display_chat_history()

        assert chat_message.calls[0][0][0] == "assistant"
        assert markdown.calls[0][0][0] == "Bonjour"
        assert any("Enrichi via le Web" in c[0][0] for c in caption.calls)
        assert len(render_source.calls) == 2

    def test_source_non_dict_utilise_le_repli_texte(self, monkeypatch):
        chat_message, markdown, caption, expander, render_source = self._patch_common(
            monkeypatch
        )
        app_frontend.st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Réponse",
                "sources": ["une source texte brute"],
            }
        ]

        app_frontend.display_chat_history()

        assert render_source.calls == []
        assert any("une source texte brute" in c[0][0] for c in markdown.calls)


# ═══════════════════════════════════════════════════════════════
# handle_user_input
# ═══════════════════════════════════════════════════════════════

class TestHandleUserInput:
    def test_aucune_saisie_ne_change_rien(self, monkeypatch):
        app_frontend.st.session_state.messages = []
        monkeypatch.setattr(app_frontend.st, "chat_input", lambda *a, **kw: None)

        app_frontend.handle_user_input()

        assert app_frontend.st.session_state.messages == []

    def test_question_avec_reponse_api_ajoute_les_messages(self, monkeypatch):
        app_frontend.st.session_state.messages = []
        app_frontend.st.session_state.thread_id = "thread-1"
        monkeypatch.setattr(
            app_frontend.st, "chat_input", lambda *a, **kw: "Parle-moi de Halloween"
        )
        monkeypatch.setattr(
            app_frontend,
            "call_chat_api",
            lambda question, thread_id: {
                "response": "Un tueur masqué...",
                "sources": [{"title": "Halloween"}],
                "metadata": {"enriched_from_web": True},
            },
        )

        app_frontend.handle_user_input()

        messages = app_frontend.st.session_state.messages
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "Parle-moi de Halloween"}
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Un tueur masqué..."
        assert messages[1]["sources"] == [{"title": "Halloween"}]
        assert messages[1]["metadata"] == {"enriched_from_web": True}

    def test_echec_api_ajoute_message_erreur(self, monkeypatch):
        app_frontend.st.session_state.messages = []
        app_frontend.st.session_state.thread_id = "thread-1"
        monkeypatch.setattr(app_frontend.st, "chat_input", lambda *a, **kw: "Question ?")
        monkeypatch.setattr(
            app_frontend, "call_chat_api", lambda question, thread_id: None
        )

        app_frontend.handle_user_input()

        messages = app_frontend.st.session_state.messages
        assert messages[1]["content"] == "Désolé, je n'ai pas pu contacter les archives."
        assert messages[1]["sources"] == []
        assert messages[1]["metadata"] == {}


# ═══════════════════════════════════════════════════════════════
# show_login_page
# ═══════════════════════════════════════════════════════════════

class TestShowLoginPage:
    def _patch_form(self, monkeypatch, text_values: dict, button_clicked: bool):
        monkeypatch.setattr(
            app_frontend.st,
            "text_input",
            lambda label, **kw: text_values.get(kw.get("key"), ""),
        )
        monkeypatch.setattr(app_frontend.st, "button", lambda *a, **kw: button_clicked)
        for name in ("title", "caption", "divider", "subheader", "success", "warning"):
            monkeypatch.setattr(app_frontend.st, name, Recorder())

    def test_bouton_non_clique_login_jamais_appele(self, monkeypatch):
        self._patch_form(
            monkeypatch, {"login_user": "admin", "login_pass": "x"}, button_clicked=False
        )
        login_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "login", login_recorder)

        app_frontend.show_login_page()

        assert login_recorder.calls == []

    def test_champs_vides_login_jamais_appele(self, monkeypatch):
        self._patch_form(monkeypatch, {"login_user": "", "login_pass": ""}, button_clicked=True)
        login_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "login", login_recorder)

        app_frontend.show_login_page()

        assert login_recorder.calls == []

    def test_login_reussi_declenche_rerun(self, monkeypatch):
        self._patch_form(
            monkeypatch, {"login_user": "admin", "login_pass": "x"}, button_clicked=True
        )
        monkeypatch.setattr(app_frontend, "login", lambda u, p: True)
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)

        app_frontend.show_login_page()

        assert len(rerun_recorder.calls) == 1

    def test_login_echoue_pas_de_rerun(self, monkeypatch):
        self._patch_form(
            monkeypatch, {"login_user": "admin", "login_pass": "mauvais"}, button_clicked=True
        )
        monkeypatch.setattr(app_frontend, "login", lambda u, p: False)
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)

        app_frontend.show_login_page()

        assert rerun_recorder.calls == []


# ═══════════════════════════════════════════════════════════════
# show_chat_page
# ═══════════════════════════════════════════════════════════════

class TestShowChatPage:
    def _patch_common(self, monkeypatch, sidebar_button_clicked: bool):
        monkeypatch.setattr(app_frontend, "display_chat_history", Recorder())
        monkeypatch.setattr(app_frontend, "handle_user_input", Recorder())
        monkeypatch.setattr(
            app_frontend, "get_token_remaining_time", lambda token: "⏱️ 10m 0s"
        )
        for name in ("title", "caption", "divider"):
            monkeypatch.setattr(app_frontend.st, name, Recorder())
        monkeypatch.setattr(app_frontend.st.sidebar, "header", Recorder())
        monkeypatch.setattr(app_frontend.st.sidebar, "markdown", Recorder())
        monkeypatch.setattr(app_frontend.st.sidebar, "divider", Recorder())
        monkeypatch.setattr(
            app_frontend.st.sidebar, "button", lambda *a, **kw: sidebar_button_clicked
        )
        app_frontend.st.session_state.access_token = "tok123"
        app_frontend.st.session_state.user = "admin"
        app_frontend.st.session_state.thread_id = "thread-1"
        app_frontend.st.session_state.messages = []

    def test_bouton_deconnexion_non_clique(self, monkeypatch):
        self._patch_common(monkeypatch, sidebar_button_clicked=False)
        logout_recorder = Recorder()
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "logout", logout_recorder)
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)

        app_frontend.show_chat_page()

        assert logout_recorder.calls == []
        assert rerun_recorder.calls == []

    def test_bouton_deconnexion_clique(self, monkeypatch):
        self._patch_common(monkeypatch, sidebar_button_clicked=True)
        logout_recorder = Recorder()
        rerun_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "logout", logout_recorder)
        monkeypatch.setattr(app_frontend.st, "rerun", rerun_recorder)

        app_frontend.show_chat_page()

        assert len(logout_recorder.calls) == 1
        assert len(rerun_recorder.calls) == 1


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

class TestMain:
    def test_sans_token_affiche_login(self, monkeypatch):
        app_frontend.st.session_state.access_token = None
        monkeypatch.setattr(app_frontend, "init_session_state", Recorder())
        login_recorder = Recorder()
        chat_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "show_login_page", login_recorder)
        monkeypatch.setattr(app_frontend, "show_chat_page", chat_recorder)

        app_frontend.main()

        assert len(login_recorder.calls) == 1
        assert chat_recorder.calls == []

    def test_avec_token_affiche_chat(self, monkeypatch):
        app_frontend.st.session_state.access_token = "tok123"
        app_frontend.st.session_state.user = "admin"
        app_frontend.st.session_state.thread_id = "thread-1"
        monkeypatch.setattr(app_frontend, "init_session_state", Recorder())
        login_recorder = Recorder()
        chat_recorder = Recorder()
        monkeypatch.setattr(app_frontend, "show_login_page", login_recorder)
        monkeypatch.setattr(app_frontend, "show_chat_page", chat_recorder)

        app_frontend.main()

        assert len(chat_recorder.calls) == 1
        assert login_recorder.calls == []
