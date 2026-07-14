"""Schéma de l'état partagé du graphe HorRAGor.

Ce module définit AgentState, la structure de données commune que tous
les nœuds du graphe LangGraph lisent et enrichissent à chaque étape.
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """État global d'une exécution du graphe HorRAGor.

    Chaque champ représente une donnée qui transite de nœud en nœud.
    Certains champs utilisent des *reducers* (via Annotated) pour éviter
    que la valeur ne soit écrasée à chaque mise à jour par un agent.
    """

    # ------------------------------------------------------------------
    # Mémoire de conversation
    # ------------------------------------------------------------------
    # Historique accumulé des échanges (Humain + IA).
    # Le reducer add_messages fusionne automatiquement les nouveaux messages
    # avec la liste existante, au lieu de remplacer la liste entière.
    # ------------------------------------------------------------------
    messages: Annotated[list[BaseMessage], add_messages]

    # ------------------------------------------------------------------
    # Entrée utilisateur
    # ------------------------------------------------------------------
    # Requête brute posée par l'utilisateur dans le chat.
    # Remplie une seule fois au démarrage du graphe.
    # ------------------------------------------------------------------
    query: str

    # ------------------------------------------------------------------
    # Résultats de la couche RAG (Phase 1)
    # ------------------------------------------------------------------
    # Conteneur hybride regroupant les résultats :
    #   - "vectorial"  : résultats de la recherche FAISS (embedding).
    #   - "structured" : résultats de la requête SQL (métadonnées).
    # Utilisé par le router pour décider si un enrichissement est nécessaire.
    # ------------------------------------------------------------------
    rag_results: dict[str, Any]

    # ------------------------------------------------------------------
    # Enrichissement Web (Phase 3)
    # ------------------------------------------------------------------
    # Texte brut récupéré par le scraper (ex: synopsis Wikipedia).
    # Vide ("") si le routeur a décidé de sauter l'étape scraping.
    # ------------------------------------------------------------------
    scraped_data: str

    # ------------------------------------------------------------------
    # Décision du routeur
    # ------------------------------------------------------------------
    # True si le router a décidé d'activer le scraper_node.
    # Bien que cette valeur soit déductible de rag_results, elle est stockée
    # explicitement pour la traçabilité (debug, tests unitaires, audit Langfuse).
    # ------------------------------------------------------------------
    needs_enrichment: bool

    # ------------------------------------------------------------------
    # Sortie finale de l'Agent de Narration
    # ------------------------------------------------------------------
    # Réponse textuelle finale, prête à être affichée à l'utilisateur.
    # Remplie exclusivement par le narration_node.
    # ------------------------------------------------------------------
    final_answer: str

    # ------------------------------------------------------------------
    # Sources à retourner dans l'API
    # ------------------------------------------------------------------
    # Liste des sources utilisées pour construire la réponse finale.
    # Chaque entrée est un dict {"title": ..., "url": ..., "type": ...}.
    # Le narration_node est responsable de remplir ce champ afin que l'API
    # FastAPI n'ait aucun recalcul à faire.
    # ------------------------------------------------------------------
    sources: list[dict[str, str]]

    # ------------------------------------------------------------------
    # Métadonnées annexes
    # ------------------------------------------------------------------
    # Informations complémentaires : films trouvés, scores de similarité,
    # nœuds visités par le graphe, temps d'exécution, etc.
    # Utile pour le debugging et les analytics.
    # ------------------------------------------------------------------
    metadata: dict[str, Any]