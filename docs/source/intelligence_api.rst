Documentation de l'API Intelligence
====================================

API Intelligence (port 8000) : serveur FastAPI qui compile et invoque le
graphe multi-agent LangGraph (RAG, Scraper, Narration).

Point d'entrée FastAPI
-----------------------

.. automodule:: src.main
   :members:
   :undoc-members:
   :show-inheritance:

Authentification
-----------------

.. automodule:: src.api.auth
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.auth.security
   :members:
   :undoc-members:
   :show-inheritance:

Graphe multi-agent
-------------------

.. automodule:: src.graph.pipeline
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.graph.nodes
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.graph.router
   :members:
   :undoc-members:
   :show-inheritance:

Outils (Tools)
---------------

.. automodule:: src.tools.rag_tool
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.tools.scraper_tool
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.tools.horror_tools
   :members:
   :undoc-members:
   :show-inheritance:

State partagé
---------------

.. automodule:: src.models.state
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
---------------

.. automodule:: src.config
   :members:
   :undoc-members:
   :show-inheritance:

Observabilité
---------------

.. automodule:: src.observability.logging_config
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.observability.langfuse_client
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.observability.json_serializer
   :members:
   :undoc-members:
   :show-inheritance:
