"""
src/graph/pipeline.py
Câblage et compilation du graphe Peer-to-Peer HorRAGor.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.models.state import AgentState
from src.graph.nodes import rag_node, scraper_node, narration_node
from src.graph.router import route_after_rag


def build_horragor_graph():
    """
    Construit et compile le graphe multi-agent.

    Architecture Peer-to-Peer (pas de superviseur LLM) :
        rag_node ──[route_after_rag]──┬──► narration_node ──► END
                                      └──► scraper_node ──► narration_node ──► END
    """
    workflow = StateGraph(AgentState)

    # ── Enregistrement des nœuds ──
    workflow.add_node("rag_node", rag_node)
    workflow.add_node("scraper_node", scraper_node)
    workflow.add_node("narration_node", narration_node)

    # ── Point d'entrée ──
    workflow.set_entry_point("rag_node")

    # ── Edge conditionnel post-RAG ──
    workflow.add_conditional_edges(
        "rag_node",
        route_after_rag,
        {
            "scraper": "scraper_node",
            "narration": "narration_node",
        },
    )

    # ── Edges fixes ──
    workflow.add_edge("scraper_node", "narration_node")
    workflow.add_edge("narration_node", END)

    # ── Compilation avec checkpointer (mémoire de session) ──
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)