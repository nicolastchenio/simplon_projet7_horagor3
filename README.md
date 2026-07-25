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
├── docker
│   ├── data_api.Dockerfile
│   ├── frontend.Dockerfile
│   └── intelligence_api.Dockerfile
├── scripts
│   └── faiss_to_pgvector.py
├── .streamlit/
│   └── config.toml           # Thème "Horror" (Phase 0.4)
├── src/
│   ├── __init__.py
│   ├── main.py               # Serveur FastAPI (API Intelligence)
│   ├── config.py             # Config Ollama, clés API, chemins
│   │──api/
│   │   ├── __init__.py
│   │   └── auth.py  
│   │──auth/
│   │   ├── __init__.py
│   │   └── security.py  
│   │──models/
│   │   ├── __init__.py
│   │   └── state.py          # State partagé (mémoire commune)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── rag_tool.py       # Recherche FAISS + SQL + pgvector
│   │   ├── scraper_tool.py   # Recherche Web (Wikipedia)
│   │   └── horror_tools.py   # Outils annexes (âge, simulateur de survie)
│   └── graph/
│       ├── __init__.py
│       ├── nodes.py          # Logique RAG, Scraper, Narration
│       ├── router.py         # Fonctions d'aiguillage conditionnel
│       └── pipeline.py       # Câblage et compilation du graphe
├── docs/                     # Sphinx (Phase 9)
├── tests/                    # Tests unitaires & intégration
├── pyproject.toml
├── app_frontend.py           # UI Streamlit (Phase 5)
├── .gitignore
├── docker-compose.dev.yml
├── docker-compose.yml
├── .env
├── .env.docker
└── .env.example