# Plan HorRAGor BOT — Partie 3

## Phase 0 : Préparation & Rattrapage des éléments de la Partie 2 ##

Avant de coder le multi-agent, tu dois poser les fondations techniques manquantes (la Partie 2 n'a pas été réalisée).

### 0.1 Restructurer le projet selon l'architecture Partie 3 ###

Adapte ton dépôt pour coller à cette arborescence :

```
horragor-project/
├── data/
│   └── faiss_index/          # Index vectoriel généré en Phase 1
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
```

À partir de la Phase 6, cette arborescence évolue vers 3 services séparés (`data-api/`, `intelligence-api/` = le contenu ci-dessus, `frontend/`) — inutile de l'anticiper maintenant.

### 0.2 Installer les dépendances ###

Ajoute dans ton `pyproject.toml` via `uv add` :

```
langgraph
langchain
langchain-community
langchain-ollama
fastapi
uvicorn[standard]
streamlit
faiss-cpu
supabase
langfuse
python-dotenv
httpx
pydantic
pytest
pytest-cov
loguru
pyjwt
passlib
rapidfuzz
```

Ta stack d'inférence : `qwen2.5:7b` (génération/raisonnement) et `nomic-embed-text` (embeddings), tous deux servis en local via Ollama (`ollama pull qwen2.5:7b` et `ollama pull nomic-embed-text`).

### 0.3 Activer le support vectoriel sur Supabase ###

Le schéma actuel de ta base (issu de la Partie 1) est purement relationnel : il n'a pas de colonne vectorielle. Avant d'attaquer le RAG, prépare Supabase :

- Active l'extension `pgvector` dans le projet Supabase (Database → Extensions).
- Ajoute une colonne d'embeddings sur la table `FILM` (ou crée une table dédiée `FILM_EMBEDDING` liée par `id_film`), dimensionnée à 768 (dimension native de `nomic-embed-text` — vérifie-la empiriquement avant de figer quoi que ce soit).
- Crée un index de similarité (ivfflat ou hnsw selon la version de pgvector disponible) et prévois la fonction/requête de recherche par distance cosinus.

Cette colonne sera peuplée en Phase 1 et exploitée par l'outil `find_similar_horror_movies`.

### 0.4 UI Streamlit : thème et configuration ###

Crée le fichier `.streamlit/config.toml` à la racine :

```
[theme]
primaryColor = "#8b0000"
backgroundColor = "#111111"
secondaryBackgroundColor = "#1b1f24"
textColor = "#e2e8f0"
font = "sans serif"
```

Committe ce fichier sur Git : c'est ce qui garantit le thème sombre chez tous les utilisateurs du dépôt.

### 0.5 Créer les outils annexes ###

Dans `src/tools/horror_tools.py`, prépare les deux outils "purs" (pas d'accès aux données) :

- `calculate_movie_age(year: int) -> int` : calcule l'âge du film par rapport à l'année actuelle.
- `horror_survival_simulator(synopsis: str, user_context: str) -> str` : simulateur ludique de chances de survie dans le scénario du film.

Ces deux outils seront rattachés à l'Agent de Narration en Phase 3.

---

## Phase 1 : La Couche Données & Vectorielle (FAISS + Supabase) ##

Tes données Gold sont dans Supabase (7392 films). Il faut les rendre exploitables par le RAG, sous forme vectorielle et sous forme structurée.

### 1.1 Générer l'index FAISS depuis Supabase ###

Crée un script `data/build_faiss_index.py` :

1. **Source** : interroge directement Supabase (`SELECT id_film, titre, annee_sortie, synopsis, tagline FROM FILM`) plutôt que le JSON Gold brut — cela garantit que chaque vecteur FAISS porte le vrai `id_film`, réutilisable ensuite par les outils SQL et pgvector.
2. **Contenu à indexer par film** : construis un texte enrichi en concaténant titre + tagline + synopsis + genres. Les synopsis de ton dataset sont courts (quelques centaines de caractères en moyenne) : inutile de faire un découpage mécanique en chunks avec chevauchement — un chunk = un film suffit dans l'immense majorité des cas.
3. **Cas des synopsis vides** : prévois un fallback (utiliser uniquement la tagline, ou exclure le film avec un log explicite) plutôt qu'un plantage du script sur les quelques films concernés.
4. **Préfixe d'embedding** : ajoute le préfixe `"search_document: "` devant chaque texte avant de l'embedder — c'est le format attendu par `nomic-embed-text` pour de bons résultats de recherche.
5. **Embedding** : vectorise avec `nomic-embed-text` via Ollama. Vérifie la dimension réelle retournée (`len(embedding)`, normalement 768) avant de créer l'index FAISS.
6. **Index** : stocke dans `data/faiss_index/horror_index.faiss` + `metadata.pkl` (association position vectorielle → `id_film`, titre, année, source).

    | Fichier | Type | Contenu exact | Taille approximative |
    |---|---|---|---|
    | `horror_index.faiss` | Binaire FAISS | La structure d'index + tous les vecteurs 768-dimensionnels des films. C'est le "cerveau numérique" qui permet la recherche ultra-rapide par similarité. | Quelques dizaines de Mo (dépend du nombre de films) |
    | `metadata.pkl` | Pickle Python | Une liste ordonnée Python : `[{"id_film": 1, "titre": "...", "annee_sortie": 1973, "source": "supabase"}, ...]`. C'est le **pont** entre la position du vecteur dans FAISS et les vraies données SQL. | Quelques Ko |

    data/faiss_index/ sera créé automatiquement par build_faiss_index.py à son exécution. Il contiendra ces deux fichiers et rien d'autre.

    Pourquoi séparer les deux ?  
    FAISS stocke superbement les matrices de nombres, mais il ne sait pas stocker des objets Python complexes. Le .pkl sert donc de dictionnaire de correspondance : quand FAISS te dit "le vecteur le plus proche est à l'index 42", tu vas chercher metadata[42] pour retrouver le id_film et le titre.
    Ces fichiers sont des artefacts lourds et régénérables : ils ne doivent jamais être poussés sur GitHub.

Conseil : fais-en un script one-shot (relancé seulement si le dataset change). Une fois généré, l'index est chargé en mémoire par l'API au démarrage.

### 1.2 Développer src/tools/rag_tool.py ###

- `search_local_horror_lore(query: str, top_k: int = 3) -> list[dict]` : préfixe la requête avec `"search_query: "`, charge l'index FAISS, embed la question, recherche les plus proches voisins, retourne les chunks + métadonnées (titre, année, source).
- `query_movie_metadata(...)` : requêtes SQL **paramétrées** sur Supabase (jamais générées par le LLM) pour récupérer réalisateur, année, genre, note moyenne, casting.
- `find_similar_horror_movies(id_film: int, k: int = 5) -> list[dict]` : recherche par similarité cosinus via pgvector (nécessite la colonne créée en 0.3).
- Optionnel : une fonction de correction fuzzy (distance de Levenshtein, via `rapidfuzz`) pour corriger les titres mal orthographiés saisis par l'utilisateur avant la recherche.

### 1.3 Développer src/tools/scraper_tool.py ###

- `extract_wikipedia_synopsis(movie_title: str) -> str` : scraping (BeautifulSoup/Requests) pour récupérer un synopsis Wikipédia.
- `enrich_from_web(movie_title: str) -> str` : appelle `extract_wikipedia_synopsis` et retourne un texte brut d'enrichissement, prêt à être injecté dans le state.

---

## Phase 2 : Le State et la Mémoire Commune ##

Le cœur de LangGraph est le State partagé entre les 3 agents.

### 2.1 Définir le schéma State ###

Dans `src/models/state.py`, définis un `AgentState` (TypedDict ou Pydantic) contenant :

- `messages` : historique de conversation (accumulé, pas écrasé).
- `query` : question de l'utilisateur.
- `rag_results` : résultats FAISS + SQL.
- `scraped_data` : résultat de l'enrichissement web.
- `needs_enrichment` : booléen décidé par le routeur — décide si tu le gardes pour la traçabilité (logs/tests) ou si tu le recalcules à la volée depuis `rag_results` ; documente ton choix dans le code.
- `final_answer` : sortie de l'Agent de Narration.
- `metadata` : infos annexes (films trouvés, sources utilisées, chemin emprunté par le graphe).

Décide aussi où vivent les **sources** que l'API devra retourner (`ChatResponse.sources`) : soit un champ dédié rempli par `narration_node`, soit un calcul à la volée à partir de `metadata` côté API.

### 2.2 Configurer la persistance (Checkpoint) ###

Utilise `MemorySaver` de LangGraph pour la persistance en mémoire du MVP. Cela permet à chaque thread/conversation de conserver son contexte. La migration vers un checkpointer persistant (SQLite/Postgres) n'est nécessaire qu'à partir du Bloc Industrialisation (Phase 7) — inutile de t'en soucier maintenant.

---

## Phase 3 : Construction du Graphe Multi-Agent (Peer-to-Peer) ##

Rappel : pas de superviseur central. Le routeur est une fonction d'aiguillage (edge conditionnelle) écrite en Python déterministe, jamais un appel LLM.

### 3.1 Node 1 : L'Agent RAG (rag_node) ###

Dans `src/graph/nodes.py` :

- Reçoit `state`, extrait `state["query"]`.
- Appelle **à la fois** `search_local_horror_lore` (vectoriel) **et** `query_movie_metadata` (structuré) — l'agent doit interroger le savoir structuré ET vectoriel, pas seulement FAISS.
- Écrit les résultats dans `state["rag_results"]` (+ `metadata`).
- Ajoute un `AIMessage` qui résume ce qui a été trouvé (pas la donnée brute).

### 3.2 Le Router (router.py) ###

Fonction `route_after_rag(state: AgentState) -> str` :

- Analyse la qualité/quantité de `state["rag_results"]`.
- Définis un seuil concret et documenté : calibre empiriquement sur quelques requêtes tests ce qu'est "un bon score de distance" FAISS.
- Ajoute un second signal de bascule : si `query_movie_metadata` ne trouve aucun film correspondant, bascule vers `"scraper"` même si FAISS a renvoyé quelque chose.
- Règle : si résultats suffisants et pertinents → retourne `"narration"`. Sinon → retourne `"scraper"`.
- Edge conditionnelle dans le graphe reliant `rag_node` à `narration_node` ou `scraper_node` selon la valeur retournée.

### 3.3 Node 2 : L'Agent Scraper (scraper_node) ###

- Se déclenche uniquement si le routeur a renvoyé `"scraper"`.
- Lit `state["query"]` ou `state["rag_results"]` pour identifier le film ambigu ou incomplet.
- Appelle `enrich_from_web(...)`.
- Écrit dans `state["scraped_data"]`.
- Edge fixe : retourne toujours vers `narration_node`.

### 3.4 Node 3 : L'Agent Narration (narration_node) ###

- **Isolation de contexte stricte** : le nœud lit uniquement `state["rag_results"]` et `state["scraped_data"]` (champs structurés) — jamais l'historique brut `state["messages"]` produit par les autres agents. C'est le principe "anti-collision de tokens" : l'Écrivain Gothique ne doit jamais voir la plomberie technique du RAG/Scraper.
- Construit un prompt système ultra-spécialisé ("Tu es HorRAGor, chroniqueur de cinéma d'horreur... Base-toi UNIQUEMENT sur les données fournies ci-dessous...") avec consigne stricte anti-hallucination.
- Outils attachés : `calculate_movie_age`, `horror_survival_simulator`, et `find_similar_horror_movies` si la question porte sur des recommandations.
- Écrit la réponse finale dans `state["final_answer"]` et les sources associées.
- Ajoute le message final à l'historique.

### 3.5 Câblage et Compilation (pipeline.py) ###

Dans `src/graph/pipeline.py` :

- Instancie `StateGraph(AgentState)`.
- Enregistre les 3 nœuds (`rag_node`, `scraper_node`, `narration_node`).
- Définis `rag_node` comme point d'entrée.
- Ajoute l'edge conditionnelle `rag_node` → (`scraper_node` | `narration_node`) via `route_after_rag`.
- Ajoute l'edge fixe `scraper_node` → `narration_node`.
- Ajoute l'edge fixe `narration_node` → `END`.
- Compile le graphe avec le checkpointer (`memory`).

### 3.6 Test local du graphe ###

Avant de toucher à FastAPI :

- Teste une invocation complète du graphe avec une question simple, vérifie que `final_answer` est cohérent.
- Teste `route_after_rag` **isolément**, avec des `state` fabriqués à la main (résultats riches vs résultats vides) — ça valide la logique du routeur sans dépendre de FAISS ni du LLM.

---

## Phase 4 : API Backend (FastAPI + Uvicorn) ##

### 4.1 Serveur FastAPI (src/main.py) ###

- **Lifespan** : charge le graphe compilé au démarrage (évite de recompiler à chaque requête).
- **Modèles Pydantic** : `ChatRequest` (message, thread_id) et `ChatResponse` (response, sources).
- **Endpoint POST /chat** :
  1. Crée le state initial avec la query et l'historique (via `thread_id`).
  2. Appelle `graph.invoke(..., config={"configurable": {"thread_id": ...}})`.
  3. Calcule les `sources` à partir de `rag_results`/`metadata` (décidé en Phase 2.1) et précise si le web a été utilisé.
  4. Retourne `final_answer` + `sources`.
  5. Prévoit une gestion d'erreur propre si le graphe lève une exception (réponse HTTP correcte plutôt qu'un crash).

### 4.2 Gestion de l'historique ###

Utilise `thread_id` pour différencier les conversations. `MemorySaver` gère l'état en RAM pour l'instant.

### 4.3 Endpoint de santé ###

Ajoute dès maintenant un endpoint `GET /health` minimal : inutile tout de suite, mais Uptime Kuma en aura besoin en Phase 8 — autant l'avoir sous la main.

---

## Phase 5 : Frontend Streamlit (Chatbot) ##

### 5.1 Interface Chat (app_frontend.py) ###

- `st.chat_input` pour la saisie utilisateur.
- `st.chat_message` pour l'affichage bulle par bulle (historique).
- Un spinner (`st.spinner("L'entité HorRAGor consulte les archives...")`) pendant l'appel à l'API.

### 5.2 Communication avec l'API ###

- Utilise `httpx` pour appeler `http://localhost:8000/chat`.
- Stocke le `thread_id` dans `st.session_state` pour conserver la conversation.
- Affiche les sources si elles existent (petit encart en gris sous la bulle du bot).
- Optionnel : affiche un badge si le chemin Scraper a été emprunté (ex. "🔍 Enrichi via le Web"), à partir des métadonnées transmises par l'API.

### 5.3 Sécurisation minimale ###

Envoie déjà un header `X-API-Key` en placeholder pour préparer le terrain (la vraie auth arrive en Phase 7).

---

## Phase 6 : Extraction de la Couche Données (API dédiée) ##

**Objectif** : la base doit être encapsulée derrière sa propre API, strictement inaccessible depuis l'extérieur du cluster. Tant que `rag_tool.py` appelle Supabase directement, cette exigence n'est pas respectée.

### 6.1 Créer le service data-api ###

Crée un service FastAPI minimal séparé (`data-api/`) qui encapsule tout l'accès Supabase : endpoints internes type `GET /films/search`, `GET /films/{id}`, `POST /films/similar` (exécute la recherche pgvector).

### 6.2 Migrer rag_tool.py vers ce service ###

`rag_tool.py` (côté API Intelligence) appelle désormais `data-api` via `httpx` au lieu d'interroger Supabase en direct. Les identifiants Supabase ne vivent plus que dans l'environnement de `data-api`.

### 6.3 FAISS reste côté Intelligence ###

L'index FAISS (local, en RAM) reste dans l'API Intelligence : ce n'est pas un accès "base de données" au sens du sujet, inutile de le faire transiter par `data-api`.

### 6.4 Étendre la documentation ###

Ajoute ce nouveau service au périmètre de la documentation Sphinx (Phase 9).

---

## Phase 7 : Conteneurisation, Auth & Réseau ##

### 7.1 Docker & Docker Compose ###

Crée 3 conteneurs + un réseau privé :

- `data-api` : aucun port publié vers l'hôte, joignable uniquement par `intelligence-api` ; seule à détenir les identifiants Supabase.
- `intelligence-api` : joignable par `frontend` via le réseau interne ; en développement tu peux publier son port pour tester `/docs`, mais en configuration sécurisée ne l'expose pas.
- `frontend` : seul service avec un port publié vers l'hôte (`8501`).

Configure un réseau Docker de type `bridge` dédié (`horragor_net`) et rattache les 3 services dessus.

### 7.2 Authentification par Refresh Tokens ###

Implémente un système simple entre Front et API :

- **Login** : `POST /auth/login` → retourne un `access_token` (JWT, court) et un `refresh_token` (long).
- **Intercepteur Streamlit** : stocke les tokens, rafraîchit automatiquement si l'access_token expire.
- **Middleware FastAPI** : valide le JWT sur `/chat` et `/auth/refresh`.

Pour un projet de formation, un utilisateur unique défini via variables d'environnement suffit — pas besoin d'une vraie gestion multi-utilisateurs.

### 7.3 Communication chiffrée ###

Sécurise la communication Streamlit → API Intelligence : un certificat auto-signé ou un reverse proxy TLS local (Traefik/Nginx) suffit pour la démo. Documente que la vraie production utiliserait un certificat valide.

---

## Phase 8 : Monitoring avec Langfuse, Loguru et la stack Prometheus ##

### 8.1 Langfuse ###

- Crée un compte/projet Langfuse.
- Dans `src/config.py`, renseigne `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
- Branche le `CallbackHandler` Langfuse dans l'invocation du graphe.
- Vérifie dans l'interface Langfuse que tu retrouves les steps (RAG, Scraper, Narration), les tokens consommés et les latences.

### 8.2 Loguru ###

Ajoute des logs structurés de bout en bout sur les 3 composants : requêtes reçues, décision du routeur, appels d'outils, erreurs.

### 8.3 Prometheus + Grafana + Uptime Kuma ###

- Prometheus collecte des métriques sur les deux API (requêtes, latences, erreurs).
- Grafana affiche des dashboards à partir de ces métriques.
- Uptime Kuma surveille la disponibilité des 3 composants, en s'appuyant sur `GET /health` (Phase 4.3).
- Ajoute ces services à ton `docker-compose.yml` (ou à un compose dédié "monitoring").

---

## Phase 9 : Documentation Sphinx ##

### 9.1 Setup Sphinx ###

Initialise Sphinx dans `docs/`, installe le thème RTD et `sphinxcontrib-openapi`.

### 9.2 Contenu obligatoire ###

1. **Doc API automatisée** : pour les **deux** API (Données + Intelligence), via `sphinxcontrib-openapi` ou autodoc.
2. **Schéma relationnel** : documente la base Supabase (tables, relations, clés primaires), y compris la colonne vectorielle ajoutée en Phase 0.3.
3. **Cartographie du graphe** : génère un schéma des nodes, du router et des edges conditionnelles via `graph.get_graph().draw_mermaid_png()` (pas besoin de Graphviz) ou `draw_png()` si Graphviz est installé.
4. **Guide d'installation** : Ollama (avec les deux modèles `qwen2.5:7b` et `nomic-embed-text`), FAISS, variables d'environnement, lancement Docker Compose.

### 9.3 Build ###

Génère la documentation HTML finale.

---

## Phase 10 : Qualité, Tests & Gouvernance ##

### 10.1 Tests unitaires ###

- Teste chaque node indépendamment (mock des outils).
- Teste le router avec des states variés (résultats riches vs résultats vides).
- Teste les endpoints de `data-api` avec la BDD mockée.

### 10.2 Tests d'intégration ###

- Lance l'API, envoie une requête et vérifie que le flux RAG → Narration ou RAG → Scraper → Narration fonctionne.
- Teste le flux d'authentification complet (login / refresh / accès protégé).

### 10.3 Couverture de tests ###

Vise une couverture ≥ 80 % sur les deux API et l'UI (`pytest-cov`).

### 10.4 Pipeline CI/CD ###

Mets en place un pipeline (ex. GitHub Actions) qui lance : lint, tests + couverture, build des images Docker, à chaque push/PR.

### 10.5 GitHub Issues ###

Crée un template d'issue dans `.github/ISSUE_TEMPLATE/bug_report.md` avec les champs : nœud concerné (RAG / Scraper / Narration), requête test, résultat attendu, résultat obtenu, logs Langfuse si applicable. Adopte la règle : chaque anomalie détectée = un ticket archivé avant correction.

---

## ✅ Checklist de validation finale ##

- [ ] Extension pgvector activée et colonne vectorielle ajoutée sur Supabase
- [ ] Index FAISS de lore généré depuis Supabase (dimension vérifiée empiriquement) et fonctionnel
- [ ] Préfixes `search_document:` / `search_query:` appliqués systématiquement
- [ ] `rag_node` interroge à la fois le structuré (SQL) et le vectoriel (FAISS)
- [ ] Graphe compilé avec 3 nodes + router conditionnel déterministe, testé isolément
- [ ] Les 5 outils de la Partie 2 sont développés et rattachés aux bons nœuds
- [ ] `narration_node` ne lit jamais l'historique brut des autres nœuds (isolation de contexte)
- [ ] API Données dédiée : aucun accès direct à Supabase depuis l'API Intelligence
- [ ] FastAPI Intelligence expose `/chat` et `/health`, gère `thread_id`
- [ ] Streamlit communique avec l'API via le réseau interne (Docker), en HTTPS
- [ ] Thème sombre appliqué via `.streamlit/config.toml` et commité
- [ ] Auth par refresh tokens opérationnelle
- [ ] Langfuse trace les exécutions
- [ ] Loguru journalise les 3 composants
- [ ] Prometheus + Grafana + Uptime Kuma monitorent les 3 composants
- [ ] Sphinx génère la doc (2 API, base de données, graphe, installation)
- [ ] Couverture de tests ≥ 80 % (2 API + UI)
- [ ] Pipeline CI/CD opérationnel
- [ ] GitHub Issues template créé

---

## Récapitulatif : outils et nœud d'accueil ##

| Outil | Fichier | Nœud consommateur |
|---|---|---|
| `search_local_horror_lore` | `rag_tool.py` | `rag_node` |
| `query_movie_metadata` | `rag_tool.py` | `rag_node` |
| `find_similar_horror_movies` | `rag_tool.py` | `narration_node` |
| `extract_wikipedia_synopsis` / `enrich_from_web` | `scraper_tool.py` | `scraper_node` |
| `calculate_movie_age` | `horror_tools.py` | `narration_node` |
| `horror_survival_simulator` | `horror_tools.py` | `narration_node` |

## Repères modèles Ollama ##

| Modèle | Rôle | Point d'attention |
|---|---|---|
| `qwen2.5:7b` | Génération/raisonnement (narration, éventuellement rag/scraper) | Tool-calling local parfois instable → prévoir un parsing JSON de secours |
| `nomic-embed-text` | Embeddings (FAISS + pgvector) | 768 dimensions, contexte natif 2048 tokens, préfixes `search_document:` / `search_query:` obligatoires |

## Bonus (optionnel, à traiter seulement une fois tout le reste validé) ##

- Un nœud "Juge" après `narration_node`, qui vérifie que le texte généré colle bien à `rag_results`/`scraped_data` (anti-hallucination).
- Un nœud "Guardrail" avant `rag_node`, qui filtre les injections de prompt ou les requêtes vides/malformées.
