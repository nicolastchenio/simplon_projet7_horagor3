# HorRAGor 🎬🩸

Chatbot spécialisé cinéma d'horreur, propulsé par un **graphe multi-agent LangGraph** (RAG + Scraper + Narration) interrogeant une base de 7392 films, avec inférence 100 % locale via Ollama.

## Aperçu

HorRAGor répond aux questions des utilisateurs sur le cinéma d'horreur en s'appuyant sur un graphe **peer-to-peer** (aucun superviseur LLM) : un routeur Python déterministe aiguille la requête entre trois agents spécialisés.

| Agent | Rôle |
|---|---|
| **RAG** | Recherche vectorielle (FAISS) **et** structurée (SQL, via l'API Données) sur le savoir local |
| **Scraper** | Enrichissement Wikipédia, déclenché uniquement si le savoir local est insuffisant |
| **Narration** | Rédige la réponse finale dans la peau d'un chroniqueur gothique — isolation stricte de contexte (ne lit jamais l'historique brut des autres agents) et consigne anti-hallucination |

## 🔗 URLs utiles

*(une fois les conteneurs Docker démarrés)*

| Service | URL | Description |
|---|---|---|
| Frontend Streamlit | http://localhost:8501/ | Interface de chat |
| API Intelligence (docs) | https://localhost:8000/docs | Swagger FastAPI — endpoints `/chat`, `/auth`, `/health` |
| Langfuse | http://localhost:3000/ | Traces d'exécution du graphe (latences, tokens, prompts) |
| Prometheus | http://localhost:9092/ | Métriques brutes des deux API |
| Grafana | http://localhost:3002/ | Dashboards de monitoring |
| Uptime Kuma | http://localhost:3003/ | Surveillance de disponibilité des 3 services |

> L'API Données (`data_api`, port 8001) n'a volontairement **aucune URL publique** : elle n'est joignable que par l'API Intelligence sur le réseau Docker interne (cf. section *Architecture* ci-dessous).

## 🏗️ Architecture

Trois couches strictement séparées — le frontend ne parle jamais directement à la base de données :

| Couche | Rôle | Composant |
|---|---|---|
| Présentation | Interface utilisateur | Streamlit (`app_frontend.py`, port 8501) |
| Intelligence | Graphe multi-agent LangGraph | `src/main.py` (port 8000, HTTPS) |
| Données | Seule couche autorisée à parler à Supabase | `data_api/main.py` (port 8001, interne uniquement) |

```
┌─────────────┐   HTTPS/JWT    ┌───────────────────┐   HTTP interne   ┌──────────────┐   SQL+SSL   ┌──────────┐
│  Streamlit  │ ─────────────► │  Intelligence API │ ───────────────► │   Data API   │ ──────────► │ Supabase │
│  (8501)     │ ◄───────────── │  (8000, LangGraph) │ ◄─────────────── │   (8001)     │ ◄────────── │(pgvector)│
└─────────────┘   JSON réponse └───────────────────┘   JSON données   └──────────────┘             └──────────┘
```

Le réseau Docker `horragor_net` isole `data_api` de l'extérieur : seule `intelligence-api` peut le joindre. `frontend` est le seul service avec un port publié vers l'hôte.

## 🛠️ Stack technique

