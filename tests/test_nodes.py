"""
tests/test_nodes.py
=====================
Tests unitaires des 3 nœuds du graphe (``src/graph/nodes.py``).

Stratégie de mock :
- ``rag_node``       : mocke ``search_local_horror_lore`` et ``query_movie_metadata``.
- ``scraper_node``   : mocke ``enrich_from_web``.
- ``narration_node`` : mocke ``_get_narrator_llm`` (aucun appel Ollama réel)
  et ``find_similar_horror_movies`` (aucune requête pgvector réelle).
  ``calculate_movie_age`` et ``horror_survival_simulator`` restent réels
  (fonctions pures, rapides, déjà couvertes par ``test_horror_tools.py``).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.graph import nodes


# ═══════════════════════════════════════════════════════════════
# rag_node
# ═══════════════════════════════════════════════════════════════

class TestRagNode:
    def test_normalisation_forme_liste(self, monkeypatch):
        monkeypatch.setattr(
            nodes,
            "search_local_horror_lore",
            lambda query, **kw: [
                {"score": 0.6, "text": "extrait A", "source": "lore_a.txt"},
                {"score": 0.9, "text": "extrait B", "source": "lore_b.txt"},
            ],
        )
        monkeypatch.setattr(
            nodes,
            "query_movie_metadata",
            lambda query, **kw: [{"title": "The Exorcist", "year": 1973}],
        )

        result = nodes.rag_node({"query": "Parle-moi de The Exorcist"})

        assert result["rag_results"]["faiss"]["best_score"] == 0.9
        assert len(result["rag_results"]["faiss"]["hits"]) == 2
        assert result["rag_results"]["structured"]["movies"] == [
            {"title": "The Exorcist", "year": 1973}
        ]
        assert result["metadata"]["films_found"] == ["The Exorcist"]
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "The Exorcist" in result["messages"][0].content

    def test_normalisation_forme_dict(self, monkeypatch):
        monkeypatch.setattr(
            nodes,
            "search_local_horror_lore",
            lambda query, **kw: {
                "results": [{"score": 0.7, "chunk": "extrait", "source": "lore.txt"}]
            },
        )
        monkeypatch.setattr(
            nodes,
            "query_movie_metadata",
            lambda query, **kw: {"movies": [{"title": "It", "year": 2017}]},
        )

        result = nodes.rag_node({"query": "Le clown des égouts"})

        assert result["rag_results"]["faiss"]["best_score"] == 0.7
        assert result["rag_results"]["faiss"]["hits"][0]["text"] == "extrait"
        assert result["rag_results"]["structured"]["movies"] == [
            {"title": "It", "year": 2017}
        ]

    def test_tolerance_cle_similarity_au_lieu_de_score(self, monkeypatch):
        monkeypatch.setattr(
            nodes,
            "search_local_horror_lore",
            lambda query, **kw: [{"similarity": 0.5, "text": "x", "source": "s"}],
        )
        monkeypatch.setattr(nodes, "query_movie_metadata", lambda query, **kw: [])

        result = nodes.rag_node({"query": "test"})

        assert result["rag_results"]["faiss"]["best_score"] == 0.5

    def test_resultats_vides(self, monkeypatch):
        monkeypatch.setattr(nodes, "search_local_horror_lore", lambda query, **kw: [])
        monkeypatch.setattr(nodes, "query_movie_metadata", lambda query, **kw: [])

        result = nodes.rag_node({"query": "film totalement inconnu"})

        assert result["rag_results"]["faiss"]["best_score"] == 0.0
        assert result["rag_results"]["structured"]["movies"] == []
        assert result["metadata"]["films_found"] == []
        assert "Aucune correspondance structurée" in result["messages"][0].content

    def test_metadata_existant_est_preserve_pas_ecrase(self, monkeypatch):
        monkeypatch.setattr(nodes, "search_local_horror_lore", lambda query, **kw: [])
        monkeypatch.setattr(nodes, "query_movie_metadata", lambda query, **kw: [])

        state = {"query": "test", "metadata": {"session_id": "abc-123"}}
        result = nodes.rag_node(state)

        assert result["metadata"]["session_id"] == "abc-123"
        assert result["metadata"]["rag_node_executed"] is True


# ═══════════════════════════════════════════════════════════════
# scraper_node
# ═══════════════════════════════════════════════════════════════

class TestScraperNode:
    def test_titre_extrait_du_structure(self, monkeypatch):
        monkeypatch.setattr(nodes, "enrich_from_web", lambda title: f"contenu web sur {title}")

        state = {
            "query": "peu importe",
            "rag_results": {
                "faiss": {"hits": []},
                "structured": {"movies": [{"title": "It"}]},
            },
        }
        result = nodes.scraper_node(state)

        assert result["scraped_data"]["title"] == "It"
        assert result["scraped_data"]["success"] is True
        assert "contenu web sur It" in result["scraped_data"]["content"]

    def test_titre_extrait_des_noms_propres_de_la_query(self, monkeypatch):
        captured = {}

        def fake_enrich(title):
            captured["title"] = title
            return "un synopsis"

        monkeypatch.setattr(nodes, "enrich_from_web", fake_enrich)

        state = {"query": "Parle-moi de The Exorcist", "rag_results": {}}
        nodes.scraper_node(state)

        assert captured["title"] == "The Exorcist"

    def test_titre_extrait_du_hit_faiss_si_rien_dans_la_query(self, monkeypatch):
        captured = {}

        def fake_enrich(title):
            captured["title"] = title
            return "un synopsis"

        monkeypatch.setattr(nodes, "enrich_from_web", fake_enrich)

        state = {
            "query": "quel est ce film",
            "rag_results": {
                "faiss": {"hits": [{"text": "Titre: It\nautre ligne"}]},
                "structured": {"movies": []},
            },
        }
        nodes.scraper_node(state)

        assert captured["title"] == "It"

    def test_fallback_sur_la_query_brute(self, monkeypatch):
        captured = {}

        def fake_enrich(title):
            captured["title"] = title
            return ""

        monkeypatch.setattr(nodes, "enrich_from_web", fake_enrich)

        state = {"query": "un film sans indice", "rag_results": {}}
        result = nodes.scraper_node(state)

        assert captured["title"] == "un film sans indice"
        assert result["scraped_data"]["success"] is False


# ═══════════════════════════════════════════════════════════════
# narration_node
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def fake_llm(monkeypatch):
    """Remplace le LLM Ollama par un mock capturant les messages envoyés."""
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(content="Une chronique gothique captivante.")
    monkeypatch.setattr(nodes, "_get_narrator_llm", lambda: llm)
    return llm


class TestNarrationNode:
    def test_reponse_construite_avec_corpus_structure_et_faiss(self, fake_llm):
        state = {
            "query": "Parle-moi de The Exorcist",
            "messages": [],
            "rag_results": {
                "faiss": {
                    "hits": [{"text": "Regan est possédée...", "score": 0.88, "source": "lore.txt"}]
                },
                "structured": {
                    "movies": [
                        {"title": "The Exorcist", "year": 1973, "director": "William Friedkin"}
                    ]
                },
            },
            "scraped_data": None,
        }
        result = nodes.narration_node(state)

        assert result["final_answer"] == "Une chronique gothique captivante."
        assert len(result["messages"]) == 1
        assert any(s["type"] == "structured" for s in result["sources"])
        assert any(s["type"] == "faiss" for s in result["sources"])
        fake_llm.invoke.assert_called_once()

    def test_fallback_gothique_si_le_llm_echoue(self, fake_llm):
        fake_llm.invoke.side_effect = ConnectionError("Ollama indisponible")

        state = {
            "query": "The Exorcist",
            "messages": [],
            "rag_results": {"faiss": {"hits": []}, "structured": {"movies": []}},
            "scraped_data": None,
        }
        result = nodes.narration_node(state)

        assert "archives gothiques se taisent" in result["final_answer"]

    def test_scraped_data_integre_au_corpus_si_succes(self, fake_llm):
        state = {
            "query": "It",
            "messages": [],
            "rag_results": {"faiss": {"hits": []}, "structured": {"movies": []}},
            "scraped_data": {"title": "It", "content": "Un clown terrifiant.", "success": True},
        }
        nodes.narration_node(state)

        human_prompt = fake_llm.invoke.call_args[0][0][1].content
        assert "ENRICHISSEMENT WEB" in human_prompt
        assert "Un clown terrifiant." in human_prompt

    def test_outil_recommandation_declenche_sur_mot_cle(self, fake_llm, monkeypatch):
        monkeypatch.setattr(
            nodes,
            "find_similar_horror_movies",
            lambda id_film, k=3: [
                {"titre": "The Conjuring", "annee_sortie": 2013, "similarite": 0.91}
            ],
        )
        state = {
            "query": "Recommande-moi un film similaire à The Exorcist",
            "messages": [],
            "rag_results": {
                "faiss": {"hits": []},
                "structured": {"movies": [{"title": "The Exorcist", "id": 1}]},
            },
            "scraped_data": None,
        }
        nodes.narration_node(state)

        human_prompt = fake_llm.invoke.call_args[0][0][1].content
        assert "RECOMMANDATIONS PAR SIMILARITÉ" in human_prompt
        assert "The Conjuring" in human_prompt

    def test_outil_survie_declenche_sur_mot_cle(self, fake_llm):
        state = {
            "query": "Ai-je une chance de survivre à ce tueur ?",
            "messages": [],
            "rag_results": {"faiss": {"hits": []}, "structured": {"movies": []}},
            "scraped_data": None,
        }
        nodes.narration_node(state)

        human_prompt = fake_llm.invoke.call_args[0][0][1].content
        assert "SIMULATEUR DE SURVIE" in human_prompt

    def test_isolation_messages_ne_contamine_pas_le_corpus_factuel(self, fake_llm):
        """L'historique brut (state['messages']) ne doit jamais alimenter le
        corpus factuel — seuls rag_results/scraped_data le peuvent. Ici,
        rag_results et scraped_data sont vides : le corpus doit rester
        vide malgré un historique de conversation riche."""
        state = {
            "query": "Et sinon ?",
            "messages": [
                HumanMessage(content="Question précédente"),
                AIMessage(
                    content="🖋️ Narration générée (30 caractères) — 1 source(s).\n\n"
                    "Ceci est la réponse précédente."
                ),
                HumanMessage(content="Et sinon ?"),
            ],
            "rag_results": {"faiss": {"hits": []}, "structured": {"movies": []}},
            "scraped_data": None,
        }
        nodes.narration_node(state)

        human_prompt = fake_llm.invoke.call_args[0][0][1].content
        assert "Aucune donnée encyclopédique" in human_prompt
        # Le contexte de dialogue (ton/mémoire), lui, est bien reconstruit :
        assert "Ceci est la réponse précédente." in human_prompt
        assert "LECTEUR : Question précédente" in human_prompt
