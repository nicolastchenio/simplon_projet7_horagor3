# Phase 0 :Préparation & Rattrapage des éléments de la Partie 2 #
## 0.2 Installer les dépendances + .gitignore##
1. La commande d'installation
    ```
    uv init

    # Core IA / Graphe
    uv add langgraph langchain langchain-community langchain-ollama

    # API & Web
    uv add fastapi "uvicorn[standard]" streamlit httpx

    # Données / Vectoriel / Auth
    uv add faiss-cpu supabase python-dotenv pydantic pyjwt passlib rapidfuzz

    # Monitoring / Tests
    uv add langfuse pytest pytest-cov loguru
    ```

2. Vérification rapide
Une fois terminé, vérifie que ton pyproject.toml contient bien les dépendances et que l'environnement virtuel est à jour :
    ```
    # Voir les deps installées
    uv pip list | grep -E "langgraph|ollama|fastapi|streamlit|faiss"

    # Vérifier que le lockfile est synchronisé
    uv sync
    ```
3. Prérequis système Ollama (hors uv)
Ces dépendances Python n'incluent pas les modèles eux-mêmes. Vérifie que tu as bien Ollama installé au niveau système (pas dans l'environnement Python), puis tire les modèles :
    ```
    # Dans un terminal classique (pas dans venv)
    ollama pull qwen2.5:7b
    ollama pull nomic-embed-text

    # Vérifier qu'ils sont présents
    ollama list
    ```
4. creation du .gitignore

## 0.3 Activer le support vectoriel sur Supabase ##


| Étape | Ce qu'on fait | Pourquoi |
|-------|---------------|----------|
| **1** | Activer l'extension `pgvector` | Pour que Supabase accepte de stocker des vecteurs |
| **2** | Ajouter une colonne `embedding vector(768)` à la table `FILM` | Pour stocker l'empreinte numérique de chaque film |
| **3** | Créer un **index** sur cette colonne | Pour que la recherche soit rapide (sinon ça prendrait 10 secondes à chaque question) |
| **4** | Créer une **fonction** `find_similar_movies` | Pour appeler facilement depuis Python plus tard |

### Etape 1 Activer pgvector ###

Dans le projet Supabase :
1) Aller dans SQL Editor (menu de gauche, icône </>)
2) Cliquer sur "New query" (ou un bouton "+" selon la version).
On a maintenant une page blanche avec une zone de texte. C'est ici qu'on écrit du SQL.
3) Coller la commande d'activation :
   ```CREATE EXTENSION IF NOT EXISTS vector; ```
4) Cliquer sur le bouton vert "Run" (en bas à droite de la zone SQL).

Vérification
Remplace le texte par :
```
SELECT * FROM pg_extension WHERE extname = 'vector';
```
Puis Run → on doit voir 1 ligne apparaître avec vector dans la colonne extname.

### Etape 2 Ajouter la colonne embedding à ta table FILM ###

C'est cette colonne embedding qui va stocker cette version mathématique : une liste de 768 nombres. Parce que le modèle nomic-embed-text (que tu as choisi et qui est dans ton plan) sort toujours des vecteurs de 768 nombres. Peu importe si le synopsis fait 10 mots ou 500 mots, après passage dans ce modèle, ça devient une liste de 768 nombres.

1. Retourner dans le SQL Editor de ton projet Supabase.
2. Cliquer sur "New query" (ou le bouton +).
3. Efface le texte précédent pour partir d'une page blanche.
4. Coller cette commande :
    ```
    ALTER TABLE film
    ADD COLUMN IF NOT EXISTS embedding vector(768);
    ```
5. Cliquer sur le bouton "Run".

Vérifier que la colonne existe bien :  
Efface le texte et colle cette commande de vérification :
```
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'film' 
AND column_name = 'embedding';
```
Puis Run.

Ce que l'on doit observer :
Dans le menu latéral gauche de Supabase dans "Table Editor" sur ta table film une nouvelle colonne vide tout à droite appelée embedding.

Elle est vide (NULL dans toutes les lignes). C'est totalement normal. On la remplira plus tard avec les vrais nombres générés par nomic-embed-text (ce sera la Phase 1 de ton plan).

### Etape 3 Créer un index de similarité sur la colonne embedding ###

