"""
tests/test_router.py
=====================
Tests unitaires du routeur déterministe post-RAG (``src/graph/router.py``).

Aucun mock nécessaire : ``route_after_rag`` et ses helpers privés sont des
fonctions pures qui ne font aucun appel LLM, réseau ou base de données —
on leur passe des ``dict`` construits à la main.
"""
from __future__ import annotations

from src.config import FAISS_COSINE_THRESHOLD
from src.graph.router import (
    _extract_best_faiss_score,
    _faiss_is_relevant,
    _structured_has_matches,
    route_after_rag,
)


def _rag_results(
    faiss_score: float | None = None,
    faiss_hits: list[dict] | None = None,
    movies: list[dict] | None = None,
    movies_key: str = "movies",
) -> dict:
    """Construit un ``rag_results`` minimal pour les tests."""
    faiss_block: dict = {"hits": faiss_hits or []}
    if faiss_score is not None:
        faiss_block["best_score"] = faiss_score
    return {
        "faiss": faiss_block,
        "structured": {movies_key: movies or []},
    }


# ═══════════════════════════════════════════════════════════════
# Helpers privés
# ═══════════════════════════════════════════════════════════════

class TestExtractBestFaissScore:
    def test_utilise_best_score_pre_calcule(self):
        rag = _rag_results(faiss_score=0.81)
        assert _extract_best_faiss_score(rag) == 0.81

    def test_fallback_sur_les_hits_si_best_score_absent(self):
        rag = _rag_results(faiss_hits=[{"score": 0.3}, {"score": 0.9}, {"score": 0.5}])
        assert _extract_best_faiss_score(rag) == 0.9

    def test_zero_par_defaut_si_aucun_signal(self):
        rag = {"faiss": {}, "structured": {}}
        assert _extract_best_faiss_score(rag) == 0.0


class TestStructuredHasMatches:
    def test_vrai_si_au_moins_min_structural_matches(self):
        rag = _rag_results(movies=[{"title": "The Exorcist"}])
        assert _structured_has_matches(rag) is True

    def test_faux_si_aucun_film(self):
        rag = _rag_results(movies=[])
        assert _structured_has_matches(rag) is False

    def test_tolerance_sur_le_nom_de_cle_results(self):
        rag = _rag_results(movies=[{"title": "It"}], movies_key="results")
        assert _structured_has_matches(rag) is True

    def test_tolerance_sur_le_nom_de_cle_rows(self):
        rag = _rag_results(movies=[{"title": "It"}], movies_key="rows")
        assert _structured_has_matches(rag) is True


class TestFaissIsRelevant:
    def test_vrai_au_dessus_du_seuil(self):
        rag = _rag_results(faiss_score=FAISS_COSINE_THRESHOLD + 0.1)
        assert _faiss_is_relevant(rag) is True

    def test_vrai_exactement_au_seuil(self):
        rag = _rag_results(faiss_score=FAISS_COSINE_THRESHOLD)
        assert _faiss_is_relevant(rag) is True

    def test_faux_en_dessous_du_seuil(self):
        rag = _rag_results(faiss_score=max(0.0, FAISS_COSINE_THRESHOLD - 0.1))
        assert _faiss_is_relevant(rag) is False


# ═══════════════════════════════════════════════════════════════
# route_after_rag — comportement global
# ═══════════════════════════════════════════════════════════════

class TestRouteAfterRag:
    def test_faiss_et_structure_bons_narration(self):
        state = {
            "rag_results": _rag_results(
                faiss_score=FAISS_COSINE_THRESHOLD + 0.2,
                movies=[{"title": "The Exorcist"}],
            )
        }
        assert route_after_rag(state) == "narration"

    def test_faiss_bon_structure_vide_narration(self):
        """Un seul signal suffisant (FAISS) fait basculer vers narration,
        même si la base structurée n'a rien trouvé — comportement réel
        actuel du router (cf. discussion sur l'écart avec la note de
        Phase 3 dans mon_tutoriel.md)."""
        state = {
            "rag_results": _rag_results(
                faiss_score=FAISS_COSINE_THRESHOLD + 0.2,
                movies=[],
            )
        }
        assert route_after_rag(state) == "narration"

    def test_structure_bon_faiss_faible_narration(self):
        state = {
            "rag_results": _rag_results(
                faiss_score=max(0.0, FAISS_COSINE_THRESHOLD - 0.2),
                movies=[{"title": "It"}],
            )
        }
        assert route_after_rag(state) == "narration"

    def test_faiss_et_structure_mauvais_scraper(self):
        state = {
            "rag_results": _rag_results(
                faiss_score=max(0.0, FAISS_COSINE_THRESHOLD - 0.3),
                movies=[],
            )
        }
        assert route_after_rag(state) == "scraper"

    def test_rag_results_absent_scraper(self):
        assert route_after_rag({}) == "scraper"

    def test_rag_results_type_invalide_scraper(self):
        assert route_after_rag({"rag_results": "pas un dict"}) == "scraper"

    def test_rag_results_none_scraper(self):
        assert route_after_rag({"rag_results": None}) == "scraper"
