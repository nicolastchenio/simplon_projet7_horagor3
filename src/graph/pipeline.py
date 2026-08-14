"""
src/graph/pipeline.py
Câblage et compilation du graphe Peer-to-Peer HorRAGor.

Traçabilité
-----------
La compilation du graphe est journalisée au démarrage (appelée une
seule fois depuis le lifespan de src/main.py) : nœuds enregistrés,
point d'entrée, arêtes fixes et conditionnelles, checkpointer et
durée de compilation. Ces logs constituent la preuve de la topologie
effectivement déployée.
"""

import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from src.graph.nodes import narration_node, rag_node, scraper_node
from src.graph.router import route_after_rag
from src.models.state import AgentState


def build_horragor_graph():
    """
    Construit et compile le graphe multi-agent.

    Architecture Peer-to-Peer (pas de superviseur LLM) :
        rag_node ──[route_after_rag]──┬──► narration_node ──► END
                                      └──► scraper_node ──► narration_node ──► END

    :returns: Le graphe compilé, muni d'un checkpointer mémoire.
    :raises Exception: Si la compilation échoue (câblage invalide).
    """
    start = time.perf_counter()
    logger.info("[Graph] ═══ Construction du graphe HorRAGor (Peer-to-Peer) ═══")

    workflow = StateGraph(AgentState)
    logger.debug(f"[Graph] StateGraph initialisé — état : {AgentState.__name__}")

    # ── Enregistrement des nœuds ──
    nodes = {
        "rag_node": rag_node,
        "scraper_node": scraper_node,
        "narration_node": narration_node,
    }
    for name, fn in nodes.items():
        workflow.add_node(name, fn)
        logger.debug(f"[Graph] Nœud enregistré : '{name}' → {fn.__name__}()")

    # ── Point d'entrée ──
    workflow.set_entry_point("rag_node")
    logger.debug("[Graph] Point d'entrée : 'rag_node'")

    # ── Edge conditionnel post-RAG ──
    branches = {
        "scraper": "scraper_node",
        "narration": "narration_node",
    }
    workflow.add_conditional_edges("rag_node", route_after_rag, branches)
    logger.debug(
        f"[Graph] Arête conditionnelle : 'rag_node' "
        f"--[{route_after_rag.__name__}]--> {branches}"
    )

    # ── Edges fixes ──
    edges = [
        ("scraper_node", "narration_node"),
        ("narration_node", END),
    ]
    for src, dst in edges:
        workflow.add_edge(src, dst)
        logger.debug(f"[Graph] Arête fixe : '{src}' --> "
                     f"{'END' if dst is END else repr(dst)}")

    # ── Compilation avec checkpointer (mémoire de session) ──
    memory = MemorySaver()
    logger.debug("[Graph] Checkpointer : MemorySaver (mémoire de session en RAM)")

    try:
        compiled = workflow.compile(checkpointer=memory)
    except Exception as exc:
        logger.error(f"[Graph] ✗ Échec de la compilation du graphe : {exc}")
        raise

    elapsed = (time.perf_counter() - start) * 1000
    logger.success(
        f"[Graph] ✓ Graphe compilé — {len(nodes)} nœuds, "
        f"{len(edges)} arêtes fixes, 1 arête conditionnelle "
        f"({len(branches)} branches), durée={elapsed:.2f} ms"
    )
    return compiled