Sans index, quand tu demanderas à PostgreSQL : "Donne-moi les films les plus proches de cette question", il devra calculer la distance cosinus entre ta question et chaque film, un par un. Ce sera très lent (plusieurs secondes voire pire). L'index, c'est comme un sommaire intelligent : il organise les vecteurs dans l'espace mathématique pour que PostgreSQL saute directement aux bons candidats sans tout calculer.

Dans pgvector, il y a plusieurs méthodes. Pour un projet pédagogique comme le tien, on va utiliser HNSW (Hierarchical Navigable Small World) :
- C'est le plus moderne et le plus utilisé aujourd'hui.
- Il est rapide et précis pour la recherche par similarité.
- Il fonctionne très bien avec des vecteurs de 768 dimensions.

1) Dans ton SQL Editor, clique sur "New query" et efface tout.
2) Coller cette commande : 
    ```
    CREATE INDEX IF NOT EXISTS idx_film_embedding_cosine 
    ON film 
    USING hnsw (embedding vector_cosine_ops);
    ```

    note perso : on met film en miniscule car ecrit comme cela dans supabase sinon ecrire FILM si tout en majuscule dans supabase
3) Cliquer sur "Run".
Supabase met parfois un petit moment à créer cet index (quelques secondes), car il prépare la structure mathématique. C'est normal.

4) Vérifier que l'index existe, Effacer le texte et colle cette commande :
```
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'film' 
AND indexname = 'idx_film_embedding_cosine';
```

### Etape 4 Créer la fonction SQL find_similar_movies ###

En créant une fonction sql plutot qu juste une requete python 
- La recherche cosinus avec pgvector utilise une syntaxe spécifique (<=> pour la distance cosinus).
- En l'encapsulant dans une fonction, ton code Python n'aura qu'à faire : supabase.rpc("find_similar_movies", {...}).
- C'est plus propre, plus rapide, et ça centralise la logique métier dans la base.

1) Dans ton SQL Editor, clique sur "New query", efface tout.
2) Coller cette commande :
    ```
    CREATE OR REPLACE FUNCTION find_similar_movies(
        query_embedding VECTOR(768),
        match_count INT DEFAULT 5
    )
    RETURNS TABLE (
        id_film INTEGER,
        titre VARCHAR,
        annee_sortie INTEGER,
        langue_originale VARCHAR,
        synopsis TEXT,
        similarity FLOAT
    )
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN QUERY
        SELECT
            f.id_film,
            f.titre,
            f.annee_sortie,
            f.langue_originale,
            f.synopsis,
            -- cosine distance (0 = identique, 2 = opposé)
            -- on transforme en score de similarité entre -1 et 1
            1 - (f.embedding <=> query_embedding) AS similarity
        FROM film f
        WHERE f.embedding IS NOT NULL
        ORDER BY f.embedding <=> query_embedding ASC
        LIMIT match_count;
    END;
    $$;
    ```
3) Cliquer sur "Run".
4) Vérifier que la fonction existe :
    ```
    SELECT proname, proargnames, prosrc 
    FROM pg_proc 
    WHERE proname = 'find_similar_movies';
    ```
    Puis Run
    Si c'est réussi, on doit voir une ligne avec find_similar_movies et ses arguments (query_embedding, match_count).
5) Vérifier que la fonction est "appelable" (test minimal)  
Comme aucun film n'a encore d'embedding de rempli, elle ne retournera aucun résultat pour l'instant, mais on peut tester qu'elle s'exécute sans erreur.
    ```
    SELECT * FROM find_similar_movies(
        ARRAY_FILL(0.0::real, ARRAY[768])::vector(768),
        1
    );
    ```
    Résultat attendu :Aucune ligne retournée (normal, aucun film n'a encore d'embedding rempli), mais pas d'erreur rouge. Tu dois juste voir les en-têtes de colonnes apparaître et un message du type Success, no rows returned.

## 0.4 UI Streamlit : thème et configuration streamlit ##

Créer le fichier `.streamlit/config.toml` à la racine

## 0.5 Créer les outils annexes ##

CréeR le fichier src/tools/horror_tools.py avec :
- calculate_movie_age => Outil utilitaire simple (année actuelle − année du film).
- horror_survival_simulator => Outil ludique purement algorithmique (mots-clés + scoring + random).

# Phase 1 : La Couche Données & Vectorielle (FAISS + Supabase) #

## 1.1 Générer l'index FAISS depuis Supabase ##