- **Orchestration agents** : LangGraph, LangChain
- **Inférence locale** : Ollama — `qwen2.5:7b` (génération) et `nomic-embed-text` (embeddings, 768D)
- **Recherche vectorielle** : FAISS (index local) + pgvector (Supabase)
- **Backend** : FastAPI, Uvicorn, Pydantic
- **Frontend** : Streamlit
- **Base de données** : Supabase (PostgreSQL + extension pgvector)
- **Authentification** : JWT (access + refresh tokens), bcrypt
- **Observabilité** : Langfuse (traces LLM), Loguru (logs JSON structurés), Prometheus + Grafana + Uptime Kuma
- **Tests** : pytest, pytest-cov (couverture ≥80 % imposée sur les 2 API + l'UI)
- **Documentation** : Sphinx (autodoc, napoleon, myst-parser, mermaid)
- **Conteneurisation** : Docker Compose (réseau `bridge` dédié)
- **Packaging** : `uv`

## 📁 Structure du projet

```
horragor-project/
├── .streamlit/
│   └── config.toml                  # Thème "Horror" (Phase 0.4)
├── certs/                           # Certificats TLS auto-signés (générés, non versionnés)
├── data/
│   ├── faiss_index/                 # Index vectoriel généré en Phase 1
│   │   ├── horror_index.faiss       # Embeddings 768D (nomic-embed-text)
│   │   └── metadata.pkl             # Pont position vecteur → id_film / titre / année
│   └── build_faiss_index.py         # Script one-shot : génère l'index FAISS depuis Supabase
├── data_api/                        # Micro-service Données (Phase 6, port 8001)
│   ├── config.py
│   ├── database.py                  # Connexion PostgreSQL + wrapper de logging SQL
│   ├── models.py                    # Schémas Pydantic
│   ├── main.py                      # Point d'entrée FastAPI
│   ├── observability/
│   │   └── logging_config.py        # Config Loguru (JSON, rotation)
│   └── routers/
│       └── films.py                 # Endpoints /films (recherche, fuzzy, détail, similarité pgvector)
├── docker/                          # Dockerfiles des 3 services applicatifs
│   ├── data_api.Dockerfile          # Image du service Données (port 8001)
│   ├── frontend.Dockerfile          # Image du frontend Streamlit (port 8501)
│   └── intelligence_api.Dockerfile  # Image du service Intelligence (port 8000, HTTPS)
├── docs/                            # Documentation technique Sphinx (Phase 9)
│   └── source/
│       ├── conf.py                  # autodoc, napoleon, myst_parser, sphinxcontrib.mermaid
│       ├── index.rst                # Sommaire
│       ├── readme.rst               # Inclusion de ce README (myst_parser)
│       ├── intelligence_api.rst     # Doc API automatique — Intelligence
│       ├── data_api.rst             # Doc API automatique — Données
│       ├── schema_bdd.rst           # Schéma relationnel (généré, cf. scripts/)
│       └── graphe_multi_agent.rst   # Cartographie du graphe (générée, cf. scripts/)
├── grafana/
│   └── provisioning/datasources/    # Datasource Prometheus auto-provisionnée
├── logs/                            # Logs Loguru des 3 services (volume Docker, non versionné)
├── observability/                   # Logging Loguru du frontend Streamlit
│   └── logging_config.py
├── scripts/                         # Scripts utilitaires ponctuels
│   ├── faiss_to_pgvector.py         # Copie les vecteurs FAISS existants vers pgvector
│   ├── generate_cert.py             # Génère le certificat TLS auto-signé (Phase 7.3)
│   ├── generate_db_schema_doc.py    # Génère docs/source/schema_bdd.rst par introspection SQL
│   └── generate_graph_doc.py        # Génère docs/source/graphe_multi_agent.rst via draw_mermaid()
├── src/                             # API Intelligence — graphe LangGraph (port 8000)
│   ├── main.py                      # Serveur FastAPI, endpoints /chat et /health
│   ├── config.py                    # Configuration centralisée (Ollama, secrets, chemins)
│   ├── api/
│   │   └── auth.py                  # Endpoints /auth (login, refresh)
│   ├── auth/
│   │   └── security.py              # Hash bcrypt + émission/validation JWT
│   ├── graph/
│   │   ├── nodes.py                 # rag_node, scraper_node, narration_node
│   │   ├── router.py                # route_after_rag — aiguillage déterministe
│   │   └── pipeline.py              # Câblage et compilation du graphe
│   ├── models/
│   │   └── state.py                 # AgentState — mémoire commune partagée
│   ├── observability/
│   │   ├── logging_config.py        # Config Loguru (JSON, rotation, interception stdlib)
│   │   ├── json_serializer.py       # Aplatit les logs Loguru en JSON pour le monitoring
│   │   └── langfuse_client.py
│   └── tools/
│       ├── rag_tool.py              # FAISS + appels HTTP vers data-api
│       ├── scraper_tool.py          # Enrichissement Wikipédia (API MediaWiki)
│       └── horror_tools.py          # Âge du film, simulateur de survie
├── tests/                           # Suite de tests (Phase 10.1/10.2/10.3)
│   ├── test_auth_endpoints.py       # Endpoints /auth/login, /auth/refresh
│   ├── test_data_api_app.py         # App data-api réelle (health, config, models, /metrics)
│   ├── test_data_api_database.py    # Wrapper de logging PostgreSQL (_LoggingCursor/Connection)
│   ├── test_data_api_films.py       # Endpoints /films/* (BDD mockée)
│   ├── test_frontend.py             # UI Streamlit (JWT, auth, chat, pages)
│   ├── test_horror_tools.py         # calculate_movie_age, horror_survival_simulator
│   ├── test_integration_chat.py     # Flux RAG→Narration / RAG→Scraper→Narration, auth complète
│   ├── test_nodes.py                # rag_node, scraper_node, narration_node (outils mockés)
│   ├── test_rag_tool.py             # FAISS local + appels HTTP data-api
│   ├── test_router.py               # route_after_rag (routeur déterministe)
│   ├── test_scraper_tool.py         # Scraping Wikipédia (API MediaWiki mockée)
│   └── test_security.py             # bcrypt + cycle de vie JWT
├── app_frontend.py                  # UI Streamlit (Phase 5)
├── docker-compose.yml               # Orchestration des services (prod-like)
├── docker-compose.dev.yml           # Override dev (ports exposés, volumes de logs)
├── prometheus.yml                   # Configuration du scraping Prometheus
├── pyproject.toml                   # Dépendances et métadonnées (uv)
└── .env.example                     # Modèle de configuration (sans secrets)
```

## ✅ Prérequis

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Ollama](https://ollama.com/) installé **au niveau système** (pas dans l'environnement Python), avec les deux modèles :
  ```
  ollama pull qwen2.5:7b
  ollama pull nomic-embed-text
  ```
- [`uv`](https://docs.astral.sh/uv/) pour la gestion des dépendances Python
- Un projet [Supabase](https://supabase.com/) avec l'extension `pgvector` activée (voir `.env.example` pour les variables attendues)

## 🚀 Démarrage

```bash
# Build + démarrage de tous les services (mode dev : ports exposés, logs en volume)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Vérification
docker ps
```

Pour tout arrêter proprement :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

Les URLs de chaque service une fois démarré sont listées dans la section *URLs utiles* ci-dessus.

## 🔒 Sécurité — Communication chiffrée (TLS)

La communication Streamlit → API Intelligence est chiffrée via un certificat auto-signé (suffisant pour le développement) :

```
Navigateur (HTTP) → Streamlit (8501) → HTTPS + certificat auto-signé → Intelligence API (8000)
```

Génération du certificat (`certs/cert.pem` + `certs/key.pem`, valides pour `localhost` et les domaines internes Docker) :

```bash
uv run python scripts/generate_cert.py
```

En production, ces fichiers doivent être remplacés par un certificat réel (Let's Encrypt/`certbot` ou équivalent) — voir les commentaires du script pour le détail.

## 📚 Documentation technique (Sphinx)

La documentation technique complète du projet (doc API automatique des deux services, schéma relationnel de la base, cartographie du graphe multi-agent) est générée avec Sphinx dans `docs/`.

```bash
# Régénérer les pages dépendantes du code/de la base avant de builder (si le schéma ou le graphe ont changé)
uv run python scripts/generate_db_schema_doc.py
uv run python scripts/generate_graph_doc.py

# Build HTML
uv run sphinx-build -b html docs/source docs/build/html
```

La doc est ensuite consultable dans `docs/build/html/index.html`.

## 🧪 Tests & couverture

La suite de tests (217 tests) couvre les deux API et l'interface Streamlit, avec un seuil de couverture minimal de 80 % imposé via `pytest-cov` (`fail_under` dans `pyproject.toml`).

```bash
uv run pytest --cov --cov-report=term-missing
```

Couverture actuelle : **~96 %** (`src` ~94 %, `data_api` ~99 %, `app_frontend.py` ~99 %).
