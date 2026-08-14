"""
scripts/generate_graph_doc.py
==============================
Génère automatiquement la page Sphinx de cartographie du graphe
multi-agent (``docs/source/graphe_multi_agent.rst``) à partir du
graphe LangGraph réellement compilé par ``src.graph.pipeline``.

Le script compile le graphe (``build_horragor_graph()``) puis appelle
``graph.get_graph().draw_mermaid()`` : le code Mermaid produit est du
texte pur, intégré directement dans une directive ``.. mermaid::`` —
aucun appel réseau (contrairement à ``draw_mermaid_png()``, qui passe
par l'API en ligne mermaid.ink), donc reproductible hors-ligne.

Relancer ce script si la topologie du graphe change (nouveau nœud,
nouvelle arête) :
    uv run python scripts/generate_graph_doc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

from src.graph.pipeline import build_horragor_graph

DOCS_SOURCE_DIR = PROJECT_ROOT / "docs" / "source"
OUTPUT_RST = DOCS_SOURCE_DIR / "graphe_multi_agent.rst"


def _build_rst_document(mermaid_code: str) -> str:
    """
    Assemble le document reST complet (diagramme + explications).

    :param mermaid_code: Code Mermaid brut renvoyé par
        ``graph.get_graph().draw_mermaid()``.
    :returns: Contenu complet de ``graphe_multi_agent.rst``.
    """
    indented_mermaid = "\n".join(
        f"   {line}" if line else "" for line in mermaid_code.splitlines()
    )

    return (
        "Cartographie du graphe multi-agent\n"
        "====================================\n\n"
        "Ce document est **généré automatiquement** par "
        "``scripts/generate_graph_doc.py`` à partir du graphe LangGraph "
        "réellement compilé (``build_horragor_graph()``) — le diagramme "
        "ci-dessous reflète toujours la topologie effective du code, pas "
        "une description à jour manuellement. Relancez ce script si la "
        "topologie change :\n\n"
        "::\n\n"
        "    uv run python scripts/generate_graph_doc.py\n\n"
        "Architecture Peer-to-Peer\n"
        "---------------------------\n\n"
        "Pas de superviseur central : ``rag_node`` est le point d'entrée, "
        "et ``route_after_rag`` (fonction Python déterministe, zéro appel "
        "LLM) décide de l'arête à suivre selon la qualité des résultats "
        "RAG.\n\n"
        ".. mermaid::\n\n"
        f"{indented_mermaid}\n\n"
        "Nœuds\n"
        "-------\n\n"
        "- ``rag_node`` — interroge à la fois le vectoriel (FAISS) et le "
        "structuré (SQL via data-api).\n"
        "- ``scraper_node`` — enrichissement Wikipédia, déclenché "
        "uniquement si ``route_after_rag`` renvoie ``\"scraper\"``.\n"
        "- ``narration_node`` — isolation stricte de contexte : ne lit "
        "que ``rag_results`` et ``scraped_data``, jamais l'historique "
        "brut des autres nœuds.\n\n"
        "Router\n"
        "--------\n\n"
        "``route_after_rag`` : fonction Python pure (aucun LLM) qui "
        "bascule vers ``\"narration\"`` si les résultats RAG sont "
        "suffisants, sinon vers ``\"scraper\"``.\n\n"
        "Checkpointer\n"
        "--------------\n\n"
        "``MemorySaver`` (mémoire de session en RAM), instancié à la "
        "compilation dans ``pipeline.py``.\n"
    )


def main() -> None:
    """
    Point d'entrée : compile le graphe et écrit ``graphe_multi_agent.rst``.
    """
    logger.info("[GraphDoc] Compilation du graphe HorRAGor...")
    graph = build_horragor_graph()

    mermaid_code = graph.get_graph().draw_mermaid()
    logger.info("[GraphDoc] Code Mermaid généré depuis la topologie réelle.")

    content = _build_rst_document(mermaid_code)
    OUTPUT_RST.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_RST.write_text(content, encoding="utf-8")

    logger.success(f"[GraphDoc] Écrit : {OUTPUT_RST}")


if __name__ == "__main__":
    main()