1) rajouter `uv add psycopg2-binary ` pour pouvoir utiiser une connexion a supabase via => DATABASE_URL="postgresql://postgres.fddfdfdfkekrrerffdf:[YOUR-PASSWORD]@aws-0-eu-west-3.pooler.supabase.com:6543/postgres" plutot que une api
2) creer le fichier " data/build_faiss_index.py"

3) Vérification avant de lancer
    ```
    Ollama est démarré et le modèle est présent :
    ollama pull nomic-embed-text
    ollama list  # doit afficher nomic-embed-text
    ```
4) Lance le script (depuis la racine) :
    ```
    uv run python data/build_faiss_index.py
    ```

    Résultat attendu :
    - Création locale de data/faiss_index/horror_index.faiss
    - Création locale de data/faiss_index/metadata.pkl
    - Aucun fichier binaire ne doit apparaître dans git status

## 1.2 Développer src/tools/rag_tool.py ##

L'idée est de centraliser tous les outils de recherche utilisés par l'agent : FAISS locale, SQL structuré, pgvector et (plus tard) la correction fuzzy.

### etape 1 : search_local_horror_lore(...)

1) _load_faiss_resources()  
   L'index FAISS fait plusieurs dizaines de méga-octets. On ne veut pas le relire depuis le disque à chaque question de l'utilisateur. Le chargeur _load_faiss_resources() garde l'index, les métadonnées et l'embedder en mémoire dès le premier appel.
2) search_local_horror_lore(...)  
   C'est la fonction principale du RAG. Elle interroge l'index FAISS.
    Points importants :
    - On préfixe la requête par "search_query: " car c'est le format d'instruction attendu par nomic-embed-text pour distinguer une question d'un document.
    - On normalise L2 le vecteur question avant la recherche, car notre index utilise InnerProduct sur des vecteurs déjà normalisés : le résultat est mathématiquement équivalent à une similarité cosinus.
    - Le score retourné sera donc un nombre entre 0 et 1 (1 = parfait).

    Note sur le champ chunk : dans notre metadata.pkl actuel, nous n'avons pas stocké le texte complet indexé (seulement id_film, titre, annee_sortie, genres). La fonction retourne donc un chunk partiellement reconstruit depuis les métadonnées. Si tu veux le texte intégral, il faudra régénérer l'index en ajoutant "text" dans documents_meta lors du build_faiss_index.py.

Vérification intermédiaire:
Créer un fichier temporaire "test_rag.py" à la racine du projet :
```
from src.tools.rag_tool import search_local_horror_lore

if __name__ == "__main__":
    res = search_local_horror_lore("poupée maléfique", top_k=3)
    for r in res:
        print(f"{r['score']:.4f} | {r['metadata']['titre']} ({r['metadata']['annee']}) | {r['chunk'][:60]}...")
```
Puis exécute :
```
uv run python test_rag.py
```

### etape 2 — query_movie_metadata(...) : requêtes SQL paramétrées ###
Au lieu de laisser le LLM écrire du SQL (risque d’injection et d’hallucination de schéma), on expose une fonction Python structurée qui :
1) Reçoit des arguments typés (titre, id_film, top_k).
2) Exécute une requête SQL prédéfinie et paramétrée (%s / %(nom)s).
3) Agrège en une seule passe les genres et le casting via STRING_AGG.
4) Retourne une liste de dictionnaires propres.

Règle d’or : le LLM ne voit jamais le SQL. Il appelle juste query_movie_metadata(titre="Conjuring").

1) ajouter ces lignes de codes en haut du fichier 
   ```
    from dotenv import load_dotenv

    # ── Définition de la racine du projet ──────────────────────────────
    # __file__ = src/tools/rag_tool.py  →  remonte 3 niveaux = racine
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

    # Charge le .env situé à la racine (avant toute utilisation d'os.environ)
    load_dotenv(PROJECT_ROOT / ".env")
    ```
