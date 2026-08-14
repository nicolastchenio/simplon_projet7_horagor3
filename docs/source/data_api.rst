Documentation de l'API Données
================================

Data-API (port 8001) : micro-service FastAPI qui encapsule le seul accès
autorisé à Supabase (recherche structurée, similarité pgvector). L'API
Intelligence ne parle jamais directement à la base de données.

Point d'entrée FastAPI
-----------------------

.. automodule:: data_api.main
   :members:
   :undoc-members:
   :show-inheritance:

Endpoints films
-----------------

.. automodule:: data_api.routers.films
   :members:
   :undoc-members:
   :show-inheritance:

Modèles de données
--------------------

.. automodule:: data_api.models
   :members:
   :undoc-members:
   :show-inheritance:

Connexion base de données
----------------------------

.. automodule:: data_api.database
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
---------------

.. automodule:: data_api.config
   :members:
   :undoc-members:
   :show-inheritance:

Observabilité
---------------

.. automodule:: data_api.observability.logging_config
   :members:
   :undoc-members:
   :show-inheritance:
