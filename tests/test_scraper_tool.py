"""
tests/test_scraper_tool.py
============================
Tests unitaires de l'outil d'enrichissement web (``src/tools/scraper_tool.py``).

Stratégie de mock :
- ``_fetch_page_sections`` / ``_fetch_section_html`` : ``requests.get`` est
  remplacé par un faux appel rejouant une réponse construite à la main
  (``FakeRequestsResponse``) — aucune vraie requête vers Wikipédia n'est émise.
- ``_clean_wiki_html`` : testée directement avec du HTML en dur, sans mock.
- ``extract_wikipedia_synopsis`` : les 3 fonctions internes ci-dessus sont
  mockées pour isoler la logique d'orchestration (choix de la section,
  gestion des échecs par étape) du détail HTTP/parsing.
- ``enrich_from_web`` : mocke ``extract_wikipedia_synopsis``.
"""
from __future__ import annotations

from typing import Any

import requests

from src.tools import scraper_tool

# ═══════════════════════════════════════════════════════════════
# Fakes communs
# ═══════════════════════════════════════════════════════════════

class FakeRequestsResponse:
    """Réponse ``requests`` factice."""

    def __init__(
        self,
        json_data: Any = None,
        content: bytes = b"x",
        raise_for_status_exc: Exception | None = None,
        json_exc: Exception | None = None,
    ):
        self._json_data = json_data
        self.content = content
        self.status_code = 200
        self._raise_for_status_exc = raise_for_status_exc
        self._json_exc = json_exc

    def raise_for_status(self):
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


def _patch_requests_get(
    monkeypatch,
    response: FakeRequestsResponse | None = None,
    raise_exc: Exception | None = None,
) -> list[tuple]:
    """Remplace ``requests.get`` et journalise les appels reçus."""
    calls: list[tuple] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        if raise_exc is not None:
            raise raise_exc
        return response

    monkeypatch.setattr(scraper_tool.requests, "get", fake_get)
    return calls


# ═══════════════════════════════════════════════════════════════
# _fetch_page_sections
# ═══════════════════════════════════════════════════════════════

class TestFetchPageSections:
    def test_titre_vide_aucun_appel_reseau(self, monkeypatch):
        calls = _patch_requests_get(monkeypatch, response=FakeRequestsResponse())

        result = scraper_tool._fetch_page_sections("   ")

        assert result == []
        assert calls == []

    def test_succes_retourne_les_sections(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                json_data={
                    "parse": {
                        "title": "Conjuring",
                        "sections": [{"index": "2", "line": "Synopsis"}],
                    }
                }
            ),
        )

        result = scraper_tool._fetch_page_sections("Conjuring")

        assert result == [{"index": "2", "line": "Synopsis"}]

    def test_timeout_retourne_liste_vide(self, monkeypatch):
        _patch_requests_get(monkeypatch, raise_exc=requests.Timeout("timeout"))

        assert scraper_tool._fetch_page_sections("Conjuring") == []

    def test_http_error_retourne_liste_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                raise_for_status_exc=requests.HTTPError("500")
            ),
        )

        assert scraper_tool._fetch_page_sections("Conjuring") == []

    def test_request_exception_retourne_liste_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch, raise_exc=requests.ConnectionError("network fail")
        )

        assert scraper_tool._fetch_page_sections("Conjuring") == []

    def test_json_invalide_retourne_liste_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(json_exc=ValueError("bad json")),
        )

        assert scraper_tool._fetch_page_sections("Conjuring") == []

    def test_erreur_mediawiki_retourne_liste_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                json_data={"error": {"code": "missingtitle", "info": "Page absente"}}
            ),
        )

        assert scraper_tool._fetch_page_sections("Film Inexistant") == []

    def test_sections_vides_sans_erreur_retourne_liste_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                json_data={"parse": {"title": "Conjuring", "sections": []}}
            ),
        )

        assert scraper_tool._fetch_page_sections("Conjuring") == []


# ═══════════════════════════════════════════════════════════════
# _fetch_section_html
# ═══════════════════════════════════════════════════════════════

class TestFetchSectionHtml:
    def test_succes_retourne_le_fragment_html(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                json_data={"parse": {"text": {"*": "<p>Un texte.</p>"}}}
            ),
        )

        result = scraper_tool._fetch_section_html("Conjuring", "2")

        assert result == "<p>Un texte.</p>"

    def test_timeout_retourne_chaine_vide(self, monkeypatch):
        _patch_requests_get(monkeypatch, raise_exc=requests.Timeout("timeout"))

        assert scraper_tool._fetch_section_html("Conjuring", "2") == ""

    def test_http_error_retourne_chaine_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                raise_for_status_exc=requests.HTTPError("500")
            ),
        )

        assert scraper_tool._fetch_section_html("Conjuring", "2") == ""

    def test_request_exception_retourne_chaine_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch, raise_exc=requests.ConnectionError("network fail")
        )

        assert scraper_tool._fetch_section_html("Conjuring", "2") == ""

    def test_json_invalide_retourne_chaine_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(json_exc=ValueError("bad json")),
        )

        assert scraper_tool._fetch_section_html("Conjuring", "2") == ""

    def test_erreur_mediawiki_retourne_chaine_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(
                json_data={"error": {"code": "missingtitle", "info": "Page absente"}}
            ),
        )

        assert scraper_tool._fetch_section_html("Film Inexistant", "2") == ""

    def test_fragment_absent_retourne_chaine_vide(self, monkeypatch):
        _patch_requests_get(
            monkeypatch,
            response=FakeRequestsResponse(json_data={"parse": {"text": {}}}),
        )

        assert scraper_tool._fetch_section_html("Conjuring", "2") == ""


# ═══════════════════════════════════════════════════════════════
# _clean_wiki_html
# ═══════════════════════════════════════════════════════════════

class TestCleanWikiHtml:
    def test_fragment_vide_retourne_chaine_vide(self):
        assert scraper_tool._clean_wiki_html("") == ""

    def test_nettoyage_normal(self):
        html = (
            "<p>Un homme découvre une maison hantée<sup>[1]</sup> .</p>"
            "<p></p>"
            "<p>Il fuit avec sa famille.</p>"
        )

        result = scraper_tool._clean_wiki_html(html)

        assert "[1]" not in result
        assert "découvre une maison hantée." in result
        assert "Il fuit avec sa famille." in result
        # Le <p> vide ne doit pas générer de paragraphe fantôme.
        assert result.count("\n\n") == 1

    def test_aucun_paragraphe_retourne_chaine_vide(self):
        assert scraper_tool._clean_wiki_html("<div>Pas de balise p</div>") == ""


# ═══════════════════════════════════════════════════════════════
# extract_wikipedia_synopsis
# ═══════════════════════════════════════════════════════════════

class TestExtractWikipediaSynopsis:
    def test_titre_vide_retourne_chaine_vide(self):
        assert scraper_tool.extract_wikipedia_synopsis("   ") == ""

    def test_echec_etape1_aucune_section(self, monkeypatch):
        monkeypatch.setattr(scraper_tool, "_fetch_page_sections", lambda title: [])

        assert scraper_tool.extract_wikipedia_synopsis("Film Inconnu") == ""

    def test_echec_etape2_aucune_section_pertinente(self, monkeypatch):
        monkeypatch.setattr(
            scraper_tool,
            "_fetch_page_sections",
            lambda title: [{"index": "1", "line": "Distribution", "anchor": "Distribution"}],
        )

        assert scraper_tool.extract_wikipedia_synopsis("Conjuring") == ""

    def test_echec_etape3_html_vide(self, monkeypatch):
        monkeypatch.setattr(
            scraper_tool,
            "_fetch_page_sections",
            lambda title: [{"index": "2", "line": "Synopsis", "anchor": "Synopsis"}],
        )
        monkeypatch.setattr(
            scraper_tool, "_fetch_section_html", lambda title, index: ""
        )

        assert scraper_tool.extract_wikipedia_synopsis("Conjuring") == ""

    def test_echec_etape4_nettoyage_vide(self, monkeypatch):
        monkeypatch.setattr(
            scraper_tool,
            "_fetch_page_sections",
            lambda title: [{"index": "2", "line": "Résumé", "anchor": "Résumé"}],
        )
        monkeypatch.setattr(
            scraper_tool, "_fetch_section_html", lambda title, index: "<div></div>"
        )
        monkeypatch.setattr(scraper_tool, "_clean_wiki_html", lambda html: "")

        assert scraper_tool.extract_wikipedia_synopsis("Conjuring") == ""

    def test_succes_retourne_le_synopsis(self, monkeypatch):
        monkeypatch.setattr(
            scraper_tool,
            "_fetch_page_sections",
            lambda title: [{"index": "2", "line": "Intrigue", "anchor": "Intrigue"}],
        )
        monkeypatch.setattr(
            scraper_tool,
            "_fetch_section_html",
            lambda title, index: "<p>Une maison hantée.</p>",
        )
        monkeypatch.setattr(
            scraper_tool, "_clean_wiki_html", lambda html: "Une maison hantée."
        )

        result = scraper_tool.extract_wikipedia_synopsis("Conjuring")

        assert result == "Une maison hantée."


# ═══════════════════════════════════════════════════════════════
# enrich_from_web
# ═══════════════════════════════════════════════════════════════

class TestEnrichFromWeb:
    def test_aucun_synopsis_retourne_chaine_vide(self, monkeypatch):
        monkeypatch.setattr(
            scraper_tool, "extract_wikipedia_synopsis", lambda title: ""
        )

        assert scraper_tool.enrich_from_web("Film Inconnu") == ""

    def test_succes_retourne_bloc_balise(self, monkeypatch):
        monkeypatch.setattr(
            scraper_tool,
            "extract_wikipedia_synopsis",
            lambda title: "Une maison hantée.",
        )

        result = scraper_tool.enrich_from_web("Conjuring")

        assert result.startswith("[Source : Wikipédia — Conjuring]")
        assert "Une maison hantée." in result
        assert result.endswith("[Fin de l'extrait Wikipédia]")