2) ajout des 2 functions  _get_db_connection() query_movie_metadata(...)
3) test rapide en remplacant le contenu de ton test_rag.py par ceci :
    ```
    from src.tools.rag_tool import query_movie_metadata

    if __name__ == "__main__":
    # 1. Recherche par fragment de titre
    print("=== Par titre (Conjuring) ===")
    for f in query_movie_metadata(titre="Conjuring", top_k=2):
        print(f"{f['titre']} ({f['annee_sortie']}) — {f['realisateur']}")
        print(f"   Genres : {f['genres']}")
        print(f"   Casting : {f['casting'][:80]}...")
        print()

    # 2. Recherche par ID exact
    print("=== Par ID ===")
    film = query_movie_metadata(id_film=1, top_k=1)
    if film:
        print(film[0])
    ```
    ou autre test plus complet 

    ```
    from src.tools.rag_tool import query_movie_metadata


    def verifier_proprete(films, contexte):
        """Retourne une liste d'erreurs si des doublons ou 'Inconnu' subsistent."""
        erreurs = []
        seen = set()

        for f in films:
            # Anti-doublon
            cle = (str(f.get("titre") or "").strip().lower(), f.get("annee_sortie"))
            if cle in seen:
                erreurs.append(f"  ❌ [{contexte}] Doublon : {f.get('titre')} ({f.get('annee_sortie')})")
            seen.add(cle)

            # Anti-"Inconnu" ou None
            real = f.get("realisateur")
            if real is None:
                erreurs.append(f"  ❌ [{contexte}] Réalisateur = None pour ID {f.get('id_film')}")
            elif str(real).strip().lower() == "inconnu":
                erreurs.append(f"  ❌ [{contexte}] Réalisateur toujours 'Inconnu' pour ID {f.get('id_film')}")

        return erreurs


    if __name__ == "__main__":
        print("=" * 70)
        print("TESTS GÉNÉRIQUES — RAG TOOL")
        print("=" * 70)
        all_ok = True

        # ============================================================
        # TEST 1 : Recherche par titre (vérifie dédoublonnage + top_k)
        # ============================================================
        print("\n▶ TEST 1 : Recherche par titre 'Conjuring' (top_k=5)")
        films = query_movie_metadata(titre="Conjuring", top_k=5)

        if not films:
            print("  ⚠️  Aucun résultat (ce titre n'existe peut-être pas dans la base).")
            all_ok = False
        else:
            print(f"  {len(films)} film(s) retourné(s) :")
            for f in films:
                real = f.get("realisateur", "Non spécifié")
                print(f"     • ID {f['id_film']} | {f['titre']} ({f['annee_sortie']}) — {real}")

            errs = verifier_proprete(films, "TEST 1")
            if errs:
                for e in errs:
                    print(e)
                all_ok = False
            else:
                print("  ✅ Pas de doublon, pas de 'Inconnu', top_k respecté.")

        # ============================================================
        # TEST 2 : Recherche par ID (dynamique, premier ID du TEST 1)
        # ============================================================
        print("\n▶ TEST 2 : Recherche par ID (dynamique)")
        if films:
            id_test = films[0]["id_film"]
            print(f"  Récupération de l'ID {id_test} depuis le TEST 1...")
            film_id = query_movie_metadata(id_film=id_test, top_k=1)

            if not film_id:
                print("  ❌ La recherche par ID a échoué.")
                all_ok = False
            else:
                f = film_id[0]
                real = f.get("realisateur", "Non spécifié")
                print(f"  → {f['titre']} ({f['annee_sortie']}) — Réalisateur : {real}")
                if real == "Inconnu" or real is None:
                    print("  ❌ Réalisateur 'Inconnu' ou None non masqué.")
                    all_ok = False
                else:
                    print("  ✅ Recherche par ID OK, données propres.")
        else:
            print("  ⏭️  Skippé (pas de film dans TEST 1 pour récupérer un ID).")

        # ============================================================
        # TEST 3 : Gestion gracieuse du vide (titre inexistant)
        # ============================================================
        print("\n▶ TEST 3 : Recherche d'un titre inexistant 'XYZ_NO_MOVIE'")
        vide = query_movie_metadata(titre="XYZ_NO_MOVIE", top_k=5)
        if not vide:
            print("  ✅ Aucun résultat — le vide est géré correctement.")
        else:
            print(f"  ⚠️  {len(vide)} résultat(s) inattendu(s) — la recherche est trop permissive ?")

        # ============================================================
        # TEST 4 : Recherche par titre partiel / court (robustesse)
        # ============================================================
        print("\n▶ TEST 4 : Recherche par titre partiel 'The' (top_k=3)")
        films_the = query_movie_metadata(titre="The", top_k=3)
        if not films_the:
            print("  ⚠️  Aucun résultat avec 'The' (pas de film anglophone ?).")
        else:
            print(f"  {len(films_the)} résultat(s) :")
            for f in films_the:
                print(f"     • {f['titre']} ({f['annee_sortie']})")
            errs = verifier_proprete(films_the, "TEST 4")
            if errs:
                for e in errs:
                    print(e)
                all_ok = False
            else:
                print("  ✅ Données propres.")

        # ============================================================
        # RÉCAPITULATIF
        # ============================================================
        print("\n" + "=" * 70)
        if all_ok:
            print("✅ TOUS LES TESTS PASSENT — RAG tool est robuste et prêt pour l'agent.")
        else:
            print("❌ CERTAINS TESTS ÉCHOUENT — Voir les détails ci-dessus.")
        print("=" * 70)
    ``` 

    puis executer la commande `uv run python test_rag.py `

