Cartographie du graphe multi-agent
====================================

Ce document est **généré automatiquement** par ``scripts/generate_graph_doc.py`` à partir du graphe LangGraph réellement compilé (``build_horragor_graph()``) — le diagramme ci-dessous reflète toujours la topologie effective du code, pas une description à jour manuellement. Relancez ce script si la topologie change :

::

    uv run python scripts/generate_graph_doc.py

Architecture Peer-to-Peer
---------------------------

Pas de superviseur central : ``rag_node`` est le point d'entrée, et ``route_after_rag`` (fonction Python déterministe, zéro appel LLM) décide de l'arête à suivre selon la qualité des résultats RAG.

.. mermaid::

   ---
   config:
     flowchart:
       curve: linear
   ---
   graph TD;
   	__start__([<p>__start__</p>]):::first
   	rag_node(rag_node)
   	scraper_node(scraper_node)
   	narration_node(narration_node)
   	__end__([<p>__end__</p>]):::last
   	__start__ --> rag_node;
   	rag_node -. &nbsp;narration&nbsp; .-> narration_node;
   	rag_node -. &nbsp;scraper&nbsp; .-> scraper_node;
   	scraper_node --> narration_node;
   	narration_node --> __end__;
   	classDef default fill:#f2f0ff,line-height:1.2
   	classDef first fill-opacity:0
   	classDef last fill:#bfb6fc

Nœuds
-------

- ``rag_node`` — interroge à la fois le vectoriel (FAISS) et le structuré (SQL via data-api).
- ``scraper_node`` — enrichissement Wikipédia, déclenché uniquement si ``route_after_rag`` renvoie ``"scraper"``.
- ``narration_node`` — isolation stricte de contexte : ne lit que ``rag_results`` et ``scraped_data``, jamais l'historique brut des autres nœuds.

Router
--------

``route_after_rag`` : fonction Python pure (aucun LLM) qui bascule vers ``"narration"`` si les résultats RAG sont suffisants, sinon vers ``"scraper"``.

Checkpointer
--------------

``MemorySaver`` (mémoire de session en RAM), instancié à la compilation dans ``pipeline.py``.
