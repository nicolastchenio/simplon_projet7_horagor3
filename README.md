horragor-project/
├── data/
│   └── faiss_index/          # Index vectoriel généré en Phase 1
│   │   ├── horror_index.faiss
│   │   └── metadata.pkl
│   └── build_faiss_index.py 
├── data_api/      ← (NOUVEAU)
│   ├── __init__.py
│   ├── database.py
│   ├── models.py
│   ├── main.py
│   └── routers/
│       ├── __init__.py
│       └── films.py
├── app_frontend.py           # UI Streamlit (Phase 5)
├── .streamlit/
│   └── config.toml           # Thème "Horror" (Phase 0.4)
├── src/
│   ├── main.py               # Serveur FastAPI (API Intelligence)
│   ├── config.py             # Config Ollama, clés API, chemins
│   ├── models/
│   │   └── state.py          # State partagé (mémoire commune)
│   ├── tools/
│   │   ├── rag_tool.py       # Recherche FAISS + SQL + pgvector
│   │   ├── scraper_tool.py   # Recherche Web (Wikipedia)
│   │   └── horror_tools.py   # Outils annexes (âge, simulateur de survie)
│   └── graph/
│       ├── nodes.py          # Logique RAG, Scraper, Narration
│       ├── router.py         # Fonctions d'aiguillage conditionnel
│       └── pipeline.py       # Câblage et compilation du graphe
├── docs/                     # Sphinx (Phase 9)
├── tests/                    # Tests unitaires & intégration
├── pyproject.toml
└── .env