### etape 3 — find_similar_horror_movies(...)

1) ajouter la function  find_similar_horror_movies(...)

2) injection des vecteurs dans pgvector qui n'a pas encore été jouée à l'étape 0.3 et que l'on doit donc faire maintenant
   - creer un script (scripts/faiss_to_pgvector.py)  pour copier directement les 7 392 vecteurs déjà calculés dans "horror_index.faiss" vers Supabase sans refaire tourner Ollama.
   - executer la commande ` uv run python scripts/faiss_to_pgvector.py `

3) Crée un test_similarity.py à la racine
    ```
    from src.tools.rag_tool import query_movie_metadata, find_similar_horror_movies
    if __name__ == "__main__":
        # ── On prend un film existant comme point d'ancrage ──
        films = query_movie_metadata(titre="Conjuring", top_k=1)
        if not films:
            print("Aucun film trouvé pour amorcer le test.")
        else:
            ref = films[0]
            print(f"Film référence : {ref['titre']} (ID {ref['id_film']})")
            print("=" * 50)

            try:
                voisins = find_similar_horror_movies(ref["id_film"], k=3)
                for v in voisins:
                    print(
                        f"• {v['titre']} ({v['annee_sortie']}) — "
                        f"sim={v['similarite']} | réal: {v['realisateur']}"
                    )
            except RuntimeError as e:
                print(f"⚠️ {e}")
    ```
4) executer la commande ` uv run python test_similarity.py `

### etape 4 — fuzzy_find_film(...)

interroge la base pour récupérer tous les titres, applique rapidfuzz.process.extractOne, et retourne le meilleur match avec son id_film.

1) installer ` uv add rapidfuzz `
2) creer la fonction fuzzy_find_film(...)
3) test d'utilisation dans test_similarity.py
    ```
    from src.tools.rag_tool import resolve_film, find_similar_horror_movies

        # Utilisateur tape avec une faute
        user_input = "conjurin heure du jugement"  # faute volontaire

        try:
            film_id = resolve_film(user_input, score_cutoff=75.0)
            print(f"Film identifié : ID {film_id}")
            
            voisins = find_similar_horror_movies(film_id, k=5)
            for v in voisins:
                print(f"• {v['titre']} ({v['annee_sortie']}) — sim={v['similarite']}")
        except RuntimeError as e:
        print(e)
    ```
4) executer la commande ` uv run python test_similarity.py `
5) creer le test "test_fuzzy.py"
   ```
   from src.tools.rag_tool import fuzzy_find_film, resolve_film

    tests = [
        "conjurin heure du jugement",
        "conjuring heure jugement",
        "Ordres du mal",
        "heure du jugement",
        "les dossiers warren",
        "exsorsiste",  # Exorciste ?
    ]

    for t in tests:
        res = fuzzy_find_film(t, score_cutoff=50.0)
        if res:
            print(f"« {t} » → « {res['titre']} » (score={res['score']}, id={res['id_film']})")
        else:
            print(f"« {t} » → AUCUN MATCH")
        print()
    ```
1) executer la commande ` uv run python test_fuzzy.py `

## 1.3 Développer src/tools/scraper_tool.py ##

L’objectif est simple : quand notre agent ne trouve pas assez de contexte narratif dans la base PostgreSQL (par exemple un synopsis trop court ou absent), il pourra aller chercher un texte de remplacement sur Wikipédia pour enrichir son state.

requests + BeautifulSoup plutôt que Selenium car Wikipédia est une page statique (pas de JavaScript indispensable pour lire un article).
Selenium est lourd et lent ; ici requests suffit amplement.
On garde Selenium sous le coude si plus tard tu dois scraper un site qui nécessite un rendu navigateur (Allociné par exemple).

Parser une page Wikipédia complète en HTML est très fragile : la structure interne de MediaWiki change souvent (balises imbriquées, div intermédiaires, liens [modifier], etc.).La solution professionnelle est d'utiliser l'API officielle MediaWiki : elle nous donne la liste exacte des sections d'un article, puis le contenu HTML isolé d'une seule section (par ex. Synopsis). Plus besoin de chercher le bon `<h2>` dans un arbre DOM complexe.

1) Installer "beautifulsoup4" => ` uv add beautifulsoup4 requests `
2) creer le fichier "scraper_tool.py"
3) Crée " test_scraper.py"  à la racine :
   
    ```
    from src.tools.scraper_tool import extract_wikipedia_synopsis, enrich_from_web

    if __name__ == "__main__":
        film = "Conjuring : Les Dossiers Warren"

        print("=== Test 1 : synopsis brut (800 premiers caractères) ===\n")
        synopsis = extract_wikipedia_synopsis(film)
        print(synopsis[:800] if synopsis else "❌ Rien trouvé")
        print("\n...\n")

        print("=== Test 2 : enrichissement formaté ===\n")
        enrichi = enrich_from_web(film)
        print(enrichi[:800] if enrichi else "❌ Rien trouvé")
        print("\n...\n")

        print("=== Test 3 : film inexistant ===\n")
        print(repr(enrich_from_web("FilmInexistantXYZ123")))

    ```

Pour executer le test =>  ` uv run python test_scraper.py `

# Phase 2 : Le State et la Mémoire Commune #

## 2.1 Définir le schéma State ##

=> creation du fichier "src\models\state.py"

Le cœur du système : AgentState, la mémoire commune que tous tes agents (RAG, Scraper, Narration) vont lire et modifier à chaque étape du graphe.

LangGraph est optimisé pour TypedDict car il fonctionne parfaitement avec le système de reducers (voir ci-dessous) et vérifie les types sans imposer la validation lourde de Pydantic à chaque transition. C’est plus léger et c’est le standard de la doc officielle.

Reducer : Annotated[list[BaseMessage], add_messages].  
add_messages (fourni par LangGraph) fusionne automatiquement les nouveaux messages avec l’historique déjà présent.

On crée un champ dédié sources dans AgentState, rempli par le narration_node à la fin.
- Cela évite à l’API FastAPI de deviner ou parser metadata pour reconstruire la réponse.
- Le contrat entre le graphe et l’API reste propre et explicite : le graphe sort un final_answer + un tableau sources prêt à être sérialisé en ChatResponse.sources.

| Champ | Qui l'écrit ? | Qui le lit ? |
|---|---|---|
| `messages` | Tous les nœuds (via reducer) | Tous les nœuds + API |
| `query` | API (entrée) | `rag_node`, `router` |
| `rag_results` | `rag_node` | `router`, `narration_node` |
| `scraped_data` | `scraper_node` | `narration_node` |
| `needs_enrichment` | `router` | Debug, tests, logs |
| `final_answer` | `narration_node` | API (réponse utilisateur) |
| `sources` | `narration_node` | API (`ChatResponse`) |
| `metadata` | Tous les nœuds | API, Langfuse, tests |

Note Personnel :

Différence entre Sequence vs list
C'est cosmétique. Sequence[BaseMessage] dit « quelque chose qui se comporte comme une liste » (tuple, liste...). list[BaseMessage] est plus explicite. Les deux passent, mais list est plus moderne en Python 3.10+

Différence entre operator.add vs add_messages
| | `operator.add` | `add_messages` |
|---|---|---|
| **Ce que ça fait** | Concatène deux listes : `[a] + [b]` | Concatène **en dédupliquant par ID** |
| **Le piège** | Si un nœud renvoie `state["messages"]` au lieu des *nouveaux* messages, l'historique entier est dupliqué | Détecte les messages déjà présents et les ignore |

Imaginons que rag_node renvoie malencontreusement l'historique complet :
```
# Dans rag_node — BUG classique du débutant
return {"messages": state["messages"] + [new_msg]}
Avec operator.add, LangGraph concatène :
```

- Ancienne liste : [human_msg, ai_msg] (déjà dans le state)
- Nouvelle liste : [human_msg, ai_msg, rag_msg] (renvoyée par le nœud)

Résultat : [human_msg, ai_msg, human_msg, ai_msg, rag_msg] → tout est dupliqué !
Avec add_messages, le reducer regarde les IDs uniques des messages : il sait que human_msg et ai_msg existent déjà, il ne les recopie pas.

