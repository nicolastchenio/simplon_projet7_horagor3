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

**=> creation du fichier "src\models\state.py"**

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

# Phase 3 : Construction du Graphe Multi-Agent (Peer-to-Peer) #

## 3.1 Node 1 : L'Agent RAG (rag_node) ##

C'est un noeud déterministe (=> pas d appel a un llm)
1) Le contrat d'un nœud LangGraph :  
    Dans LangGraph, un nœud n'est pas une classe. C'est une fonction Python pure qui respecte un contrat strict :
    - Entrée : elle reçoit l'état courant (state: AgentState) — c'est un snapshot complet de la mémoire commune.
    - Sortie : elle retourne un dict contenant uniquement les clés qu'elle veut ajouter ou modifier.
    - Fusion : LangGraph applique ce dict sur l'état global. Pour la liste messages, grâce au reducer add_messages que tu as déclaré dans AgentState, le nouveau message est ajouté (pas écrasé).


    Règle d'or : on ne jamaise balance la donnée brute (JSON kilométrique) dans messages. On y met un résumé synthétique (AIMessage). La donnée brute reste dans rag_results, accessible aux nœuds suivants par clé

2) La stratégie du double appel (Vectoriel + Structuré) :  
    Le rag_node doit être le seul endroit où l'on interroge le savoir local. Il croise :  
    - search_local_horror_lore(query) → le cœur vectoriel FAISS (chunks de lore, synopsis, critiques).
    - query_movie_metadata(query) → la base structurée (SQL ou dictionnaire de métadonnées : titre, réalisateur, année, etc.).

    Si l'utilisateur demande "Qui a réalisé L'Exorciste en 1973 ?", FAISS peut rapporter des chunks pertinents mais oublier l'année exacte. La requête structurée elle, remonte la fiche complète. Le routeur (3.2) décidera ensuite si ce double résultat est suffisant.

**=> Creation de "src/graph/nodes.py" :**  
Pour l'instant, ce fichier ne contient que le chercheur local. Les deux autres ouvriers (scraper_node, narration_node) viendront s'y greffer dans les étapes suivantes.

## 3.2 Le Router (router.py) ##
le router est une fonction Python pure, zéro LLM, qui lit state["rag_results"] et renvoie une chaîne "narration" ou "scraper".

Le contrat de données entre rag_node et router  :  
Pour que le router puisse décider sans ambiguïté, le rag_node doit écrire dans l'état un dict structuré de cette forme :
```
state["rag_results"] = {
    "faiss": {
        "hits": [
            {"text": "...", "score": 0.78, "source": "lore_1973.txt"},
            {"text": "...", "score": 0.61, "source": "lore_1973.txt"},
        ],
        "best_score": 0.78,   # cosine similarity (IndexFlatIP, vecteurs normalisés)
        "count": 2,
    },
    "structured": {
        "movies": [
            {"id": 123, "title": "The Exorcist", "year": 1973, ...}
        ],
        "count": 1,
    }
}
```

1) creation du fichier "src/graph/router.py"
2) creation d un test "test_router_iso.py"
```
# test_router_iso.py  ← fichier jetable après validation
"""Tests isolés du router — à supprimer ou déplacer dans tests/ après succès.

Usage :
    python test_router_iso.py

Puis suppression :
    rm test_router_iso.py
"""

from src.graph.router import route_after_rag


def test_riche__narration():
    state = {
        "rag_results": {
            "faiss": {
                "hits": [
                    {"text": "The Exorcist 1973...", "score": 0.81},
                    {"text": "Regan MacNeil...", "score": 0.74},
                ],
                "best_score": 0.81,
            },
            "structured": {
                "movies": [{"id": 1, "title": "The Exorcist", "year": 1973}]
            },
        }
    }
    assert route_after_rag(state) == "narration", "riche devrait aller en narration"


def test_struct_vide__scraper_meme_si_faiss_renvoie_qqch():
    state = {
        "rag_results": {
            "faiss": {
                "hits": [{"text": "...", "score": 0.55}],
                "best_score": 0.55,
            },
            "structured": {"movies": []},
        }
    }
    assert route_after_rag(state) == "scraper", "struct vide doit basculer scraper"


def test_faiss_faible__scraper():
    state = {
        "rag_results": {
            "faiss": {"hits": [{"score": 0.42}], "best_score": 0.42},
            "structured": {"movies": [{"id": 2, "title": "Some Film"}]},
        }
    }
    assert route_after_rag(state) == "scraper", "faiss faible doit basculer scraper"


def test_rag_results_manquant__scraper():
    assert route_after_rag({}) == "scraper", "garde-fou manquant doit basculer scraper"


if __name__ == "__main__":
    test_riche__narration()
    test_struct_vide__scraper_meme_si_faiss_renvoie_qqch()
    test_faiss_faible__scraper()
    test_rag_results_manquant__scraper()
    print("✅ 4/4 tests router isolés passés — le router est calibré.")
```
3) commande pour executer le test ` uv run python test_router_iso.py `

## 3.3 Node 2 : L'Agent Scraper (scraper_node) ##
1) Dans "src/graph/nodes.py" — ajouter scraper_node
2) Crée test_scraper_node_iso.py à la racine :
```
from src.graph.nodes import scraper_node
from src.models.state import AgentState

def test_scraper_avec_titre_structuré():
    state: AgentState = {
        "query": "film avec le clown des égouts",
        "messages": [],
        "rag_results": {
            "faiss": {"best_score": 0.38, "hits": []},
            "structured": {"movies": [{"id": 42, "title": "It"}]},
        },
        "scraped_data": None,
        "needs_enrichment": None,
        "final_answer": None,
        "sources": None,
        "metadata": {},
    }
    result = scraper_node(state)
    assert "scraped_data" in result
    assert result["scraped_data"]["title"] == "It"
    assert result["scraped_data"]["success"] in (True, False)
    print("✅ Test structuré OK")

def test_scraper_fallback_query():
    state: AgentState = {
        "query": "The Exorcist",
        "messages": [],
        "rag_results": {"faiss": {"best_score": 0.2, "hits": []}, "structured": {"movies": []}},
        "scraped_data": None,
        "needs_enrichment": None,
        "final_answer": None,
        "sources": None,
        "metadata": {},
    }
    result = scraper_node(state)
    assert result["scraped_data"]["title"] == "The Exorcist"
    print("✅ Test fallback query OK")

if __name__ == "__main__":
    test_scraper_avec_titre_structuré()
    test_scraper_fallback_query()
    print("✅ Tests scraper_node isolés passés")
```

3) executer la command ` uv run python test_scraper_node_iso.py `

## 3.4 Node 3 : L'Agent Narration (narration_node) ##
1) Dans "src/graph/nodes.py" — ajouter narration_node

    | Principe plan | Réalisation dans le code |
    |---|---|
    | **Isolation stricte** | On lit `query`, `rag_results`, `scraped_data`. On ne parcourt **jamais** `state["messages"]`. |
    | **Anti-hallucination** | Prompt système explicite : *« Tu ne disposes d'aucune mémoire externe »* + corpus injecté en `human_prompt`. |
    | **Outils attachés** | Appels déterministes selon mots-clés de la query (`wants_reco`, `wants_survival`) + `calculate_movie_age` systématique si année dispo. |
    | **Anti-collision tokens** | Le LLM ne voit que le contexte encyclopédique recompilé à blanc, pas les résumés techniques des autres nœuds. |
    | **Sources propres** | Tableau `sources` structuré prêt pour l'API (`type`, `title`, `year`, `score`…). |

2) Crée test_narration_node_iso.py à la racine :
    ```
    from src.graph.nodes import narration_node
    from src.models.state import AgentState

    def test_narration_plein():
        state: AgentState = {
            "query": "Parle-moi de The Exorcist et recommande-moi un film similaire",
            "messages": [],
            "rag_results": {
                "faiss": {
                    "best_score": 0.88,
                    "hits": [
                        {"text": "Regan est possédée par un démon via la ouija...", "score": 0.88, "source": "lore_exorcist.txt"},
                    ],
                },
                "structured": {
                    "movies": [
                        {
                            "id_film": 1,
                            "title": "The Exorcist",
                            "titre": "L'Exorciste",
                            "year": 1973,
                            "annee_sortie": 1973,
                            "realisateur": "William Friedkin",
                            "genres": "Horreur, Surnaturel",
                        }
                    ]
                },
            },
            "scraped_data": None,
            "needs_enrichment": None,
            "final_answer": None,
            "sources": None,
            "metadata": {},
        }
        result = narration_node(state)
        assert "final_answer" in result and len(result["final_answer"]) > 0
        assert isinstance(result.get("sources"), list)
        assert len(result["messages"]) == 1
        print("✅ Test narration PLEIN passé")
        print(f"📝 Réponse ({len(result['final_answer'])} car.) :\n{result['final_answer'][:400]}...")

    def test_narration_vide():
        state: AgentState = {
            "query": "Film inexistant XYZ12345",
            "messages": [],
            "rag_results": {"faiss": {"best_score": 0.1, "hits": []}, "structured": {"movies": []}},
            "scraped_data": None,
            "needs_enrichment": None,
            "final_answer": None,
            "sources": None,
            "metadata": {},
        }
        result = narration_node(state)
        assert "final_answer" in result
        print("✅ Test narration VIDE passé (ne plante pas)")

    if __name__ == "__main__":
        test_narration_plein()
        print()
        test_narration_vide()
        print("\n✅ Tous les tests narration_node isolés passés.")
    ```
3) Vérifie qu'Ollama est démarré, puis : ` uv run python test_narration_node_iso.py `

## 3.5 Câblage et Compilation (pipeline.py) ##

1) creation du fichier "src/graph/pipeline.py"
    | Élément | Rôle |
    |---|---|
    | `MemorySaver()` | Checkpointer in-memory qui permet de reprendre une conversation (thread_id) si tu veux ajouter du chat multi-tours plus tard. |
    | `workflow.compile(checkpointer=memory)` | Figé le graphe en une application exécutable. |
    | `add_conditional_edges` | Aiguillage déterministe Python (ton `route_after_rag`) — **zéro appel LLM** pour router. |
    | `config={"configurable": {"thread_id": ...}}` | Obligatoire dès qu'on utilise un checkpointer, même en mode stateless par requête. |



2) Crée à la racine test_pipeline.py pour valider le flux complet :
   ```
   """
    test_pipeline.py (jetable)
    Validation end-to-end : RAG → Router → Narration (ou Scraper) → Narration.
    """
    import uuid

    from src.graph.pipeline import build_horragor_graph
    from src.models.state import AgentState


    def run_graph(query: str):
        graph = build_horragor_graph()

        initial_state: AgentState = {
            "query": query,
            "messages": [],
            "rag_results": None,
            "scraped_data": None,
            "needs_enrichment": None,
            "final_answer": None,
            "sources": None,
            "metadata": {"session_id": str(uuid.uuid4())},
        }

        # Configuration du thread pour le checkpointer
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}

        final_state = graph.invoke(initial_state, config=config)
        return final_state


    def test_chemin_direct_narration():
        """Question riche → devrait passer directement à narration_node."""
        print("\n=== TEST : Chemin RAG → Narration ===")
        result = run_graph("Parle-moi de The Exorcist et de son impact")

        answer = result.get("final_answer", "")
        sources = result.get("sources", [])

        print(f"Réponse ({len(answer)} car.) :")
        print(answer[:600] + ("..." if len(answer) > 600 else ""))
        print(f"\nSources utilisées : {len(sources)}")
        for s in sources:
            print("  -", s)

        assert answer, "final_answer ne doit pas être vide"
        assert result["messages"], "L'historique doit contenir le message final"
        print("\n✅ Chemin direct passé.")


    def test_chemin_avec_scraper():
        """Question ambiguë ou film incomplet → devrait transiter par scraper_node."""
        print("\n=== TEST : Chemin RAG → Scraper → Narration ===")
        result = run_graph("Le film avec un clown qui tue des gosses dans les égouts")

        answer = result.get("final_answer", "")
        scraped = result.get("scraped_data")

        print(f"Réponse ({len(answer)} car.) :")
        print(answer[:600] + ("..." if len(answer) > 600 else ""))
        if scraped:
            print(f"\nDonnées scrapées présentes : {len(scraped.get('movies', []))} film(s)")
        else:
            print("\n(Aucun scraping déclenché — le RAG a peut-être suffi)")

        assert answer, "final_answer ne doit pas être vide"
        print("\n✅ Chemin via scraper passé (ou RAG autosuffisant).")


    if __name__ == "__main__":
        test_chemin_direct_narration()
        test_chemin_avec_scraper()
        print("\n" + "=" * 50)
        print("✅ Tous les tests pipeline passés.")
        print("=" * 50)
    ```
3) Lance le test (Ollama doit tourner) : ` uv run python test_pipeline.py `

# Phase 4 : API Backend (FastAPI + Uvicorn) #
## 4.1 Serveur FastAPI (src/main.py) ##
Installe les dépendances nécessaires : ` uv add fastapi uvicorn `

1) On va maintenant envelopper tout ça dans un serveur FastAPI (src/main.py) robuste, avec :

   - des modèles Pydantic typés pour l'entrée et la sortie :  
     on définit le contrat de données : ce que le client envoie et ce que l'API renvoie. Cela valide automatiquement les requêtes et documente l'API.
     - ChatRequest force le client à envoyer un message non vide.
     - ChatResponse garantit que le client reçoit toujours la même structure, quelle que soit la réussite ou l'échec interne.
     - Les Field(description=...) serviront à la documentation auto-générée de FastAPI (/docs).
     
   - un lifespan qui compile le graphe une seule fois au démarrage :  
       On ne veut pas recompiler le StateGraph à chaque requête : c'est coûteux et inutile. FastAPI propose le pattern lifespan pour exécuter du code au démarrage et à l'arrêt du serveur.
       - yield sépare le boot (avant) du teardown (après).
       - Le graphe est importé à l'intérieur du lifespan pour éviter les imports circulaires au chargement du module.
       - _compiled_graph est globale à ce module, mais encapsulée : seul main.py y touche.

   - un endpoint POST /chat qui prépare le state, invoque le graphe, et formate la réponse :
       - Vérifier que le graphe est chargé.
       - Créer le AgentState initial.
       - Appeler graph.invoke(...) sans bloquer la boucle async de FastAPI (on utilise asyncio.to_thread).
       - Extraire final_answer et reconstruire les sources à partir de rag_results et scraped_data.
       - Retourner un ChatResponse propre.
     
   - une gestion d'erreur propre (HTTP 500 contrôlé, pas de crash brut).

2) Lancer et tester  
    S'assurer que Ollama tourne et que ton .env est chargé, puis lance le serveur :
    ` uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 `

    On doit voir dans la console :
    ```
    [lifespan] Compilation du graphe LangGraph en cours...
    [lifespan] Graphe compilé et prêt.
    ```

    Puis, dans un autre terminal, teste avec curl :
    ```
    curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"message\": \"Parle-moi de Freddy les griffes de la nuit et de son impact\"}"
    ```
    On doit recevoir un JSON du type :
    ```
    {
    "response": "Ah, cher lecteur gothique, permets-moi de te mener...",
    "sources": [
        {"type": "faiss", "score": 0.715, "title": "Les Griffes de la nuit", "year": 1984, "preview": "..."},
        {"type": "sql", "id": 42, "title": "Les Griffes de la nuit", "year": 1984}
    ],
    "used_web": false,
    "thread_id": "a1b2c3d4-..."
    }
    ```
    
    Autre option => Ouvrir simplement http://localhost:8000/docs dans le navigateur.
      - Cliquer sur POST /chat
      - Cliquer sur "Try it out"
      - Coller un message dans le message du ChatRequest
      - Cliquer "Execute"

    On verra la réponse JSON directement, sans se battre avec curl

    Et l'UI doc est dispo ici : http://localhost:8000/docs

## 4.2 Gestion de l'historique ##
Actuellement dans "main.py" à chaque appel on envoie :

```
initial_state: AgentState = {
    "query": payload.message,
    "messages": [],        # ← vide : le message utilisateur n'est pas injecté ici
    ...
}
```
Conséquence : le MemorySaver restaure bien l'historique précédent depuis le RAM, mais comme tu ne lui ajoutes jamais le nouveau message de l'utilisateur, le narration_node ne peut pas exploiter la conversation en contexte. L'historique est sauvé, mais il est muet.

Dans "src/main.py" :

- Ajoute l'import (avec les autres imports en haut) : ` from langchain_core.messages import HumanMessage `
- Modifie la construction de initial_state dans chat_endpoint :
    ```
        initial_state: AgentState = {
            "query": payload.message,
            "messages": [HumanMessage(content=payload.message)],  # ← AJOUTÉ
            "rag_results": None,
            "scraped_data": None,
            "needs_enrichment": None,
            "final_answer": None,
            "sources": None,
            "metadata": {"session_id": str(uuid.uuid4())},
        }
    ```
    Grâce au reducer add_messages, LangGraph va fusionner cette nouvelle liste avec l'historique déjà stocké dans le checkpoint du thread_id. Si c'est la première fois, la liste devient [HumanMessage(...)]. Si c'est le 3ème échange, elle devient [..., AIMessage(...), HumanMessage(...)].

Dans "src/graph/nodes.py" Faire lire la mémoire au narrateur (option mais recommandée) :
- il faut que le narration_node injecte l'historique dans son prompt. dans narration_node, juste après print(">>> Narration Node") rajouter :
    ```
    # ── 0. RÉCUPÉRATION DE LA MÉMOIRE CONVERSATIONNELLE DU THREAD ──
    # On filtre les bruits techniques (logs RAG / scraper) pour ne garder
    # que les échanges réels entre le lecteur et le chroniqueur.
    dialogue_history: list[str] = []
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            dialogue_history.append(f"LECTEUR : {msg.content}")
        elif isinstance(msg, AIMessage):
            # On saute les résumés des nœuds internes
            if msg.content.startswith("Recherche RAG") or msg.content.startswith("🔍 Scraping"):
                continue
            # Pour le message de narration, on isole la réponse textuelle proprement dite
            text = msg.content
            if text.startswith("🖋️") and "\n\n" in text:
                text = text.split("\n\n", 1)[1]
            dialogue_history.append(f"HORRAGOR : {text.strip()}")

    # La dernière entrée est la requête actuelle (injectée par main.py) → on l'exclut du passé
    memory_block = ""
    if len(dialogue_history) > 1:
        memory_block = "--- CONTEXTE DU DIALOGUE ---\n" + "\n".join(dialogue_history[:-1]) + "\n\n"
    ```
- Puis, modifie le bloc human_parts pour insérer cette mémoire 
    ```
    human_parts = [
        f"QUESTION DU LECTEUR : {query}",
        "",
        memory_block + "--- ENCYCLOPÉDIE HORRAGOR ---",
        encyclopedic_context,
    ]
    ```
- modifier le le system_prompt pour légitimer la mémoire (une ligne suffit) :
    ```
    system_prompt = (
        "Tu es HorRAGor, chroniqueur de cinéma d'horreur gothique, vêtu d'une redingote noire "
        "et armé d'une plume d'argent. Tu peux considérer le CONTEXTE DU DIALOGUE ci-dessus "
        "pour adapter ton ton et tes références, mais les faits doivent impérativement provenir "
        "de l'ENCYCLOPÉDIE et des OUTILS fournis ci-dessous. "
        "Règles absolues :\n"
        "1. Base-toi exclusivement sur les sections FICHES, EXTRAITS, ENRICHISSEMENT et Outils.\n"
        "2. Si la réponse n'est pas dans le corpus, avoue-le avec élégance gothique ; n'invente jamais.\n"
        "3. Ne invente aucun titre, réalisateur, date, ou intrigue.\n"
        "4. Sépare clairement chaque film si le corpus en mentione plusieurs.\n"
        "5. Utilise les RECOMMANDATIONS uniquement si elles sont fournies par l'outil.\n"
        "6. Termine toujours par une signature macabre appropriée."
    )
    ```

Test rapide pour valider, dans le terminal :
```
# Thread 1 : présentation
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"message\": \"Je m'appelle Alice et j'adore l'horreur psychologique\", \"thread_id\": \"memo-test-777\"}"

# Thread 2 : question de mémoire (même thread_id)
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"message\": \"Quel est mon prénom et quel genre horrifique j'aime ?\", \"thread_id\": \"memo-test-777\"}"
```

## 4.3 Endpoint de santé ##
C'est une ligne à ajouter dans src/main.py pour exposer une santé du système.


Dans src/main.py, ajoute simplement cet endpoint à la suite de tes autres routes :
```
@app.get("/health")
async def health_check():
    """Endpoint minimal pour le monitoring (Uptime Kuma, Phase 8)."""
    return {
        "status": "ok",
        "service": "horragor-api",
        "timestamp": datetime.utcnow().isoformat()
    }
```
Ne pas oublier l'import si tu utilises datetime :
```
from datetime import datetime
```
Tester-le :
```
curl http://localhost:8000/health
```
On doit obtenir :
```
{"status":"ok","service":"horragor-api","timestamp":"2026-07-17T..."}
```

# Phase 5 : Frontend Streamlit (Chatbot) #
## 5.1 Interface Chat (app_frontend.py) ##
On se concentre uniquement sur l'interface : on veut une page Streamlit fonctionnelle avec les bulles, la zone de saisie et le spinner — mais sans l'appel API pour l'instant (c'est le sujet de la 5.2).

1) Créer le fichier "app_frontend.py" à la racine du projet.
2) Tester
   - Lancer l'API (pour l'instant elle n'est pas encore appelée, mais c'est une bonne habitude) :
   ` uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload `
   - Dans un second terminal, lance Streamlit : ` streamlit run app_frontend.py `
   - On doit voir sur url => http://localhost:8501/  l'interface streamlit

## 5.2 Communication avec l'API ##
On remplace la simulation par un vrai appel HTTP vers ton FastAPI.

Pré-requis : ton backend (uvicorn src.main:app --port 8000) doit être lancé. Le contrat attendu côté frontend est le JSON que renvoie ton ChatResponse :
```
{
  "response": "Le film d'horreur...",
  "sources": [...],
  "metadata": {"enriched_from_web": true}
}
```

1) On retire time (inutile maintenant) et on ajoute httpx. On définit aussi les constantes de connexion, y compris le placeholder X-API-Key pour la 5.3.  
Le API_TIMEOUT à 120 s est volontaire : si le graphe LangChain doit scraper Wikipédia, on ne veut pas couper la connexion au bout de 5 secondes.
2) Fonction d'appel au backend => def call_chat_api(question: str, thread_id: str)  
le cœur de la communication. Cette fonction isole tout le réseau (erreurs comprise) pour ne pas faire crasher l'interface si l'API est éteinte.
3) Fonction utilitaire de rendu des sources
Pour éviter de dupliquer le code entre l'affichage de l'historique et l'affichage temps réel, on crée une petite fonction interne. Au lieu d'afficher str(source) brut, on déstructure le dict réel. Si title est None, on tombe sur un intitulé par défaut. Si preview est vide, on affiche une mention d'indisponibilité plutôt qu'un champ vide.
4) Mise à jour de l'affichage de l'historique  
En 5.1, nos messages étaient des {"role": ..., "content": ...}. Maintenant, un message assistant peut transporter aussi les sources et les metadata. Il faut donc enrichir display_chat_history pour ré-afficher ces extras quand Streamlit réexécute le script.
5) Wiring — remplacement de la simulation par l'appel réel  
On réécrit handle_user_input. Le principe reste le même (input → affichage user → spinner → affichage bot), mais on appelle maintenant call_chat_api, et on stocke l'intégralité de la réponse (texte + sources + metadata) dans l'historique.
6) Vérification de la fonction main  
La fonction main et init_session_state restent globalement identiques à la 5.1.

Refaire le teste faite en 5.1 :
- poser une question → bulle user immédiate.
- Le spinner « consulte les archives... » s'affiche pendant 1 à 30 s (selon ta chaîne RAG).
- La réponse textuelle du bot apparaît.
- Si le backend renvoie une liste dans "sources", un encart 📚 Sources utilisées apparaît sous la réponse.
- Si le backend renvoie "metadata": {"enriched_from_web": true}, le caption 🔍 Enrichi via le Web est visible

## 5.3 Sécurisation minimale ##
Il ne reste qu'une ligne à ajouter : le header X-API-Key dans le client httpx. C'est un placeholder pour préparer la Phase 7 (vraie authentification).

Modification de call_chat_api, Remplacer juste le bloc headers au début de la fonction par celui-ci :
```
headers = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,  # Phase 5.3 : header préparatoire pour l'authentification
}
```

Le reste de la fonction reste inchangé. Le API_KEY est déjà défini en haut du fichier : ` API_KEY: str = "placeholder-horragor-key" `

# src/config.py #
1) Crée le fichier  src/config.py
2) modification de src/tools/rag_tool.py  
   Test rapide à faire après mise à jour :
   ```
   # 1. Vérifier que le module charge sans erreur
    python -c "from src.tools.rag_tool import search_local_horror_lore; print('OK rag_tool')"

    # 2. Vérifier que config expose les bonnes valeurs
    python -c "from src.config import OLLAMA_CHAT_MODEL; print(OLLAMA_CHAT_MODEL)"
    # Attendu : qwen2.5:7b (ou ce que tu as mis dans ton .env)
    ```
3) modifier src/tools/scraper_tool.py
   test a faire :
   ` python -c "from src.tools.scraper_tool import REQUEST_TIMEOUT; print(REQUEST_TIMEOUT)" `
4) modifier src/graph/router.py  
   - Et ajout de ` FAISS_COSINE_THRESHOLD=0.60 ` dans mon .env
        Dans src/config.py, tu as déjà une valeur par défaut : ` FAISS_COSINE_THRESHOLD: float = float(os.getenv("FAISS_COSINE_THRESHOLD", "0.55")) `  
        Cela signifie :
        - Pas de variable dans .env  → (config.py prend le relais)→  0.55
        - FAISS_COSINE_THRESHOLD=0.60 dans .env  →  .env prime  →  0.60  
        On a donc les deux :
        - .env = la surcouche locale pour toi, maintenant, sur cette machine.
        - config.py = le fallback universel si quelqu'un oublie de renseigner le .env.
  
        Si on met 0.60 en dur dans config.py ou router.py, on doit modifier le code source et redémarrer l'IDE à chaque fois que l'on change d'environnement. Avec .env, tu changes une valeur, tu relances, c'est testé — sans toucher au code.

   - test a faire : ` python -c "from src.graph.router import FAISS_COSINE_THRESHOLD; print(FAISS_COSINE_THRESHOLD)" `
   
5) modifier src/graph/nodes.py
   test a faire : ` python -c "from src.graph.nodes import _get_narrator_llm; llm = _get_narrator_llm(); print(llm.model, llm.base_url)" `
6) modifier data/build_faiss_index.py

# Phase 6 : Extraction de la Couche Données (API dédiée) #

Actuellement, rag_tool.py ouvre une connexion directe à Supabase avec psycopg2. C'est pratique en développement, mais c'est une faille d'architecture :
- Le mot de passe Supabase transite dans le code du backend métier.
- Si on change de base, tu dois modifier tous les outils.
- La couche "accès aux données" n'est pas testable / mockable proprement.

L'idée est donc de créer un service FastAPI dédié, interne, qui sera le seul à parler à PostgreSQL. Ton API principale (src/main.py, port 8000) deviendra un client HTTP de ce nouveau service (data_api, port 8001).On respecte le principe : "La base est inaccessible depuis l'extérieur du cluster".

## 6.1 Créer le service data_api ##

1) Creation de l'architecture :
    ```
    horragor-project/
    ├── data_api/      ← (NOUVEAU)
    │   ├── __init__.py
    │   ├── database.py
    │   ├── models.py
    │   ├── main.py
    │   └── routers/
    │       ├── __init__.py
    │       └── films.py

2) data_api/database.py  
On utilise un pool de connexions synchrones. FastAPI exécute les fonctions def dans un threadpool, donc le service reste non-bloquant.

3) data_api/models.py  
On définit les schémas de données. Le modèle FilmDetail est la représentation canonique d'un film dans notre API.

4) data_api/routers/films.py
C'est ici qu'on écrit les endpoints qui remplaceront les requêtes brutes de rag_tool.py.

5) data_api/main.py

6) dans src/config.py rajouter 
    ```
    # ═══════════════════════════════════════════════════════════════
    # Service interne data-api (Phase 6)
    # ═══════════════════════════════════════════════════════════════
    # URL complète vers le micro-service d'accès aux données.
    # En dev c'est localhost:8001, en Docker ce sera http://data-api:8001
    # sur le réseau interne.
    # ═══════════════════════════════════════════════════════════════
    DATA_API_URL: str = os.getenv("DATA_API_URL", "http://localhost:8001")
    ```

    test dans le navigateur ` http://127.0.0.1:8001/health `
    ou 
    ```
    # 1. Santé
    curl http://127.0.0.1:8001/health

    # 2. Recherche textuelle
    curl "http://127.0.0.1:8001/films/search?q=exorcist&limit=2"

    # 3. Film par ID (remplace 1 par un vrai id de ta base)
    curl http://127.0.0.1:8001/films/3937
    ```
## 6.2 Migrer rag_tool.py vers ce service ##
Il y a 3 étapes :

| Étape | Action | Fichier(s) concerné(s) |
|-------|--------|------------------------|
| **1** | **Terminer le `data-api`** pour qu'il expose tous les endpoints dont `rag_tool.py` a besoin (recherche textuelle, détail par ID, similarité pgvector par ID, fuzzy). | `data_api/routers/films.py` |
| **2** | **Réécrire `rag_tool.py`** pour qu'il appelle le `data-api` via `httpx` au lieu de `psycopg2`. | `src/tools/rag_tool.py` |
| **3** | **Nettoyer & tester** : supprimer `psycopg2` du côté Intelligence, vérifier les appels. | `.env`, `src/config.py`, etc. |

1) Terminer data_api/routers/films.py  
data-api existe mais il renvoie encore beaucoup de null (pas de jointures). De plus, il lui manque l'endpoint de similarité par ID et de fuzzy matching.
   - Vérifie la dépendance rapidfuzz => ` uv add rapidfuzz `
   - modifier data_api/routers/films.py pour integrer les jointures et les 4 endpoints nécessaires.
   - Vérifie que data-api démarre toujours => ` uvicorn data_api.main:app --host 127.0.0.1 --port 8001 --reload `
   - Tester les 4 endpoints
        ```
        # Test A : recherche textuelle avec jointures
        curl "http://127.0.0.1:8001/films/search?q=exorcist&limit=1"

        # Test B : détail par ID
        curl "http://127.0.0.1:8001/films/3937"

        # Test C : similarité pgvector
        curl "http://127.0.0.1:8001/films/3937/similar?k=2"

        # Test D : fuzzy
        curl "http://127.0.0.1:8001/films/fuzzy?title=conjuring"
        ```

2) Réécrire src/tools/rag_tool.py
- Installer  httpx côté API Intelligence => uv add httpx
- Remplacer le contenu de src/tools/rag_tool.py  
  Les seules parties conservées sont FAISS (qui reste local) et la logique métier (formatage, fuzzy, etc.). Tout le SQL a été remplacé par des appels httpx vers DATA_API_URL.

3) Nettoyer les imports inutiles dans src/config.py si besoin
   
4) Tester de la migration  
Lance les 2 services (dans 2 terminaux séparés) :
   - Terminal 1 — data-api => ` uvicorn data_api.main:app --host 127.0.0.1 --port 8001 `
   - Terminal 2 — API Intelligence =>  ` uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload `  

Puis teste depuis un 3ème terminal que rag_tool.py fonctionne encore via le nouveau chemin HTTP :  
```
# Test A : métadonnées structurées (appelle data-api en interne)
uv run python -c "from src.tools.rag_tool import query_movie_metadata; print(query_movie_metadata(titre='exorcist', top_k=2))"

# Test B : similarité pgvector
uv run python -c "
from src.tools.rag_tool import find_similar_horror_movies
print(find_similar_horror_movies(3937, k=2))
"

# Test C : fuzzy → resolve
uv run python -c "from src.tools.rag_tool import fuzzy_find_film, resolve_film; print(fuzzy_find_film('conjuring')); print(resolve_film('conjuring'))"
```

# Phase 7 : Conteneurisation, Auth & Réseau #
## 7.1 Docker & Docker Compose
L'objectif est de figer l'application dans 3 images isolées qui communiquent uniquement à l'intérieur d'un réseau privé Docker (horragor-net). En configuration sécurisée, seul Streamlit expose un port vers l'hôte (8501). Pour préserver cette contrainte tout en permettant le débogage, l'architecture repose sur deux fichiers d'orchestration : une base stricte et un override de développement.

### Principe de l'architecture réseau

Dans Docker, chaque conteneur possède son propre espace réseau et ne connaît pas les ports de l'hôte. Lorsqu'ils partagent un même réseau bridge (horragor-net), ils peuvent se joindre par leur nom de service défini dans le compose :
- intelligence-api appelle http://data-api:8001 (Data API)
- frontend appelle http://intelligence-api:8000 (Intelligence API)
- Le navigateur de l'utilisateur, lui, ne voit que http://localhost:8501

Les identifiants Supabase restent ainsi confinés dans le conteneur data-api, et le moteur LLM (Ollama) reste accessible uniquement par intelligence-api via host.docker.internal.

### Construction des images
Trois images sont construites à la demande grâce aux Dockerfile placés dans le dossier docker/ :
- docker/data_api.Dockerfile : image légère basée sur python:3.12-slim. Seuls les fichiers strictement nécessaires sont copiés : src/__init__.py et src/config.py (la configuration Supabase), ainsi que le code spécifique du Data API. Le graphe LangGraph et les outils de l'Intelligence ne sont pas embarqués ici.
- docker/intelligence_api.Dockerfile : image complète embarquant libgomp1 (requis par faiss-cpu), l'intégralité du package src/, l'index FAISS sous data/faiss_index et le fichier pyproject.toml. Les variables OLLAMA_BASE_URL=http://host.docker.internal:11434 et DATA_API_URL=http://data-api:8001 lui permettent de joindre Ollama sur l'hôte Windows et le Data API sur le réseau interne.
- docker/frontend.Dockerfile : image Streamlit avec httpx et PYTHONPATH=/app. Elle copie l'ensemble du dossier src/ (nécessaire pour l'import src.config), le script app_frontend.py et le dossier .streamlit/.

### Orchestration : deux configurations pour deux usages

Pour respecter l'exigence de sécurité (seul le frontend exposé) sans bloquer le développement, on utilise le mécanisme de fusion de fichiers de Docker Compose.

#### Fichier de base : docker-compose.yml
Ce fichier décrit la configuration cible et sécurisée. Il déclare les 3 services avec la directive build pour reconstruire automatiquement les images si elles sont absentes, surcharge les variables d'environnement pour utiliser les noms de service internes (ex. API_BASE_URL=http://intelligence-api:8000), et n'expose aucun port pour les deux APIs.

#### Fichier d'override : docker-compose.dev.yml
Ce second fichier, placé à côté du premier, contient uniquement les différences nécessaires au mode développement. Il ajoute temporairement les sections ports: pour data-api (8001:8001) et intelligence-api (8000:8000). Docker Compose fusionne les deux fichiers à l'exécution : la base définit le réseau, les variables et les dépendances, tandis que l'override injecte les ports de debug sans modifier l'image de production.

| Mode | Commande | Ports exposés | Usage |
|------|----------|---------------|-------|
| **Production / Sujet** | `docker compose up -d` | Seul `8501` (Streamlit) | Respect strict du périmètre de sécurité. Les APIs sont invisibles depuis l'hôte mais communiquent en interne. |
| **Développement** | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` | `8501`, `8000`, `8001` | Swagger (`/docs`) et tests directs sur les APIs accessibles depuis le navigateur/Postman. |

1) Dockerfile du data_api
- creer "docker/data_api.Dockerfile"
  
    | Instruction | Pourquoi on fait ça |
    |-------------|---------------------|
    | `python:3.12-slim` | Image légère (~60 Mo) suffisante pour FastAPI + psycopg. Pas besoin de la version "full" ou d'Alpine (qui complique les builds Python). |
    | `PYTHONUNBUFFERED=1` | Force Python à afficher les logs immédiatement. Indispensable pour voir les erreurs dans `docker logs`. |
    | `uv pip install --system` | Dans un conteneur, on n'a pas besoin de virtualenv. On installe directement dans l'environnement système Python. |
    | `COPY pyproject.toml` avant le code | **Cache Docker magique** : si tu modifies juste un `.py`, Docker réutilise la layer des dépendances déjà installées. Le build est instantané. |
    | `COPY src/config.py` seul | Respect du principe : on n'embarque pas tout `src/` (pas besoin du graphe LangGraph ici). Juste la config. |
    | `EXPOSE 8001` | Documente le port. Le `docker-compose.yml` l'utilisera plus tard pour le mapping. |
    | **`python:3.12-slim`** | Ton `pyproject.toml` exige `>=3.12`. On s'aligne exactement. |
    | **`RUN mkdir -p src`** | Prépare le dossier avant de copier les fichiers dedans. |
    | **`COPY src/__init__.py src/`** | Nécessaire pour que Python traite `src` comme un package. Sans ça, `from src.config import ...` pourrait échouer selon le contexte. |

- Créer ".dockerignore" à la racine de ton projet (au même niveau que .env)
- Commande pour tester le build :
  - Depuis la racine de ton projet : ` docker build -f docker\data_api.Dockerfile -t horragor-data-api:1.0 . `
  - Si on est en train de coder et que de rebuilds souvent, ajouter --no-cache quand on modifie les dépendances : `docker build --no-cache -f docker\data_api.Dockerfile -t horragor-data-api:1.0 . `
  - Lancer le conteneur (méthode rapide avec ton .env), puisque ton .env est déjà à la racine, Docker peut le lire directement et injecter les variables dans le conteneur : ` docker run --rm -p 8001:8001 --env-file .env horragor-data-api:1.0 `
  - Vérifie ensuite : http://localhost:8001/docs doit afficher ta documentation Swagger.
  
2) Dockerfile pour ton API Intelligence (FastAPI + LangGraph + FAISS)  
Il est plus complet que celui du data-api car il embarque tout le package src/, l'index FAISS, et la librairie système libgomp1 requise par faiss-cpu.

   -  Créer le fichier "docker\intelligence_api.Dockerfile"
   -  creer un ".env.docker" à la racine:
   -  build  => ` docker build -f docker\intelligence_api.Dockerfile -t horragor-intelligence-api:1.0 . `
   -  lancer => ` docker run --rm --env-file .env.docker -p 8000:8000 horragor-intelligence-api:1.0 `  
   Ouvre ton navigateur sur http://localhost:8000/docs pour vérifier que l'API Intelligence est en ligne.
   - Si on veut tester l'index FAISS dans le conteneur, Pour s'assurer que l'index est bien là, tu peux lancer un shell dans l'image : ` docker run -it --rm --env-file .env horragor-intelligence-api:1.0 sh `  
   Puis dans le shell => ` ls -la /app/data/faiss_index `
   On doit voir les fichiers index.faiss, metadata.json, etc.

3) Dockerfile pour le frontend Streamlit
Le frontend Streamlit est le plus simple des trois conteneurs : il n'a besoin que de Streamlit + d'un client HTTP (requests) pour discuter avec l'API Intelligence.
   - Créer le fichier docker/frontend.Dockerfile

        | Élément | Pourquoi |
        |---|---|
        | **`httpx`** remplace `requests` | le code utilise `import httpx`, pas `requests`. |
        | **`PYTHONPATH=/app`** | Obligatoire car tu fais des imports absolus (`from src.config import ...`). Sans ça, Python ne trouve pas le package `src`. |
        | **`COPY src/ src/`** | le frontend dépend de `src/config.py`. On copie donc tout le dossier `src/`. |

    - build => ` docker build -t horragor-frontend -f docker/frontend.Dockerfile . `
    - lancer => ` docker run -d --name horragor-front-test -p 8501:8501 -e API_BASE_URL=http://host.docker.internal:8000 horragor-frontend `
  
        | Option | Signification |
        |---|---|
        | `-d` | Lance en arrière-plan (tu récupères la main dans le terminal) |
        | `--name horragor-front-test` | Nom du conteneur pour plus facilement le gérer |
        | `-p 8501:8501` | Redirige le port 8501 du conteneur vers ton PC (`localhost:8501`) |
        | `-e API_BASE_URL=http://host.docker.internal:8000` | **Essentiel** : dit au frontend d'appeler ton API qui tourne sur Windows, pas dans le conteneur |
        | `horragor-frontend` | Le nom de l'image qu'on vient de builder |

   - ouvrir le navigateur => http://localhost:8501

## docker-compose.yml ##
### 1. Placement des fichiers
Placez les deux fichiers docker-compose.yml (base) et docker-compose.dev.yml (override) dans le même répertoire que vos fichiers d'environnement :
```
📁 votre-projet/
├── docker-compose.yml           ← configuration "Sujet" / Production
├── docker-compose.dev.yml       ← override développement (ports API temporaires)
├── .env                         ← variables Data API
├── .env.docker                  ← variables Intelligence API
├── docker/                      ← Dockerfiles
│   ├── data_api.Dockerfile
│   ├── intelligence_api.Dockerfile
│   └── frontend.Dockerfile
├── data_api/                    ← code source Data API
```

### 2. Principe de sécurité du réseau
Conformément aux exigences du projet, l'architecture réseau suit cette règle stricte :

| Service | Port interne | Port publié vers l'hôte | Accessible par... |
|---------|--------------|-------------------------|-------------------|
| `data-api` | `8001` | ❌ **Aucun** | Uniquement `intelligence-api` via le réseau Docker |
| `intelligence-api` | `8000` | ❌ **Aucun** | Uniquement `frontend` via le réseau Docker |
| `frontend` | `8501` | ✅ `8501:8501` | Le navigateur de l'utilisateur |



Les conteneurs communiquent entre eux par leur nom de service sur le réseau interne horragor-net :
- Le frontend appelle http://intelligence-api:8000
- L'intelligence appelle http://data-api:8001

Le PC hôte (Windows) ne voit que Streamlit. Les identifiants Supabase et le moteur LLM restent enfermés dans le périmètre Docker.

### 3. Fichier docker-compose.yml (base — mode Production)
Ce fichier définit la configuration sujet. Aucun port critique n'est exposé.

### 4. Fichier docker-compose.dev.yml (override — mode Développement)
Ce fichier ne contient que les différences par rapport au précédent. Docker Compose va les fusionner. Il sert uniquement à ouvrir temporairement les ports des APIs pour consulter la documentation Swagger (/docs) et tester avec Postman.
Créer un fichier nommé exactement docker-compose.dev.yml à côté du premier

Pourquoi ça fonctionne ?Docker Compose lit d'abord le fichier de base, puis applique le fichier d'override. Le docker-compose.dev.yml ajoute les sections ports: manquantes sans écraser le reste de la configuration (réseau, variables, dépendances, etc.).

### 5. Lancer les services
#### Mode "Sujet" / Production (sécurisé, seul Streamlit est visible)
Depuis le répertoire contenant les fichiers .yml :
```
docker compose down
docker compose up -d --build
```
Vérification :
```
docker ps
```
Résultat attendu en production :
```
CONTAINER ID   IMAGE                         PORTS                    NAMES
xxxxxxxxxxxx   horragor-data-api:1.0          <aucun>                  horragor-data
xxxxxxxxxxxx   horragor-intelligence-api:1.0  <aucun>                  horragor-ia
xxxxxxxxxxxx   horragor-frontend:latest       0.0.0.0:8501->8501/tcp   horragor-front
```

| Service | URL | État |
|---|---|---|
| Frontend Streamlit | http://localhost:8501 | ✅ Accessible |
| Data API (Swagger) | http://localhost:8001/docs | ❌ Inaccessible (normal, c'est le but) |
| Intelligence API (Swagger) | http://localhost:8000/docs | ❌ Inaccessible |

Les 3 conteneurs communiquent néanmoins parfaitement entre eux via le réseau interne horragor-net.

#### Mode Développement (accès temporaire aux APIs)
Pour déboguer ou consulter la documentation Swagger des APIs :
```
docker compose down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```
Vérification :
```
docker ps
```
Résultat attendu en développement :
```
CONTAINER ID   IMAGE                         PORTS                    NAMES
xxxxxxxxxxxx   horragor-data-api:1.0          0.0.0.0:8001->8001/tcp   horragor-data
xxxxxxxxxxxx   horragor-intelligence-api:1.0  0.0.0.0:8000->8000/tcp   horragor-ia
xxxxxxxxxxxx   horragor-frontend:latest       0.0.0.0:8501->8501/tcp   horragor-front
```

| Service | URL | État |
|---|---|---|
| Frontend Streamlit | http://localhost:8501 | ✅ Accessible |
| Intelligence API (Swagger) | http://localhost:8000/docs | ✅ Accessible |
| Data API (Swagger) | http://localhost:8001/docs | ✅ Accessible |

### 6. Suivre les logs en temps réel
```
# Logs de l'Intelligence API (backend LLM)
docker compose logs -f intelligence-api

# Logs de tous les services
docker compose logs -f

# Logs d'un service spécifique
docker compose logs -f data-api
docker compose logs -f frontend
```

### 7. Arrêter les services
```
docker compose down
```

Cette commande supprime les containers mais conserve le réseau horragor-net.
Pour supprimer aussi le réseau :
```
docker compose down --remove-orphans
docker network rm horragor-net
```

Pour redémarrer après un arrêt :
```
docker compose up -d
```

### 8. Récapitulatif des modes
| Fichier(s) utilisé(s) | Commande | Ports ouverts | Usage |
|-----------------------|----------|---------------|-------|
| `docker-compose.yml` seul | `docker compose up -d` | Seul `8501` | **Production / Sujet** — respect strict du périmètre de sécurité |
| Base + `docker-compose.dev.yml` | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` | `8501`, `8000`, `8001` | **Développement** — test des APIs via Swagger/Postman sans toucher au code |


------- si besoin -----------------

### 9. Configurer Ollama pour écoute sur toutes les interfaces

Par défaut, Ollama écoute uniquement sur `127.0.0.1` (localhost). Les containers Docker **ne peuvent pas** y accéder. Il faut qu'il écoute sur `0.0.0.0`.

#### A. Arrêter Ollama proprement

Cliquez-droit sur l'icône Ollama dans la barre des tâches Windows → **Quitter**.

#### B. Configurer la variable d'environnement `OLLAMA_HOST`

**Option 1 — Ligne de commande (session courante) :**
```cmd
set OLLAMA_HOST=0.0.0.0
```

**Option 2 — Persistante (recommandée) :**
1. `Win + R` → tapez `sysdm.cpl` → **Entrée**
2. Onglet **Avancé** → bouton **Variables d'environnement**
3. Section **Utilisateur** → **Nouvelle…**
   - Nom de la variable : `OLLAMA_HOST`
   - Valeur de la variable : `0.0.0.0`
4. Validez sur **OK** → **OK** → **OK**
5. Redémarrez votre PC pour que la variable soit prise en compte.

#### C. Relancer Ollama

Depuis le menu Démarrer Windows, lancez **Ollama** à nouveau.

#### D. Vérifier avec `netstat`

Ouvrez un **nouveau** terminal (CMD ou PowerShell) :

```cmd
netstat -an | findstr 11434
```

**Résultat attendu :**
```
TCP    0.0.0.0:11434         0.0.0.0:0              LISTENING
```

> ✅ **C'est bon !** Ollama écoute maintenant sur toutes les interfaces.
> 
> ❌ **Si vous voyez `127.0.0.1:11434`** → le PC n'a pas redémarré après le changement de variable d'environnement. Redémarrez le PC.

#### E. Vérifier qu'Ollama répond

```cmd
curl http://localhost:11434/api/tags
```
## 7.2 Authentification par Refresh Tokens ##

Juste avant on a une architecture en 3 couches isolées :
```
[Navigateur] ──► [Streamlit :8501] ──► [Intelligence API :8000] ──► [Data API :8001] ──► [Supabase]
                    (vitrine)            (cerveau)                   (coffre-fort)
```

Grace  a Docker on a un mur d'enceinte : seul le port 8501 (Streamlit) est ouvert vers l'extérieur. Les APIs sont invisibles depuis le PC hôte.

Mais il reste deux failles. C'est exactement ce que 7.2 et 7.3 viennent combler.

7.2 — Authentification : "Qui a le droit d'entrer ?"

Le problème actuel
Ton mur Docker protège les APIs 8000 et 8001 du monde extérieur. Mais la porte d'entrée (Streamlit → 8000/chat) est grande ouverte. 
Imagine une analogie : ton château hanté a de superbes remparts (Docker), mais la grande porte n'a pas de serrure. N'importe qui qui atteint le frontend peut envoyer des requêtes à ton cerveau LLM.

Pourquoi c'est un problème concret ?
- Coût / Abus : ton LLM (Ollama) consomme des ressources. Sans authentification, n'importe qui peut spammer /chat et faire tourner ton GPU à fond.
- Contrôle d'accès : tu veux que seul un utilisateur connecté puisse discuter avec le chroniqueur.
- Traçabilité : savoir qui fait quoi.

Pourquoi des Refresh Tokens et pas juste un mot de passe ?

C'est là que le sujet devient intéressant. Il y a deux clés, pas une :

| Token | Durée de vie | Rôle | Analogie |
|---|---|---|---|
| **access_token** | **Courte** (ex. 15 min) | Prouve ton identité à chaque requête `/chat` | Un **bracelet de festival** valable une journée |
| **refresh_token** | **Longue** (ex. 7 jours) | Sert à obtenir un nouveau access_token sans se reconnecter | Ta **carte d'identité** au vestiaire |

Pourquoi cette complexité ? À cause d'un dilemme de sécurité :
- Si on faisait UN SEUL token à longue durée : pratique (pas besoin de se reconnecter), mais dangereux — s'il est volé, le voleur a accès pendant 7 jours.
- Si on faisait UN SEUL token à courte durée : sécurisé, mais pénible — l'utilisateur devrait retaper son mot de passe toutes les 15 minutes.

La solution des 2 tokens combine le meilleur des deux mondes :
```
Connexion (login avec mot de passe)
   │
   └──► access_token (15 min) + refresh_token (7 jours)
          │
          ├── Chaque /chat utilise l'access_token
          │
          └── Quand l'access_token expire (au bout de 15 min) :
                 → le refresh_token demande un NOUVEL access_token
                 → SANS retaper le mot de passe
```
L'access_token court limite les dégâts en cas de vol (expire vite). Le refresh_token long évite de retaper le mot de passe sans arrêt. C'est le standard de l'industrie (OAuth2).

```
Streamlit                          Intelligence API
   │                                     │
   │  POST /auth/login (user+pass)       │
   │────────────────────────────────────►│  vérifie les identifiants
   │  ◄──── access_token + refresh_token │  (fabrique 2 JWT)
   │                                     │
   │  POST /chat  (Bearer access_token)  │
   │────────────────────────────────────►│  middleware valide le JWT ✅
   │                                     │
   │  ... 15 min plus tard, access expiré │
   │  POST /auth/refresh (refresh_token) │
   │────────────────────────────────────►│  fabrique un NOUVEL access_token
   │  ◄──────────── nouvel access_token  │
```

Les 3 pièces à construire (comme dit le sujet)
1) POST /auth/login → tu envoies user+password, tu reçois les 2 tokens. (La serrure de la porte.)
2) Intercepteur Streamlit → le frontend stocke les tokens et rafraîchit automatiquement en coulisses. (L'utilisateur ne voit rien, c'est transparent.)
3) Middleware FastAPI → chaque appel à /chat vérifie « ce bracelet est-il valide ? ». Si non → 401. (Le videur à l'entrée.)

Pourquoi "utilisateur unique via .env" ? Parce que le sujet dit clairement : c'est un projet de formation. Construire une vraie base de données d'utilisateurs (inscription, hachage bcrypt, récupération de mot de passe...) serait hors-sujet. On veut juste démontrer que tu maîtrises le mécanisme JWT, pas gérer 10 000 comptes.

On va construire l'authentification en 4 briques, dans cet ordre logique :
```
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 : La config (.env + config.py)                      │
│  → Définir l'utilisateur unique + les secrets JWT           │
├─────────────────────────────────────────────────────────────┤
│  ÉTAPE 2 : Le module auth (src/auth/security.py)             │
│  → Fabriquer/valider les tokens (access + refresh)          │
├─────────────────────────────────────────────────────────────┤
│  ÉTAPE 3 : Les routes (POST /auth/login, /auth/refresh)      │
│  → + protéger /chat avec une dépendance FastAPI             │
├─────────────────────────────────────────────────────────────┤
│  ÉTAPE 4 : L'intercepteur Streamlit (app_frontend.py)        │
│  → Login + stockage tokens + refresh automatique            │
└─────────────────────────────────────────────────────────────┘
```
On utilisera :
- PyJWT = fabriquer les tokens (les « badges » une fois connecté).
- bcrypt = stocker/vérifier le mot de passe sans le mettre en clair.


### ÉTAPE 1 : La config (.env + config.py) 

1) Installer les dépendances => ` uv add PyJWT bcrypt `
2) Générer tes secrets (avec uv run) 
   - La clé de signature JWT : 
   dans l'environnement du projet ` uv run python -c "import secrets; print(secrets.token_hex(32))" `  
   Copie le résultat → ira dans JWT_SECRET_KEY. => 19360c6f5dd8cf8cd986f7f50593aac2454ba081ca86382ae80a14fd72150c84
   - Le hash bcrypt de ton mot de passe : ` uv run python -c "import bcrypt; print(bcrypt.hashpw('motdepasse123'.encode(), bcrypt.gensalt()).decode())" `   
    On obtiendra un hash  $ 2b $ 12$... → à coller dans AUTH_PASSWORD_HASH => $2b$12$LxWJmxxqFrTbAEsCBK5LqOLwilyxqfsLNvKBi/jD59l4XUslMrC02
3) Ajouter les variables dans .env et .env.example
   - dans le .env :  
        ```
        # ── Authentification JWT (Phase 7.2) ──
        JWT_SECRET_KEY=colle_ici_le_token_hex_généré_au_1-b-①
        AUTH_USERNAME=admin
        AUTH_PASSWORD_HASH='colle_ici_le_hash_bcrypt_généré_au_1-b-②'
        ```
   - dans le .env.example :
        ```
        # ═══════════════════════════════════════════════════════════
        #  Authentification JWT (Phase 7.2) — OBLIGATOIRE
        # ═══════════════════════════════════════════════════════════
        # Clé secrète de signature des tokens (générer via :
        #   python -c "import secrets; print(secrets.token_hex(32))")
        JWT_SECRET_KEY=[GENERER-UNE-CLE-SECRETE-ALEATOIRE]

        # Identifiant unique de l'utilisateur autorisé
        AUTH_USERNAME=admin

        # Hash bcrypt du mot de passe (générer via :
        #   python -c "import bcrypt; print(bcrypt.hashpw('votre_mot_de_passe'.encode(), bcrypt.gensalt()).decode())")
        AUTH_PASSWORD_HASH='[GENERER-UN-HASH-BCRYPT]'
        ```
    - dans le .env.docker rajouter 
        ```
        # ── Authentification JWT (Phase 7.2) ──
        JWT_SECRET_KEY=colle_ici_le_token_hex_généré_au_1-b-①
        AUTH_USERNAME=admin
        AUTH_PASSWORD_HASH='colle_ici_le_hash_bcrypt_généré_au_1-b-②'
        ACCESS_TOKEN_EXPIRE_MINUTES=15
        REFRESH_TOKEN_EXPIRE_DAYS=7
        ```
4) Ajouter le bloc dans src/config.py
    ```
    # ═══════════════════════════════════════════════════════════════
    # Authentification JWT (Phase 7.2)
    # ═══════════════════════════════════════════════════════════════
    # Système d'authentification par Refresh Tokens verrouillant les
    # échanges entre l'IHM Streamlit et l'API Intelligence, tel qu'exigé
    # par le cahier des charges (Épilogue MLOps, Couche Intelligence).
    #
    # Pour un projet de formation, un utilisateur UNIQUE est défini via
    # ces variables d'environnement (pas de gestion multi-utilisateurs).
    # ═══════════════════════════════════════════════════════════════

    # Clé secrète servant à SIGNER les JWT (HMAC-SHA256).
    # Doit rester strictement confidentielle : quiconque la connaît peut
    # forger des tokens valides.
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_EN_PRODUCTION")

    # Algorithme de signature symétrique (le standard pour un secret unique).
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    # Durée de vie de l'access_token en MINUTES (court : sécurité renforcée).
    # Si volé, il n'est exploitable que quelques minutes.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    )

    # Durée de vie du refresh_token en JOURS (long : confort utilisateur).
    # Il permet de régénérer des access_token sans se reconnecter.
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(
        os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
    )

    # Identifiant de l'unique utilisateur autorisé.
    AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "admin")

    # Hash bcrypt du mot de passe (JAMAIS le mot de passe en clair).
    # La vérification se fait via bcrypt.checkpw().
    AUTH_PASSWORD_HASH: str = os.getenv("AUTH_PASSWORD_HASH", "")
    ```

5) modifier le fichier "docker-compose.yml", ajouter "env_file" a tous les service :
    ```
    services:
    # ── Service 1 : Data API ────────────────────────────────────────────────
    data-api:
        build:
        context: .
        dockerfile: docker/data_api.Dockerfile
        image: horragor-data-api:1.0
        container_name: horragor-data
        pull_policy: never
        env_file:
        - .env.docker              # ← CHANGE .env → .env.docker
        networks:
        - horragor-net
        restart: unless-stopped

    # ── Service 2 : Intelligence API ────────────────────────────────────────
    intelligence-api:
        build:
        context: .
        dockerfile: docker/intelligence_api.Dockerfile
        image: horragor-intelligence-api:1.0
        container_name: horragor-ia
        pull_policy: never
        env_file:
        - .env.docker              # ← ✅ BON
        networks:
        - horragor-net
        depends_on:
        - data-api
        extra_hosts:
        - "host.docker.internal:host-gateway"
        environment:
        - OLLAMA_BASE_URL=http://host.docker.internal:11434
        restart: unless-stopped

    # ── Service 3 : Frontend Streamlit ──────────────────────────────────────
    frontend:
        build:
        context: .
        dockerfile: docker/frontend.Dockerfile
        image: horragor-frontend:latest
        container_name: horragor-front
        pull_policy: never
        env_file:
        - .env.docker              # ← AJOUTE CETTE LIGNE
        ports:
        - "8501:8501"
        networks:
        - horragor-net
        depends_on:
        - intelligence-api
        environment:
        - API_BASE_URL=http://horragor-ia:8000
        restart: unless-stopped

    networks:
    horragor-net:
        driver: bridge
    ```

6) relancer les containeurs
    ```
    docker compose -f docker-compose.yml -f docker-compose.dev.yml down
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
    ```

### ÉTAPE 2 : src/auth/security.py — le module qui fabrique et valide réellement les tokens. ##

1) Crée l'arborescence
   - src\auth\__init__.py
   - src\auth\security.py avec son code
2) Petit test rapide pour valider que tout s'importe bien : ` uv run python -c "from src.auth.security import create_access_token; print(create_access_token('horagor')[:40], '...')" `  
Cela doit normalement afficher un début de token (eyJ...)

### ÉTAPE 3 : Les routes /auth/login et /auth/refresh
C'est ici qu'on branche security.py à FastAPI pour que le frontend puisse récupérer ses tokens.

1) Crée l'arborescence
   - src\api\__init__.py
   - src\api\auth.py avec son code
2) Enregistrer le routeur auth dans src/main.py
   - Ajouter l'import (après les imports FastAPI)
        ```
        from __future__ import annotations
        from datetime import datetime

        import asyncio
        import uuid
        from langchain_core.messages import HumanMessage
        from contextlib import asynccontextmanager
        from typing import Any, AsyncGenerator
        from fastapi import FastAPI, HTTPException, status, Depends
        from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
        from pydantic import BaseModel, Field
        from src.api.auth import router as auth_router
        from src.auth.security import verify_access_token
        ```
   - Enregistre le routeur (après la création de l'app, avant ou après le lifespan)
        ```
        app = FastAPI(
            title="HorRAGor API",
            description="API backend multi-agent pour le chroniqueur de cinéma d'horreur.",
            version="0.4.0",
            lifespan=lifespan,
        )

        # Enregistre le routeur d'authentification  ← NOUVEAU
        app.include_router(auth_router)
        ```
   -  Dans la fonction get_current_user (ligne ~130), remplacer :  
        ` async def get_current_user(credentials: HTTPAuthCredentials = Depends(HTTPBearer())) -> str: `  
        par  
        ` async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> str: `  
   -  Ajoute APRÈS la création de l'app (ou à côté de ta route /chat existante) :
        ```
        # ═══════════════════════════════════════════════════════════════
        # Route protégée par JWT (Phase 7.2)
        # ═══════════════════════════════════════════════════════════════

        @app.post("/chat")
        async def chat(
            message: str,
            credentials: HTTPAuthCredentials = Depends(HTTPBearer()),
            # ... autres paramètres existants (session_id, etc.)
        ):
            """
            Endpoint protégé par JWT.
            
            Nécessite un header Authorization:
                Authorization: Bearer {access_token}
            
            Le token est validé automatiquement via verify_access_token().
            Si le token est invalide ou expiré → 401 Unauthorized.
            """
            try:
                # Valide le token et récupère le username
                username = verify_access_token(credentials.credentials)
                print(f"✅ Utilisateur authentifié : {username}")
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token invalide ou expiré : {str(e)}"
                )
            
            # ← Ton code de chat existant commence ici
            # ...
        ```
   -  Rebuild les conteneur : 
        ```
        docker compose -f docker-compose.yml -f docker-compose.dev.yml down
        docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
        ```
3) testes :
   - Test 1 : vérifier que verify_access_token s'importe  
    ` uv run python -c "from src.auth.security import verify_access_token; print('✅ verify_access_token importée avec succès')" `
   - Test 2 : Login valide
        ```
        curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\": \"admin\", \"password\": \"motdepasse123\"}"
        ```
        Réponse attendue (200) :
        ```
        {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "bearer"
        }
        ```
   - Test 3 : Login invalide (mauvais mot de passe)
        ```
        curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\": \"admin\", \"password\": \"MAUVAIS\"}"

        ```
        Réponse attendue (401) :
        ```
        {
        "detail": "Nom d'utilisateur ou mot de passe incorrect."
        }
        ```
   - Test 4 : Refresh token
        On récupère le refresh_token du test 1, puis :
        ```
        curl -X POST http://localhost:8000/auth/refresh -H "Content-Type: application/json" -d "{\"refresh_token\": \"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ...\"}"
        ```
        Réponse attendue (200) :
        ```
        {
        "access_token": "eyJhbGciOiJIUzI1NiIs... (NOUVEAU)",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs... (INCHANGÉ)",
        "token_type": "bearer"
        }
        ```


   - Test 5 : Appel /chat SANS token (doit retourner 401)
        ```
        curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"message\": \"Parle-moi de Saw\"}"
        ```
        Réponse attendue (401) :
        ```
        {
        "detail": "Token invalide ou expiré : ..."
        }
        ```
   - Test 6 : Appel /chat AVEC token (doit marcher)
        ```
        curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\": \"admin\", \"password\": \"motdepasse123\"}"

        curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -H "Authorization: Bearer TON_ACCESS_TOKEN_ICI" -d "{\"message\": \"Parle-moi de Saw\"}"
        ```

### ÉTAPE 4 — Sécuriser le frontend Streamlit ###
Maintenant que le backend exige un token, ton Streamlit ne peut plus appeler /chat directement (il recevrait 401). Il faut :
- Page de login dans Streamlit (username + password → appel /auth/login)
- Stocker les tokens dans st.session_state
- Ajouter le header Authorization: Bearer ... à chaque appel /chat
- (Bonus) Refresh automatique quand l'access_token expire (au bout de 15 min)

 Plan de transformation

✅ Ajouter une page de login (à afficher avant le chat)  
✅ Stocker access_token + refresh_token dans st.session_state  
✅ Modifier call_chat_api() pour envoyer le header Authorization  
✅ Ajouter un intercepteur de refresh (gestion du 401 + retry auto)  
✅ Bouton de déconnexion  

1) modifier app_frontend.py
   - ajout de :

        | Fonctionnalité | Code |
        |---|---|
        | 🔐 Login → `/auth/login` | `login()` |
        | 🔄 Refresh auto → `/auth/refresh` | `refresh_access_token()` + intercepteur dans `call_chat_api()` |
        | 📌 Stockage tokens | `st.session_state.access_token/refresh_token` |
        | 🚪 Logout | `logout()` |
        | 🔁 Retry 401 | `call_chat_api()` avec 2 tentatives |
    
   - faire :
        ```
        docker compose -f docker-compose.yml -f docker-compose.dev.yml down
        docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
        ```

   - tester : 
       ouvrir http://localhost:8501

        On devrait avoir :

            ❌ Une page de login (pas le chat)  
            Identifiant : admin  
            Mot de passe : motdepasse123  

            Après login :
            ✅ Page de chat normale
            ✅ Bouton "Se déconnecter" dans la sidebar


2) Refresh automatique quand l'access_token expire (au bout de 15 min)
Plan :
   - Décoder le JWT pour extraire le timestamp exp (expiration)
   - Vérifier l'expiration au début de chaque appel /chat
   - Si le token expire dans moins de X secondes → refresh automatique
   - Afficher l'expiration dans le sidebar (bonus UX)

    Donc modifier app_fontend.py :
    ```
    app_frontend.py
    ├── Imports (httpx, streamlit, etc.)
    ├── st.set_page_config()  ← DOIT ÊTRE PREMIER
    │
    ├── ════════════════════════════════════════════
    ├── UTILITAIRES JWT  ← 🔴 AJOUTER ICI
    ├── ════════════════════════════════════════════
    │   ├── decode_jwt_payload()
    │   ├── get_token_expiration()
    │   ├── is_token_expired_soon()
    │   └── get_token_remaining_time()
    │
    ├── ════════════════════════════════════════════
    ├── INITIALISATION SESSION STATE
    ├── ════════════════════════════════════════════
    │   └── init_session_state()
    │
    ├── ════════════════════════════════════════════
    ├── AUTHENTIFICATION
    ├── ════════════════════════════════════════════
    │   ├── login()
    │   ├── refresh_access_token()
    │   └── logout()
    │
    ├── ════════════════════════════════════════════
    ├── APPEL API  ← 🔴 MODIFIER ICI
    ├── ════════════════════════════════════════════
    │   └── call_chat_api()  ← Ajouter vérification proactive
    │
    ├── ════════════════════════════════════════════
    ├── AFFICHAGE
    ├── ════════════════════════════════════════════
    │   ├── _render_source()
    │   ├── display_chat_history()
    │   └── handle_user_input()
    │
    ├── ════════════════════════════════════════════
    ├── PAGE DE LOGIN
    ├── ════════════════════════════════════════════
    │   └── show_login_page()
    │
    ├── ════════════════════════════════════════════
    ├── PAGE CHAT  ← 🔴 MODIFIER ICI (sidebar)
    ├── ════════════════════════════════════════════
    │   └── show_chat_page()
    │
    ├── ════════════════════════════════════════════
    ├── POINT D'ENTRÉE
    ├── ════════════════════════════════════════════
    │   └── main()
    │
    └── if __name__ == "__main__": main()
    ```

   - faire :  
        ```
        docker compose -f docker-compose.yml -f docker-compose.dev.yml down
        docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
        ```

    - tester :  
          ouvrir http://localhost:8501
          Regarder dans le sidebar : tu dois voir ⏱️ 14m 32s (ou similaire)  
          Chaque appel /chat vérifiera si le token expire dans < 5 min  
          Si oui, refresh automatique avant même que ça échoue ! ✨  

## 7.3 Communication chiffrée ##

Le sujet dit : « L'interface utilisateur doit elle aussi être isolée dans son conteneur et assurer une communication chiffrée et sécurisée vers l'API d'IA. » => Direction précise : « vers l'API d'IA » (Streamlit → Intelligence API).

Le problème actuel  
Même avec l'authentification (7.2), tes tokens et tes messages voyagent en HTTP clair entre Streamlit et l'API.

Analogie : tu as maintenant une serrure sur ta porte (7.2), mais tu cries ton mot de passe à voix haute dans la rue en entrant. Quelqu'un qui écoute (attaque Man-in-the-Middle) peut intercepter :
- Ton mot de passe au moment du login.
- Tes tokens (et donc se faire passer pour toi).
- Le contenu de tes conversations.

La solution : TLS (le "S" de HTTPS)  
Le TLS chiffre tout ce qui circule sur le fil. Même si quelqu'un intercepte les paquets, il ne voit que du charabia illisible.
```
SANS TLS (http://) :   "password=dracula1897"   ← lisible par un espion
AVEC TLS (https://) :  "x9$Kf#2@..."             ← charabia chiffré
```

L'objectif passer de :  
` Streamlit  ──── HTTP (clair) ────►  API IA   ❌ Espionnable `  
vers  
` Streamlit  ──── HTTPS (TLS) ────►  API IA   ✅ Chiffré `

Donc le flux a chiffrer:
```
Streamlit (app_frontend.py)
   │  API_BASE_URL=http://horragor-ia:8000   ← à passer en https://
   ▼
Intelligence API (src/main.py sur port 8000)  ← à passer en TLS
```

Pourquoi "auto-signé" ou "reverse proxy local" suffit ?
Voici la nuance importante que le sujet souligne :
| Type de certificat | Qui le garantit ? | Usage |
|---|---|---|
| **Auto-signé** | Toi-même (ton PC) | Démo / formation ✅ |
| **Certificat valide** (Let's Encrypt, etc.) | Une autorité de confiance reconnue | Vraie production 🏢 |

Un certificat auto-signé chiffre tout aussi bien la communication. Sa seule "faiblesse" : le navigateur affiche un avertissement (« connexion non sécurisée ») car personne d'officiel ne garantit que tu es bien qui tu prétends être. Pour une démo locale, c'est parfaitement suffisant — le chiffrement fonctionne, c'est ce qui compte.

C'est pour ça que le sujet demande explicitement de documenter que « la vraie production utiliserait un certificat valide ». On te teste sur ta compréhension, pas sur ta capacité à acheter un certificat.

Les options proposées par le sujet
1) Certificat auto-signé directement sur Uvicorn (le plus simple).
2) Reverse proxy TLS (Traefik ou Nginx) : un conteneur supplémentaire qui gère le HTTPS et redirige vers tes APIs. Plus proche de la "vraie" production.

On ne fera que le certificat auto-signé directement par uvicorn.

Plan d'action :

| # | Action | Fichier concerné |
|---|---|---|
| **1** | 🐍 Générer `cert.pem` + `key.pem` en Python | Nouveau : `scripts/generate_cert.py` |
| **2** | 📁 Copier les certs + ajouter options TLS à Uvicorn | `intelligence_api.Dockerfile` |
| **3** | 🔗 Passer `API_BASE_URL` en `https://` + accepter cert auto-signé | `docker-compose.yml` + `app_frontend.py` |
| **4** | 📄 Documenter (prod = vrai certificat) | README |

1) Générer le certificat

    un certificat TLS est composé de 2 fichiers :
    | Fichier | Rôle | Analogie |
    |---|---|---|
    | **`key.pem`** (clé privée) | Déchiffre les messages. **SECRET** 🔒 | Ta clé de maison (à ne jamais donner) |
    | **`cert.pem`** (certificat public) | Prouve ton identité + chiffre. **PUBLIC** 📢 | Ta carte d'identité (montrable) |

    Il faut distinguer 2 choses différentes :
    | Étape | Rôle | Outil |
    |---|---|---|
    | **1. Générer** le certificat (`.pem`) | Créer les fichiers `key.pem` + `cert.pem` | OpenSSL (ou Python) |
    | **2. Utiliser** le certificat | Uvicorn charge les fichiers et chiffre | Uvicorn |

    Le fonctionnement : 
      1. Streamlit se connecte à l'API
      2. L'API montre son cert.pem (« voici mon identité »)
      3. Streamlit chiffre les données avec la clé publique du cert
      4. Seule l'API peut déchiffrer avec sa key.pem privée
      5. ✅ Communication sécurisée établie

    - Générer le certificat en Python  
        ` uv pip install cryptography `  
        ajouter le script dans " scripts/generate_cert.py "
        Lance le script : ` python scripts/generate_cert.py `  
        Vérifie que le dossier certs/ contient bien key.pem et cert.pem

    Details importants :
    - Le Common Name = horragor-ia => C'est crucial que le  docker-compose.yml, Streamlit appelle l'API via : ` API_BASE_URL=http://horragor-ia:8000 `. Le certificat doit correspondre à ce nom horragor-ia, sinon la validation TLS échoue.
    - Les SAN (Subject Alternative Names) => On ajouté horragor-ia et localhost pour que ça marche : En Docker (via horragor-ia) et En local dev (via localhost)

2) Configurer Uvicorn en HTTPS  
   - On modifie " docker/intelligence_api.Dockerfile"  pour que sa commande de lancement charge le certificat :
       ```
       CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", \
           "--ssl-keyfile", "/app/certs/key.pem", \
           "--ssl-certfile", "/app/certs/cert.pem"]
       ```
   - On modifie "docker-compose.yml" :  
       1) Ajouter le volume certs car on a choisi la stratégie B (volume monté) : le certificat n'est PAS dans l'image Docker, il est "branché" au démarrage depuis ton PC.
           ```
           volumes:
           - ./certs:/app/certs:ro
           ```
           - ./certs = le dossier sur ton PC (celui qui contient key.pem + cert.pem)  
           - /app/certs = où ces fichiers apparaissent DANS le conteneur (c'est le chemin que ton Dockerfile utilise : /app/certs/key.pem)  
           - :ro = read-only (le conteneur peut lire mais pas modifier → sécurité)  

           👉 Le lien avec ton Dockerfile : ta commande CMD cherche /app/certs/key.pem. Ce volume est ce qui remplit ce dossier /app/certs. Sans lui, le fichier n'existe pas → Uvicorn plante au démarrage.

       2) Passer API_BASE_URL en https://  
           Dans le service frontend, Streamlit appelle l'API. Comme l'API est maintenant en HTTPS, l'URL doit changer :
           ```
           # AVANT
           - API_BASE_URL=http://horragor-ia:8000
           # APRÈS
           - API_BASE_URL=https://horragor-ia:8000
           ```
   - Il y a un piège classique qui va arriver : ton certificat est auto-signé. Quand Streamlit (via httpx) va appeler https://horragor-ia:8000, httpx va refuser le certificat par défaut avec une erreur du type : `
   httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] `. C'est normal et attendu : httpx ne fait pas confiance à un certificat qu'aucune autorité officielle n'a signé. On réglera ça à l'étape 3 dans app_frontend.py en disant à httpx de faire confiance à TON cert.pem (le bon comportement) — on n'utilisera PAS verify=False (mauvaise pratique).

3) Configurer httpx dans app_frontend.py pour qu'il fasse confiance à ton certificat.

- créer le client httpx à 3 endroits :
    ```
    with httpx.Client(timeout=API_TIMEOUT) as client:   # dans login()
    with httpx.Client(timeout=API_TIMEOUT) as client:   # dans refresh_access_token()
    with httpx.Client(timeout=API_TIMEOUT) as client:   # dans call_chat_api()
    ```
- dire à httpx de faire confiance à TON cert.pem  
    Le paramètre verify= de httpx.Client accepte un chemin vers un certificat de confiance. On lui passe ton cert.pem.

    Ajouter une constante en haut du fichier :
    ```
    import os

    # 🔒 Certificat auto-signé de l'API Intelligence (TLS, Phase 7.3).
    # httpx doit faire confiance à CE certificat précis (pas verify=False !).
    # Chemin dans le conteneur frontend → à monter via volume dans docker-compose.
    SSL_VERIFY = os.getenv("SSL_CERT_PATH", "/app/certs/cert.pem")
    ```
- Ajouter verify=SSL_VERIFY aux 3 clients 
` with httpx.Client(timeout=API_TIMEOUT, verify=SSL_VERIFY) as client: `

- Conséquence importante : le frontend a AUSSI besoin du cert  
    Le conteneur frontend doit accéder à /app/certs/cert.pem. Il faut donc monter le même volume sur le service frontend dans docker-compose.yml :
    ```
    frontend:
        ...
        environment:
        - API_BASE_URL=https://horragor-ia:8000
        - SSL_CERT_PATH=/app/certs/cert.pem
        volumes:
        - ./certs:/app/certs:ro
    ```

- lancer : ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build `  
    et verifier les logs ` docker logs horragor-ia | tail -20 `  
    On devra voir Uvicorn running on https://0.0.0.0:8000 (le https confirme que TLS est actif ✅).

- Ouvrir  http://localhost:8501 et teste le login :  
    Identifiant : admin  
    Mot de passe : motdepasse123

- Vérification :  
` docker logs -f horragor-ia ` on doit voir 
` INFO:     Uvicorn running on https://0.0.0.0:8000 `

Sreamlit lui-même reste en HTTP (:8501), ce qui est normal. Voici pourquoi :
```
┌─────────────────┐
│  Navigateur     │
│  (sur ton PC)   │
└────────┬────────┘
         │
         │ HTTP (normal, pas HTTPS)
         ↓
┌─────────────────────────────┐
│  Streamlit Frontend         │
│  http://localhost:8501      │ ← C'est bon comme ça
│  (conteneur horragor-front) │
└─────────┬───────────────────┘
          │
          │ HTTPS (certificat auto-signé)
          │ Communication interne au réseau Docker
          ↓
┌─────────────────────────────┐
│  Intelligence API (Uvicorn) │
│  https://horragor-ia:8000   │ ← C'est ça qui est en HTTPS
│  (conteneur horragor-ia)    │
└─────────────────────────────┘
```
Streamlit n'a pas besoin d'être en HTTPS parce que :
- C'est une application locale (sur ta machine)
- Le navigateur accède via localhost (réseau local)
- La sécurité TLS se fait entre les conteneurs Docker (réseau interne)

Le certificat auto-signé (cert.pem) est uniquement pour l'API Intelligence (communication conteneur-à-conteneur).

# Phase 8 : Monitoring avec Langfuse, Loguru et la stack Prometheus #
## 8.1 Langfuse ##

sources :
- https://github.com/langfuse/langfuse
- https://langfuse.com/
- https://www.datacamp.com/tutorial/langfuse?utm_cid=23552157100&utm_aid=188237542690&utm_campaign=230119_1-ps-other~dsa-tofu~ai_2-b2c_3-emea_4-prc_5-na_6-na_7-le_8-pdsh-go_9-nb-e_10-na_11-na&utm_loc=9218685-&utm_mtd=-c&utm_kw=&utm_source=google&utm_medium=paid_search&utm_content=ps-other~emea-en~dsa~tofu~tutorial~artificial-intelligence&gad_source=1&gad_campaignid=23552157100&gbraid=0AAAAADQ9WsFFDQVglWF5tu8tt0306wgvu&gclid=CjwKCAjwvZHTBhAlEiwA1ug5P3jZNXH5qRbSxZVTJ6T50ft5pfNSnFIqH8WAUscK_PfiI4tjlCnnVhoCx68QAvD_BwE
- 

Langfuse est un outil de monitoring open-source qui trace, évalue et calcule le coût
de chaque étape de vos agents LLM en temps réel.

Imagine que ton agent HorRAGor est une boîte noire. Quand un utilisateur pose une question, il se passe plein de choses invisibles :
```
Question utilisateur
   ↓
[RAG Node]      → cherche dans FAISS (combien de temps ? quels résultats ?)
   ↓
[Router]        → décide : enrichir via web ou pas ? (pourquoi cette décision ?)
   ↓
[Scraper Node]  → va sur Wikipedia (a-t-il réussi ? combien de temps ?)
   ↓
[Narration]     → génère la réponse avec le LLM (combien de tokens ? quel coût ?)
   ↓
Réponse finale
```

Langfuse est un outil d'observabilité (observability) spécialisé pour les applications LLM. Langfuse va montrer :

| Ce que tu vois | Utilité concrète |
|---|---|
| 🕐 **Latence par étape** | "Le RAG prend 8s, c'est lui le goulot d'étranglement" |
| 🔢 **Tokens consommés** | "Cette réponse a coûté 1200 tokens" |
| 📊 **Traces complètes** | Voir l'arbre RAG → Router → Narration pour chaque requête |
| 🐛 **Erreurs** | "Le scraper a planté sur cette question précise" |
| 💬 **Prompts exacts** | Voir le prompt EXACT envoyé au LLM (très utile pour débugger) |


Vocabulaire important
- Trace : l'enregistrement complet d'une requête (de la question à la réponse)
- Span : une sous-étape dans une trace (ex: le RAG Node est un span)
- CallbackHandler : le "mouchard" qu'on branche sur LangGraph pour qu'il envoie automatiquement les infos à Langfuse

Plan d'action :

| Étape | Action | Fichier concerné |
|---|---|---|
| **A** | Installer Langfuse en local (Docker) | Terminal |
| **B** | Créer un compte local + projet → récupérer les clés | Navigateur (`localhost:3000`) |
| **C** | Installer le package Python `langfuse` | `pyproject.toml` |
| **D** | Ajouter les clés dans les fichiers `.env` | `.env`, `.env.example`, `.env.docker` |
| **E** | Configurer `src/config.py` | `src/config.py` |
| **F** | Créer un helper Langfuse | `src/observability/langfuse_client.py` |
| **G** | Brancher le callback dans `main.py` | `src/main.py` |
| **H** | Tester et vérifier dans l'interface | Navigateur |

### étape A : Installer Langfuse en local

La distinction fondamentale : Langfuse Serveur vs Langfuse Client

| | Le **SERVEUR** Langfuse | Le **CLIENT** Langfuse |
|---|---|---|
| **C'est quoi ?** | L'application web complète (le `git clone`) | Le petit package Python (`uv add langfuse`) |
| **Rôle** | Stocke et affiche les traces (l'interface sur `:3000`) | Envoie les traces depuis ton code |
| **Où ?** | Un **service externe** qui tourne à côté | **Dans** ton projet `horragor-project` |
| **Analogie** | Le **serveur de mails** (Gmail) | Ton **application mail** (Outlook) |

- Seul le CLIENT (uv add langfuse) va dans ton projet.
- Le SERVEUR (git clone) est une infrastructure séparée, comme ta base Supabase.

=>  on n'installera pas le serveur dans notre projet horragor-project/ mais dans un un projet (dossier) "langfuse" a part:

```
C:\Users\toi\Projets\           ← Le  dossier de travail général
│
├── horragor-project/           ← Le projet (inchangé)
│   ├── src/
│   ├── docker-compose.yml
│   └── ...
│
└── langfuse/                   ← Le git clone VA ICI (À CÔTÉ, pas dedans !)
    ├── docker-compose.yml       ← Le compose de Langfuse
    └── ...
```

```
┌─────────────────────────────────────────────────────────┐
│ DISQUE                                              │
│                                                          │
│  ┌──────────────────────┐    ┌────────────────────────┐ │
│  │  horragor-project/   │    │  langfuse/             │ │
│  │                      │    │                        │ │
│  │  uv add langfuse ────┼───►│  (serveur sur :3000)   │ │
│  │  (le CLIENT)         │    │  docker compose up -d  │ │
│  │                      │    │                        │ │
│  │  Le code envoie     │    │  reçoit et affiche     │ │
│  │  les traces  ───────────► │  les traces            │ │
│  └──────────────────────┘    └────────────────────────┘ │
│                                                          │
└──────────────────────────────────────────────────────────┘
```
Pour information un seul serveur Langfuse (ici en local) peut suivre plusieurs projets LLM différents en parallèle car c'est une plateforme de monitoring mutualisée
```
┌──────────────────────────────────────────────────────┐
│  SERVEUR LANGFUSE (localhost:3000)                    │
│  (une seule installation Docker)                      │
│                                                       │
│  ┌─────────────────┐  ┌─────────────────┐            │
│  │ Projet          │  │ Projet          │            │
│  │ "HorRAGor"      │  │ "Chatbot-RH"    │  ...       │
│  │                 │  │                 │            │
│  │ pk-lf-aaa...    │  │ pk-lf-bbb...    │            │
│  │ sk-lf-aaa...    │  │ sk-lf-bbb...    │            │
│  └────────▲────────┘  └────────▲────────┘            │
│           │                    │                     │
└───────────┼────────────────────┼─────────────────────┘
            │                    │
   ┌────────┴────────┐   ┌───────┴─────────┐
   │ horragor-project│   │ autre-projet-llm│
   │ (clés HorRAGor) │   │ (clés Chatbot)  │
   └─────────────────┘   └─────────────────┘
   ```
Chaque projet a ses clés uniques (pk-lf-... / sk-lf-...). C'est la clé qui aiguille les traces vers le bon projet dans l'interface. Les traces ne se mélangent jamais.

A noter que Langfuse a besoin de PostgreSQL, ClickHouse et Redis :
- PostgreSQL → stocke les projets, users, clés API
- ClickHouse → base analytique ultra-rapide pour stocker les millions de traces/tokens
- Redis → cache et file d'attente pour absorber les pics de traces

Actions a faire :
1. Créer un dossier de travail "langfuse" (en dehors de horragor-project)
2. Entrer dans ce dossier =>  ` cd langfuse `
3. Cloner le dépôt officiel de Langfuse  
` git clone https://github.com/langfuse/langfuse.git `
4. Lance Langfuse (ça télécharge PostgreSQL, ClickHouse, Redis... sois patient)  
` docker compose up -d `  
    Note 1 j ai eu un probleme car Windows limite a 260 caractères les chemins de fichiers.  
    solution :
    - Activer les chemins longs dans Git => Ouvrir un terminal en administrateur et lancer : ` git config --global core.longpaths true `
    - supprimer le dossier langfuse car cassé 
    - et recreer ce dossier et recloner 

    Note 2 j ai eu un autre probleme le port 5432 etait deja utilisé:  
    "Error response from daemon: ports are not available: exposing port TCP 127.0.0.1:5432 -> 127.0.0.1:0: listen tcp4 127.0.0.1:5432: bind: An attempt was made to access a socket in a way forbidden by its access permissions."  
    Cause : un PostgreSQL local (ou un autre conteneur) occupe déjà le port 5432 sur
    l'hôte.

    Solution — dans le `docker-compose.yml` de Langfuse, service `postgres` :
        ```
        postgres:
            image: postgres:17
            ...
            ports:
            - 127.0.0.1:5432:5432    # AVANT
        ```
    - Changer uniquement le port de gauche en 5433
        ```
        ports:
            - 127.0.0.1:5433:5432    # APRÈS
        ```
    - Sauvegarder (Ctrl+S) et relance
        ```
        docker compose down
        docker compose up -d
        ```
        Quelques remarques sur le fichier `docker-compose.yml` :  
        ⚠️ Note sécurité — valeurs par défaut

        Cette installation utilise les secrets par défaut du docker-compose.yml
        (marqués `# CHANGEME`). Acceptable en local, à changer impérativement
        avant toute exposition réseau ou mise en production :

        - SALT, NEXTAUTH_SECRET : `openssl rand -base64 32`
        - ENCRYPTION_KEY : `openssl rand -hex 32`
        - POSTGRES_PASSWORD, REDIS_AUTH, CLICKHOUSE_PASSWORD : mots de passe forts

        ⚠️ Changer ENCRYPTION_KEY après avoir créé des clés API rend celles-ci
        illisibles. Le faire AVANT le premier démarrage, ou repartir d'un
        `docker compose down -v`.

   - Vérifier que tout tourne ` docker compose ps `  
        → les 6 services doivent être Up, et postgres/clickhouse/redis/minio (healthy)
   - Ouvrir http://localhost:3000 dans le navigateur (on voit la page de connexion Langfuse)

    Note 3 — "Cette page ne fonctionne pas" : Langfuse pointait vers une base
    Supabase distante

    Diagnostic : ` docker compose logs langfuse-web `  
    Sortie :  
        ```
        Datasource "db": PostgreSQL database "postgres", schema "public"
        at "aws-1-eu-central-1.pooler.supabase.com:5432"
        Error: P3005 The database schema is not empty.
        ```

    Cause : des variables DATABASE_URL / DIRECT_URL d'un autre projet
    (Supabase) étaient présentes dans l'environnement et écrasaient les valeurs par
    défaut du docker-compose.yml. Résultat : Prisma tentait ses migrations sur une
    base distante déjà remplie → boucle infinie de crashs.

    ⚠️ Piège à éviter : ne PAS créer de fichier .env à partir de
    .env.dev.example. Ce fichier est destiné au développement local hors Docker
    (les hosts y sont localhost, pas les noms de services Docker). Docker Compose
    lit automatiquement tout .env présent dans le dossier et ses valeurs
    localhost écrasent les bonnes valeurs → le conteneur ne trouve plus la base.
    Le docker-compose.yml officiel de Langfuse est auto-suffisant : il contient
    déjà toutes les variables nécessaires avec les bons hosts Docker.

    Solution :
      1) S'il existe un .env dans le dossier langfuse/, le renommer pour que
     Docker Compose l'ignore : ` ren .env .env.local ` => perso j ai renommer en ` .env.local `
      2) Supprimer toute directive env_file ajoutée dans le docker-compose.yml :
          ```
          langfuse-web:
              image: docker.io/langfuse/langfuse:3
              restart: always
              env_file:          # ← SUPPRIMER CES 2 LIGNES
              - .env           # ← SUPPRIMER
              environment:
              ...
          ```
     3) Vérifier qu'aucune variable ne traîne dans l'environnement Windows :
          ```
          echo %DATABASE_URL%
          echo %DIRECT_URL%
          ```
          → doit afficher littéralement %DATABASE_URL% (= variable inexistante).
          Sinon : set DATABASE_URL= et set DIRECT_URL=


     4) (Optionnel (ce que je n ai pas fait), pour verrouiller définitivement) Écrire les valeurs en dur dans le docker-compose.yml, sans la syntaxe ${...} qui autorise
     l'écrasement par une variable externe. Dans le bloc environment de
     langfuse-web ET dans l'ancre &langfuse-worker-env :
          ```
          DATABASE_URL: postgresql://postgres:postgres@postgres:5432/postgres
          DIRECT_URL: postgresql://postgres:postgres@postgres:5432/postgres
          ```
     5) Vérifier la config résolue par Docker Compose avant de lancer :  
      ` docker compose config | findstr DATABASE_URL `  
      → doit afficher @postgres:5432 (et non localhost ni une URL Supabase).

      Note 4 — Le conteneur restait bloqué sur localhost:5432 malgré la correction
      Symptôme déroutant : docker compose config affichait la bonne valeur
      (@postgres:5432) mais le conteneur continuait à crasher avec
      Can't reach database server at localhost:5432.

      Vérification : ` docker inspect langfuse-langfuse-web-1 --format "{{json .Config.Env}}" | findstr /i DATABASE_URL `  

      → affichait encore @localhost:5432

      Cause : les variables d'environnement sont injectées à la création du
      conteneur, jamais à son redémarrage. Le conteneur crashait en boucle
      (restart: always) et Docker le relançait sans jamais le recréer → il gardait
      figée la config du premier lancement, quand le .env fautif était encore lu.

      Solution :  
        ```
        docker compose down -v --remove-orphans
        docker ps -a --filter "name=langfuse"      # doit ne rien retourner
        docker compose up -d --force-recreate
        ```

      Vérifier que le nouveau conteneur a bien la bonne config : ` docker inspect langfuse-langfuse-web-1 --format "{{json .Config.Env}}" | findstr /i DATABASE_URL `  
      → DATABASE_URL=postgresql://postgres:postgres@postgres:5432/postgres ✅

      Réflexe de debug à retenir : quand un conteneur semble ignorer une
      correction de configuration, comparer
      - docker compose config → la config théorique (fichiers YAML + .env
      - docker inspect <conteneur> → la config réelle du conteneur qui tourne

      Si les deux divergent, le conteneur est obsolète : il faut le recréer, pas le redémarrer.

      | Commande | Recrée le conteneur ? |
      |---|---|
      | `docker compose restart` | ❌ Non — relance le process, config figée |
      | `docker compose up -d` | ⚠️ Seulement si Compose détecte un changement |
      | `docker compose up -d --force-recreate` | ✅ Toujours |
      | `docker compose down` + `up -d` | ✅ Oui (sauf conteneurs orphelins) |

5) Vérifier les logs jusqu'au démarrage complet :  
   ` docker compose logs -f langfuse-web `  
   Attendre ✓ Ready in XXXXms (le premier lancement prend 1 à 3 minutes : migrations PostgreSQL + ClickHouse).
6) Ouvrir http://localhost:3000 → la page de connexion Langfuse s'affiche

### étape B :  Créer un compte local + projet → récupérer les clés

1. Créer le compte  
    Cliquer sur « No account yet? Sign up » (lien sous le formulaire) et remplir :

    | Champ | Valeur suggérée |
    |---|---|
    | **Name** | nicolas tchenio |
    | **Email** | `nicolas.tchenio@gmail.com` (aucun mail n'est envoyé, pas de vérification) |
    | **Password** | 8 caractères minimum => ` m@tdepasse123 ` — **noter-le**, pas de reset possible sans SMTP configuré |

    → Sign up  
    💡 Comme aucun serveur SMTP n'est configuré (SMTP_CONNECTION_URL est vide), il n'y a ni mail de confirmation ni récupération de mot de passe. Garde ses identifiants quelque part.

2. Créer l'organisation  
    Langfuse demande de créer une organisation.
    Organization name : Simplon (ou ce que tu veux)
    → Create
3. Inviter des membres  
    Écran suivant : invitation de membres. Skip — je suis seul.
4. Créer le projet  
    Project name : HorRAGor
    → Create
5. Générer les clés API  
    Sur le dashboard du projet, aller dans:  
    Settings (menu latéral gauche) → API Keys → + Create new API key

    - On obtient :

        ```
        Secret Key : sk-lf-9cd12075-9695-4229-be6d-0d38fdfb28c9   ← affichée UNE SEULE FOIS
        Public Key : pk-lf-ad9c9977-cdec-402f-b3b8-eee965f4d213
        Host       : http://localhost:3000
        ```

    - Copier les trois immédiatement dans le .env du projet HorRAGor (pas dans le dossier langfuse/) : 

        ```
        # .env  (à la racine de ton projet HorRAGor)  
        LANGFUSE_SECRET_KEY=sk-lf-...  
        LANGFUSE_PUBLIC_KEY=pk-lf-...  
        LANGFUSE_HOST=http://localhost:3000
        ```

    - Mets à jour .env.example (documentation pour les autres)
        ```
        # .env.example

        # ===== LANGFUSE =====
        LANGFUSE_SECRET_KEY=sk-lf-your-secret-key-here
        LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key-here
        LANGFUSE_HOST=http://localhost:3000
        ```

    - Mets à jour .env.docker (pour Docker Compose)
        ```
        # .env.docker

        # ===== LANGFUSE =====
        LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        LANGFUSE_HOST=http://host.docker.internal:3000
        ```

### étape C : Installer le package Python `langfuse` | `pyproject.toml` | ### 
Dans notre projet "horragor-project" ajouter le package avec uv ` uv add langfuse `

### étape d : Ajouter les clés dans les fichiers .env ().env, .env.example, .env.docker)

On a deux stacks différents dans les réseaux Docker  :
- Langfuse → réseau par défaut du projet langfuse (dossier langfuse/)
- HorRAGor → réseau horragor-net (bridge dédié)

Deux options :
- Option A — la plus simple (recommandée pour l'instant):  
    Utiliser host.docker.internal, que l'on a déjà configuré pour Ollama dans intelligence-api :
    ```
    # .env.docker
    LANGFUSE_HOST=http://host.docker.internal:3000
    ```
    Ça fonctionne car Langfuse expose bien 3000:3000 sur l'hôte. Et on a déjà dans "docker-compose.yml" :
    ```
    extra_hosts:
    - "host.docker.internal:host-gateway"
    
- Option B — réseau partagé (plus « propre », plus tard) :  
Créer un réseau externe commun et le rattacher aux deux stacks. À garder pour une phase d'industrialisation.

J' ai choisi l option A :
- Le conteneur doit avoir été recréé après ta modif de .env.docker => ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate intelligence-api `
- Vérifier les variables  :
    ```
    docker exec horragor-ia printenv LANGFUSE_HOST
    docker exec horragor-ia printenv LANGFUSE_PUBLIC_KEY
    docker exec horragor-ia printenv LANGFUSE_SECRET_KEY
    ```
    Attendu :
    ```
    http://host.docker.internal:3000
    pk-lf-...
    sk-lf-...
    ```
- Test de vérification :
```
# Depuis ton PC
curl http://localhost:3000/api/public/health

# Depuis le conteneur HorRAGor
docker exec horragor-ia python -c "import httpx; print(httpx.get('http://host.docker.internal:3000/api/public/health').text)"
```
Les deux doivent répondre. Si le second échoue, c'est un souci de pare-feu Windows sur le port 3000.

### étape E : Charger la config Langfuse dans le code
Maintenant que les variables arrivent bien dans le conteneur, il faut que Python les lise. C'est le rôle de src/config.py.

juste après la section Ollama / LLM pour respecter ta logique de regroupement thématique rajouter
```
# ─────────────────────────────────────────────
# OBSERVABILITÉ — Langfuse (Phase 8.1)
# ─────────────────────────────────────────────
LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

# Le tracing ne s'active que si les DEUX clés sont renseignées.
# → l'application reste 100 % fonctionnelle sans Langfuse (CI, tests, démo hors-ligne).
LANGFUSE_ENABLED: bool = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)
```
note ⚠️ Un piège lié à ta ligne 26 :  
` load_dotenv(dotenv_path=_ENV_PATH, override=True) `  
Le override=True signifie que le .env écrase les variables d'environnement Docker. En local hors conteneur c'est ce que l'on veut. Mais dans le conteneur, si un fichier .env était monté ou copié dans l'image, il écraserait les valeurs de .env.docker que tu viens de valider.
Vérifier donc que .env n'est pas dans l'image :  
` docker exec horragor-ia ls -la /app/.env `  
→ Attendu : No such file or directory. Si le fichier existe, ajoute .env à ton .dockerignore.

Test de validation de l'étape E :
- Après la modification, Rebuild pour intégrer le nouveau config.py dans l'image : ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `

    A retenir toute modification dans src exige un rebuild car  Le volume src/ n'était pas monté dans mon"docker-compose.dev.yml".

- puis : ` docker exec horragor-ia python -c "from src import config; print('HOST:', config.LANGFUSE_HOST); print('ENABLED:', config.LANGFUSE_ENABLED); print('PK ok:', config.LANGFUSE_PUBLIC_KEY.startswith('pk-lf-'))" `

    Attendu :
    ```
    HOST: http://host.docker.internal:3000
    ENABLED: True
    PK ok: True
    ```
    Si ENABLED: False → les clés ne remontent pas jusqu'à Python → c'est le piège du override=True ci-dessus.

### étape F, G, H	
Langfuse s'intègre à LangGraph via un CallbackHandler : un objet qu'on passe dans le config de graph.invoke(). LangChain/LangGraph appellent alors automatiquement ce handler à chaque étape (début de nœud, appel LLM, fin, erreur) et Langfuse construit une trace hiérarchique :
```
Trace "horragor-chat"
├── rag_node          (durée, input, output)
│   └── OllamaEmbeddings   (tokens, latence)
├── scraper_node      (si déclenché)
└── narration_node
    └── ChatOllama    (prompt complet, réponse, tokens)
```
Le principe clé : on ne touche pas aux nœuds. Toute l'instrumentation se fait au point d'entrée (src/main.py), là où on invoque le graphe. C'est ce qui rend Langfuse non-intrusif.

| Choix technique | Justification |
|---|---|
| **Module dédié `observability/`** | Découplage : le code métier ne connaît pas Langfuse. Changer d'outil = modifier un seul fichier. |
| **Dégradation gracieuse** | L'observabilité ne peut pas faire tomber la production. Trois niveaux de garde-fou (config, import, instanciation). |
| **`flush()` au shutdown** | Le buffer est asynchrone : sans flush, les dernières traces sont perdues à l'arrêt du conteneur. |

1) Créer un dossier "src/observability/" avec un
   - "__init__.py" vide
   - "langfuse_client.py" 
    Ce module isole toute la logique Langfuse. Avantage : si Langfuse est indisponible ou désactivé, l'application continue de fonctionner normalement (dégradation gracieuse).
    etape F helper Langfuse => avec get_langfuse_handler() et flush_langfuse()
2) Modifier "src/main.py" :  
étape G brancher le callback
   - Ajouter l'import (après from src.auth.security import verify_access_token)
       ```
       # ═══════════════════════════════════════════════════════════════
       # Observabilité (Phase 8) — import non bloquant
       # ═══════════════════════════════════════════════════════════════
       # Ce module ne lève jamais d'exception : si Langfuse est indisponible,
       # get_langfuse_handler() retourne None et l'agent fonctionne normalement.
       from src.observability.langfuse_client import (
           flush_langfuse,
           get_langfuse_handler,
       )
       ```
   - Modifier le lifespan pour vider le buffer à l'extinction
       ```
       @asynccontextmanager
       async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
           """Cycle de vie de l'application FastAPI.

           **Au démarrage** : compile le graphe LangGraph une seule fois et
           initialise le handler Langfuse (les logs indiquent s'il est actif).

           **À l'extinction** : force l'envoi des traces Langfuse encore en
           mémoire tampon, afin de ne perdre aucune observation.
           """
           global _compiled_graph

           # ── DÉMARRAGE ──
           print("🕯️  Compilation du graphe HorRAGor...")
           _compiled_graph = build_horragor_graph()
           print("✅ Graphe compilé et prêt.")

           # Initialisation anticipée de l'observabilité : provoque l'affichage
           # du log "✅ Langfuse actif" (ou de l'avertissement) dès le boot,
           # plutôt qu'à la première requête utilisateur.
           get_langfuse_handler()

           yield  # ─── L'application sert les requêtes ici ───

           # ── EXTINCTION ──
           # Le buffer Langfuse est asynchrone : sans ce flush, les dernières
           # traces seraient perdues à l'arrêt du conteneur.
           flush_langfuse()
           print("🌙 Extinction du serveur HorRAGor.")
       ```
       Adapte les print à ce que contient déjà ton lifespan — garde ta logique existante, ajoute seulement get_langfuse_handler() avant le yield et flush_langfuse() après.

   - Injecter le handler dans chat_endpoint :
       Remplacer la ligne actuelle : ` config = {"configurable": {"thread_id": thread_id}}`

       par ce bloc :
       ```
       # ═══════════════════════════════════════════════════════════════
       # Configuration LangGraph + Observabilité Langfuse
       # ═══════════════════════════════════════════════════════════════
       # `configurable.thread_id` : clé du checkpointer (mémoire de session).
       # `callbacks`              : liste de handlers LangChain. Langfuse y
       #                            observe automatiquement chaque nœud du
       #                            graphe et chaque appel LLM/embedding.
       # `metadata`               : enrichissements visibles dans l'UI
       #                            Langfuse, très utiles pour filtrer les
       #                            traces (par utilisateur, par session).
       # `run_name`               : nom lisible de la trace dans l'UI.
       # ═══════════════════════════════════════════════════════════════
       langfuse_handler = get_langfuse_handler()

       graph_config: dict[str, Any] = {
           "configurable": {"thread_id": thread_id},
           "run_name": "horragor-chat",
           "metadata": {
               # Préfixes spéciaux reconnus par Langfuse pour alimenter
               # ses filtres natifs dans l'interface web :
               "langfuse_user_id": username,
               "langfuse_session_id": thread_id,
               "langfuse_tags": ["horragor", "rag", "production"],
           },
       }

       # On n'ajoute la clé `callbacks` que si le handler existe, afin de
       # ne jamais passer [None] à LangGraph (qui lèverait une erreur).
       if langfuse_handler is not None:
           graph_config["callbacks"] = [langfuse_handler]
       ```

       Puis, dans l'invocation juste en dessous, remplace config par graph_config :
       ```
           try:
               final_state: AgentState = await asyncio.to_thread(
                   _compiled_graph.invoke,
                   initial_state,
                   graph_config,   # ← anciennement `config`
               )
       ```
       Pourquoi renommer config en graph_config ? Parce que ton module importe déjà from src import config (indirectement, via src.api.auth). Une variable locale nommée config masque le module et rend le code ambigu. Ce renommage est une bonne pratique de lisibilité.

3) Modifier "src/config.py"

    Dans le bloc langfuse rajouter :
    ```
    # Le SDK cherche LANGFUSE_HOST dans os.environ. On réinjecte la valeur
    # résolue (avec son défaut) pour couvrir le cas où la variable n'était
    # pas définie du tout dans l'environnement.
    os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST
    ###
    ```

4) Tests:
   - verifier que le paquet langfuse est bien dans mes dépendances :  ` docker exec horragor-ia python -c "import langfuse; print(langfuse.__version__)" `
   - rebuild : ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `
   - apres le rebuild : ` docker logs horragor-ia --tail 50 `
   - test :
        ```
        REM 4. Obtenir un token JWT
        curl -k -X POST https://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"TON_USER\",\"password\":\"TON_PASS\"}"
        ```
        Note pour avoir le username et password ce sont ceux que j'ai définis en Phase 7.2 (=> admin et motdepasse123 )
        Si oublie faire : ` docker exec horragor-ia printenv | findstr AUTH `

        ```
        REM 5. Envoyer un message (remplace <TOKEN>)
        curl -k -X POST https://localhost:8000/chat -H "Content-Type: application/json" -H "Authorization: Bearer <TOKEN>" -d "{\"message\":\"Parle-moi de The Exorcist\"}"
        ```
        Puis ouvre http://localhost:3000 → menu Tracing → tu dois voir une trace horragor-chat, dépliable nœud par nœud.

## 8.2 Loguru ##
Instrumenter de bout en bout la journalisation structurée sur les 3 couches du projet (Données, Intelligence, Présentation) afin d'assurer une traçabilité complète des requêtes, décisions, appels d'outils et erreurs en temps réel.

Les 3 points clés de l'énoncé à couvrir:

| Point | Où | Quoi |
|---|---|---|
| **Requêtes reçues** | `src/main.py` | Logger chaque requête HTTP entrante (user, query, timestamp) |
| **Décision du routeur** | `src/graph/router.py` | Logger quel chemin est choisi (RAG seul, Scraper seul, RAG+Scraper, LLM pur) |
| **Appels d'outils** | `src/graph/nodes.py` | Logger chaque nœud du graphe (RAG, Scraper, Narration) : entrée, sortie, erreur |

Architecture de la Solution :

| Principe | Implémentation |
|---|---|
| **Centralisation** | Un module `logging_config.py` par service (3 au total : src/, data_api/, app_frontend.py) configurant Loguru **une seule fois** au démarrage |
| **Structuration** | Logs en JSON pour traçabilité (fichiers rotatifs dans `./logs/`) |
| **Contexte** | Utilisation de `logger.contextualize(request_id=...)` pour **corréler les logs d'une même requête** à travers plusieurs fonctions/fichiers |
| **Niveaux** | `DEBUG` (développement local), `INFO` (production) — paramétrable via `config.py` |
| **Persistance** | Logs rotatifs (50 MB par fichier, max 5 fichiers) écrits dans `./logs/` |

Structuration du code :
```
src/observability/
├── __init__.py
├── langfuse_client.py         ← tracing (agent Langfuse)
└── logging_config.py          ← logging (infrastructure)  [NOUVEAU]

data_api/observability/
├── __init__.py
└── logging_config.py          ← idem (copie conforme)  [NOUVEAU]

app_frontend.py
└── Au démarrage : from observability.logging_config import setup_logging; setup_logging()  [NOUVEAU]
```

Flux de Données d'une Requête (avec Loguru):
```
┌──────────────────────────────────┐
│  COUCHE 3 : PRÉSENTATION         │
│  (app_frontend.py / Streamlit)   │
└────────────┬──────────────────────┘
             │
             ├─ logger.info("👤 User login")
             │  (logs frontend)
             │
             ▼
┌──────────────────────────────────────────────────┐
│  COUCHE 2 : DONNÉES                              │
│  (data_api/main.py :: /auth/login endpoint)      │
│  ┌──────────────────────────────────────────────┐│
│  │ logger.info("🔐 Tentative login")   [LOG A1] ││
│  │ → data_api/database.py                       ││
│  │   logger.info("🗄️ SELECT user WHERE...")  ││
│  │ logger.info("✅ Login OK")           [LOG A2] ││
│  └──────────────────────────────────────────────┘│
└────────────┬──────────────────────────────────────┘
             │
             ├─ Token JWT retourné au Frontend
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  COUCHE 3 : PRÉSENTATION                                │
│  (app_frontend.py :: POST /chat avec token)             │
│  ┌─────────────────────────────────────────────────────┐│
│  │ logger.info("💬 User envoie question")    [LOG B1]  ││
│  │ request_id = uuid.uuid4()                           ││
│  │ with logger.contextualize(request_id=...) : ││
│  └─────────────────────────────────────────────────────┘│
└────────────┬─────────────────────────────────────────────┘
             │
             ▼ (HTTP POST /chat)
┌─────────────────────────────────────────────────────────┐
│  COUCHE 1 : INTELLIGENCE                                │
│  (src/main.py :: /chat endpoint)                        │
│  ┌─────────────────────────────────────────────────────┐│
│  │ logger.info("📨 Requête reçue")          [LOG #1]   ││
│  │   request_id="abc-123"                              ││
│  │   query="films horreur"                             ││
│  │   user_id="alice"                                   ││
│  │ ↳ request_id attaché à TOUS les logs qui suivent   ││
│  └─────────────────────────────────────────────────────┘│
└────────────┬─────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  src/graph/router.py :: route_request()                 │
│  ┌─────────────────────────────────────────────────────┐│
│  │ logger.debug("🚦 Routeur décide: RAG+Web") [LOG #2] ││
│  │ return "rag_scraper_branch"                         ││
│  └─────────────────────────────────────────────────────┘│
└────────────┬─────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────────────┐  ┌─────────────────────┐
│ RAG Node         │  │ Scraper Node        │
│ (src/graph/      │  │ (src/graph/         │
│  nodes.py)       │  │  nodes.py)          │
│ ┌────────────────┐│  │ ┌─────────────────┐ │
│ │logger.info(    ││  │ │logger.info(     │ │
│ │"🔍 RAG search" ││  │ │"🌐 Scraper Web" │ │
│ │)      [LOG #3] ││  │ │)      [LOG #3b] │ │
│ └────────────────┘│  │ └─────────────────┘ │
│                  │  │                     │
│ → src/tools/     │  │ → src/tools/        │
│   rag_tool.py    │  │   scraper_tool.py   │
│                  │  │                     │
│ logger.info(     │  │ logger.info(        │
│ "📊 FAISS: "     │  │ "📡 Wikipedia API:  │
│ )                │  │ ")                  │
│                  │  │                     │
│ logger.info(     │  │ logger.info(        │
│ "✅ 5 docs",     │  │ "✅ 2 pages",       │
│  scores=...      │  │  urls=...           │
│ )                │  │ )                   │
└────────┬─────────┘  └────────┬────────────┘
         │                     │
         └──────────┬──────────┘
                    ▼
        ┌─────────────────────────────┐
        │ Narration Node              │
        │ (src/graph/nodes.py)        │
        │ ┌───────────────────────────┐│
        │ │logger.info(               ││
        │ │"✍️ LLM Narration") [LOG #4]││
        │ │                           ││
        │ │ → src/observability/      ││
        │ │   langfuse_client.py      ││
        │ │   (trace agent)           ││
        │ │                           ││
        │ │logger.info(               ││
        │ │"✅ Narration OK",         ││
        │ │char_count=...,            ││
        │ │tokens_used=...            ││
        │ │)                          ││
        │ └───────────────────────────┘│
        └────────────┬─────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│  src/main.py :: retour réponse                           │
│  ┌──────────────────────────────────────────────────────┐│
│  │ logger.info("✅ Réponse envoyée",  [LOG #5]          ││
│  │             elapsed_ms=1636)                         ││
│  │ return ChatResponse(...)                             ││
│  └──────────────────────────────────────────────────────┘│
└────────────┬──────────────────────────────────────────────┘
             │
             ▼ (HTTP response 200)
┌──────────────────────────────────────────────────────────┐
│  COUCHE 3 : PRÉSENTATION                                 │
│  (app_frontend.py :: affiche réponse)                    │
│  ┌──────────────────────────────────────────────────────┐│
│  │ logger.info("✅ Réponse affichée", [LOG B2]          ││
│  │             elapsed_frontend_ms=42)                  ││
│  └──────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘

   ═══════════════════════════════════════════════════════════════════════════
   ./logs/intelligence_api.log.json
   ═══════════════════════════════════════════════════════════════════════════
   {"time":"2026-07-31T18:20:12.345Z","level":"INFO",
    "service":"intelligence","message":"📨 Requête reçue",
    "request_id":"abc-123","query":"films horreur","user_id":"alice"}

   {"time":"2026-07-31T18:20:12.356Z","level":"DEBUG",
    "service":"intelligence","message":"🚦 Routeur: RAG+Web",
    "request_id":"abc-123"}

   {"time":"2026-07-31T18:20:12.401Z","level":"INFO",
    "service":"intelligence","message":"🔍 RAG search",
    "request_id":"abc-123","query":"films horreur","top_k":5}

   {"time":"2026-07-31T18:20:12.523Z","level":"INFO",
    "service":"intelligence","message":"✅ RAG: 5 docs",
    "request_id":"abc-123","scores":[0.89,0.87,0.82,0.78,0.75]}

   {"time":"2026-07-31T18:20:12.525Z","level":"INFO",
    "service":"intelligence","message":"🌐 Scraper Web",
    "request_id":"abc-123"}

   {"time":"2026-07-31T18:20:13.001Z","level":"INFO",
    "service":"intelligence","message":"✅ Scraper: 2 pages",
    "request_id":"abc-123","titles":["The Shining","Hereditary"]}

   {"time":"2026-07-31T18:20:13.105Z","level":"INFO",
    "service":"intelligence","message":"✍️ LLM Narration",
    "request_id":"abc-123"}

   {"time":"2026-07-31T18:20:13.980Z","level":"INFO",
    "service":"intelligence","message":"✅ Narration OK",
    "request_id":"abc-123","char_count":1240,"tokens_used":234}

   {"time":"2026-07-31T18:20:13.981Z","level":"INFO",
    "service":"intelligence","message":"✅ Réponse envoyée",
    "request_id":"abc-123","elapsed_ms":1636}
   ═══════════════════════════════════════════════════════════════════════════

   ═══════════════════════════════════════════════════════════════════════════
   ./logs/data_api.log.json
   ═══════════════════════════════════════════════════════════════════════════
   {"time":"2026-07-31T18:20:12.320Z","level":"INFO",
    "service":"data","message":"🔐 Tentative login",
    "user_id":"alice","endpoint":"/auth/login"}

   {"time":"2026-07-31T18:20:12.325Z","level":"DEBUG",
    "service":"data","message":"🗄️ SELECT user",
    "query":"WHERE username='alice'","elapsed_ms":5}

   {"time":"2026-07-31T18:20:12.330Z","level":"INFO",
    "service":"data","message":"✅ Login OK",
    "user_id":"alice","token_expires_in_s":3600}
   ═══════════════════════════════════════════════════════════════════════════

   ═══════════════════════════════════════════════════════════════════════════
   ./logs/frontend.log.json
   ═══════════════════════════════════════════════════════════════════════════
   {"time":"2026-07-31T18:20:12.300Z","level":"INFO",
    "service":"frontend","message":"👤 User login",
    "user_id":"alice","endpoint":"http://localhost:8001/auth/login"}

   {"time":"2026-07-31T18:20:12.340Z","level":"INFO",
    "service":"frontend","message":"💬 User envoie question",
    "request_id":"abc-123","query":"films horreur"}

   {"time":"2026-07-31T18:20:13.985Z","level":"INFO",
    "service":"frontend","message":"✅ Réponse affichée",
    "request_id":"abc-123","elapsed_frontend_ms":42}
   ═══════════════════════════════════════════════════════════════════════════
   ↳ 3 fichiers logs, parsables par Prometheus/Grafana/Uptime Kuma
```
Plan Détaillé COMPLET — Les 3 Couches
1) Couche 1 : Intelligence (src/)
   - Priorité 1 — Fondations
  
        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 1 | `src/config.py` | **[MODIFIER]** Ajouter `LOG_LEVEL`, `LOG_DIR`, `LOG_JSON`, `LOG_FILE_MAX_BYTES`, `LOG_FILE_BACKUP_COUNT` | Source unique de configuration Loguru |
        | 2 | `pyproject.toml` | **[VÉRIFIER/AJOUTER]** Dépendance `loguru>=0.7.0` | Loguru doit être installé |
        | 3 | `src/observability/logging_config.py` | **[CRÉER]** Module d'initialisation (fonction `setup_logging()`) | Exécuté une seule fois au démarrage |
        | 4 | `src/main.py` | **[MODIFIER]** Appel `setup_logging()` en premier, logs requêtes reçues/réponses | Point d'entrée : chaque requête HTTP loggée |
        | 5 | `src/graph/router.py` | **[MODIFIER]** Logs de la décision du routeur | **Point clé énoncé** : tracer quel chemin est choisi |
        | 6 | `src/graph/nodes.py` | **[MODIFIER]** Logs in/out des 3 nœuds (RAG, Scraper, Narration) | **Point clé énoncé** : appels d'outils loggés |

   - Priorité 2 — Cohérence de la chaîne

        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 7 | `src/tools/rag_tool.py` | **[MODIFIER]** Logs internes : nb docs, scores, fallback | Visibilité sur le comportement du RAG |
        | 8 | `src/tools/scraper_tool.py` | **[MODIFIER]** Logs internes : URL appelée, succès/échec réseau | Visibilité sur le Scraper |
        | 9 | `src/api/auth.py` | **[MODIFIER]** Logs des tentatives login (réussi et échoué) | Sécurité : tracer les authentifications |

   - Priorité 3 — Infrastructure (src)
        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 10 | `src/graph/pipeline.py` | **[MODIFIER]** Logs de compilation du graphe | Diagnostic au boot |
        | 11 | `src/observability/langfuse_client.py` | **[MODIFIER]** Remplacer `print()` par `logger` | Cohérence observabilité |

2) Couche 2 : Données (data_api/)
   - Priorité 1 — Fondations
        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 12 | `data_api/config.py` | **[CRÉER OU VÉRIFIER]** Ajouter `LOG_LEVEL`, `LOG_DIR`, `LOG_JSON`, etc. | Même configuration que src/ |
        | 13 | `data_api/observability/logging_config.py` | **[CRÉER]** Copie conforme de `src/observability/logging_config.py` | Exécuté au démarrage de `data_api/main.py` |
        | 14 | `data_api/main.py` | **[MODIFIER]** Appel `setup_logging()` en premier | Point d'entrée data_api : requêtes HTTP loggées |

   - Priorité 2 — Chaîne
        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 15 | `data_api/database.py` | **[MODIFIER]** Logs des opérations DB (SELECT, INSERT, UPDATE, DELETE) | Traçabilité complète des données |
        | 16 | `data_api/api/auth.py` (si existe) | **[MODIFIER]** Logs des authentifications data_api | Cohérence sécurité |

3) Couche 3 : Présentation (app_frontend.py)
   - Priorité 1 — Fondations
        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 17 | `observability/logging_config.py` (frontend) | **[CRÉER]** Copie conforme de `src/observability/logging_config.py` | Streamlit loggé structurément |
        | 18 | `app_frontend.py` | **[MODIFIER]** Appel `setup_logging()` au démarrage, logs des interactions utilisateur | Point d'entrée Streamlit : événements loggés |

   - Priorité 2 — Chaîne
        | # | Fichier | Action | Raison |
        |---|---|---|---|
        | 19 | `app_frontend.py` (auth section) | **[MODIFIER]** Logs des appels `/auth/login` et `/auth/refresh` | Tracer les sessions utilisateur |
        | 20 | `app_frontend.py` (chat section) | **[MODIFIER]** Logs des appels `/chat` et temps de réponse | Tracer les interactions |

4) Infrastructure & Docker (Tous les services)

    | # | Fichier | Action | Raison |
    |---|---|---|---|
    | 21 | `docker-compose.dev.yml` | **[MODIFIER]** Ajouter volumes `./logs:/app/logs` pour **chaque service** | Persistance logs Intelligence + Données + Frontend |
    | 22 | `.gitignore` | **[MODIFIER]** Ajouter `logs/` | Ne pas commiter les fichiers log |


Ordre de transmission suggéré:  

1) Fondations (Intelligence) : pyproject.toml + src/config.py
→ creation de src/observability/logging_config.py
2) Point d'entrée (Intelligence): src/main.py
3) Cœur de l'énoncé (Intelligence): src/graph/router.py + src/graph/nodes.py
4) Chaîne Intelligence : src/tools/rag_tool.py + src/tools/scraper_tool.py + src/api/auth.py + src/graph/pipeline.py + src/observability/langfuse_client.py
5) Fondations (Données) : data_api/config.py + data_api/main.py
→ creation de data_api/observability/logging_config.py
6) Chaîne (Données) : data_api/database.py
7) Fondations (Frontend) : app_frontend.py (sections auth + chat)
→ creation de  observability/logging_config.py (frontend)
8) Infrastructure : docker-compose.dev.yml + .gitignore

Résumé : Les 3 Couches Couvertes
| Couche | Point d'Entrée | Router/Décision | Appels d'Outils | Persistence |
|---|---|---|---|---|
| **Intelligence** (`src/`) | `src/main.py` ✅ | `src/graph/router.py` ✅ | `src/graph/nodes.py` + outils ✅ | `./logs/intelligence_api.log.json` ✅ |
| **Données** (`data_api/`) | `data_api/main.py` ✅ | N/A (pas de routeur) | `data_api/database.py` ✅ | `./logs/data_api.log.json` ✅ |
| **Présentation** (`app_frontend.py`) | `app_frontend.py` ✅ | N/A (pas de routeur) | Appels `/chat` + `/auth` ✅ | `./logs/frontend.log.json` ✅ |

----------------

1) actions point 1:
    - MODIFICATION 1 : src/config.py
    - CRÉATION : 
       - src/observability/logging_config.py
       - src/observability/json_serializer.py => pour ameliiorer la presentation du json
    - Variables d'environnement à ajouter au .env (optionnel, defaults OK) (idem pour le .env.example et .env.docker)


2) actions point 2 :  
    On va maintenant modifier src/main.py pour intégrer le logging structuré au point d'entrée de l'application Intelligence.
    - Importer setup_logging() de src/observability/logging_config.py
    - Appeler setup_logging() en tout premier (avant FastAPI)
    - Remplacer les print() par des logs structurés
    - Ajouter un middleware de requête/réponse avec request_id automatique
    - Logger les requêtes HTTP, réponses et erreurs

    On obtient maintenant :
    - Traçabilité complète : chaque requête HTTP a un request_id unique
    - Logs structurés : points clés avec tags [lifespan], [chat_endpoint], etc.
    - Gestion des erreurs : 401, 503, 500 sont loggées correctement
    - Temps de réponse : chaque requête note son elapsed_time
    - X-Request-ID dans les headers : utile pour tracker côté frontend

    Tests :
    - rebuild : ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `
    - Test A — le démarrage : ` docker logs horragor-ia --tail 40 `
    - Test B — le middleware et le X-Request-ID : `curl -ki https://localhost:8000/health `  
        ✅ Attendu : HTTP/1.1 200 OK + un header x-request-id: <uuid>.  
        Note l'UUID, puis : ` docker logs horragor-ia --tail 20 `  
        ✅ Attendu : → Requête entrante : GET /health, la ligne debug du health check, et ← Réponse : 200 (x.xx ms) — les trois portant le même request_id. C'est ça qui prouve que la traçabilité fonctionne.
    - Test C — non-régression /chat authentifié  
        Récupère un token (adapte le mot de passe) : `  curl -k -s -X POST https://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"TON_MDP\"}"`
        Puis, avec le token : `curl -ki -X POST https://localhost:8000/chat -H "Authorization: Bearer TON_TOKEN" -H "Content-Type: application/json" -d "{\"message\":\"Parle-moi de The Exorcist\"}" `  
        ✅ Attendu : 200 + JSON complet (response, sources, used_web, thread_id).  Dans les logs, la chaîne complète avec le même request_id : requête entrante → ✅ Utilisateur authentifié : admin → Sources FAISS extraites : N → ← Réponse : 200.

3) actions point 3 : modifications =>  
    nodes.py :  
        - Import from loguru import logger  
        - Logs structurés dans rag_node :  
          - logger.info() pour les étapes principales (début, vectoriel, structuré, résumé)  
          - logger.debug() pour les détails (normalisation, fallback, métadonnées)  
        - Logs dans scraper_node (priorités, appels web)
        - Logs dans narration_node (corpus, outils, LLM invocation, succès/erreur)  
        - Docstrings enrichies, commentaires français préservés

    router.py
      - Import from loguru import logger
      - Logs dans helpers (_extract_best_faiss_score, _structured_has_matches, _faiss_is_relevant)
      - Logs détaillés dans route_after_rag() :
       - logger.warning() pour décisions négatives (aucun signal)
       - logger.info() pour décisions positives (avec contexte détaillé)
      - Docstrings enrichies en français
      - Suppression du logger = logging.getLogger(__name__) (remplacé par Loguru)
  
    Tests :  
       - verifier que dans ".env.docker" => ` LOG_LEVEL=DEBUG `
       - rebuild : ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `  
       - Test :   
         - ` docker logs -f horragor-ia ` ou ` docker logs -f horragor-ia | findstr /C:"RAG Node" /C:"Router" /C:"Scraper" /C:"Narration" `  
         - et faire une requete dans interface streamlit

4) actions point 4 : Chaîne Intelligence : 
- src/tools/rag_tool.py — Logs du comportement vectoriel et structuré
  
    | Point | Statut actuel | À ajouter |
    |-------|--------------|-----------|
    | Chargement FAISS | ✅ Logs présents | ✅ Logs OK |
    | Recherche vectorielle | ⚠️ Logs minimalistes | 🔴 **Ajouter : scores des résultats, seuil de pertinence** |
    | Appels data-api | ⚠️ Pas de logs | 🔴 **Ajouter : URL, statut HTTP, nombre de résultats** |
    | Erreurs réseau | ⚠️ Minimaliste | 🔴 **Ajouter : timeout, détail d'erreur** |
    | Fuzzy matching | ⚠️ Minimaliste | 🔴 **Ajouter : score_cutoff, candidats testés** |

    tests :
    - ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `
    - Syntaxe Python valide => ` python -m py_compile src/tools/rag_tool.py && echo "✅ Syntaxe OK" `
    - Vérifier les imports => ` python -c "from src.tools.rag_tool import search_local_horror_lore, query_movie_metadata, find_similar_horror_movies, fuzzy_find_film, resolve_film, _load_faiss_resources; print('OK: 6 fonctions importees')" `
    - Compter les appels logger => ` findstr /C:"logger." src\tools\rag_tool.py | find /c /v "" ` ou ` for %L in (info debug warning error success) do @findstr /C:"logger.%L" src\tools\rag_tool.py | find /c /v "" > nul & findstr /C:"logger.%L" src\tools\rag_tool.py | find /c /v "" `
    - Sections docstring (Parameters / Returns / Raises) => ` findstr /R /C:"Parameters" /C:"Returns" /C:"Raises" src\tools\rag_tool.py | find /c /v ""`
    - Signatures inchangées => ` python -c "import inspect,src.tools.rag_tool as m;[print(n, inspect.signature(f)) for n,f in vars(m).items() if callable(f) and getattr(f,'__module__','')==m.__name__]" `
    - Vérification en conditions réelles (Docker) :
        ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `  
        Puis, dans un second terminal cmd : ` docker logs -f horragor-ia | findstr /C:"FAISS" /C:"data-api" /C:"Fuzzy" /C:"pgvector" /C:"score" `  
        Lance ensuite une requête Streamlit avec un titre volontairement mal orthographié (ex. « Shinning » ou « Concjuring ») pour faire apparaître (score_cutoff appliqué + candidat fuzzy retenu, les scores FAISS (min / max / moyen), l'URL data-api appelée + statut HTTP + durée ms)
    - Aucune exception avalée => ` findstr /C:"except" src\tools\rag_tool.py `

- src/tools/scraper_tool.py — Logs des appels réseau et parsing  
    les modifications :  
    | Exigence | Implémentation |
    |---|---|
    | URL cible appelée | `urlencode` complet en `debug` avant chaque GET |
    | Statut HTTP + durée ms | `info` après chaque réponse, avec `perf_counter` |
    | Taille réponse | octets bruts + nb caractères du fragment HTML |
    | Éléments extraits | nb sections, nb `<sup>` retirés, nb `<p>`, nb paragraphes conservés, taux de compression |
    | Page vide / sélecteur KO | `warning` dédié si 0 section, 0 `<p>`, fragment vide, texte vide après nettoyage |
    | Timeout / RequestError / HTTPError | 3 `except` distincts + `ValueError` JSON, tous en `error` avec durée |
    | User-agent / config | logué une fois au chargement du module |
    | Bonus | redirection Wikipédia détectée et tracée, liste des sections disponibles en cas d'échec étape 2 |

    tests :
    - ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `
    - Syntaxe => ` python -m py_compile src\tools\scraper_tool.py && echo OK Syntaxe `
    - Imp => orts (5 fonctions) => ` python -c "from src.tools.scraper_tool import _fetch_page_sections, _fetch_section_html, _clean_wiki_html, extract_wikipedia_synopsis, enrich_from_web; print('OK: 5 fonctions importees')" `
    - Comptage logger (≥ 45 attendu) => ` findstr /C:"logger." src\tools\scraper_tool.py | find /c /v "" `
    - Instrumentation durée (~20 attendu) => ` findstr /N /C:"perf_counter" src\tools\scraper_tool.py | find /c /v "" `
    - Gestion d'erreurs (8 attendu : 2×Timeout, 2×HTTPError, 2×RequestException, 2×ValueError) => ` findstr /C:"except requests" /C:"except ValueError" src\tools\scraper_tool.py `
    - Signatures inchangées => ` python -c "import inspect,src.tools.scraper_tool as m;[print(n, inspect.signature(f)) for n,f in vars(m).items() if callable(f) and getattr(f,'__module__','')==m.__name__]" `
    - Cas réel : film existant => ` python -c "from src.tools.scraper_tool import enrich_from_web; r=enrich_from_web('Shining'); print('LONGUEUR:', len(r))" `
    - Cas d'échec : page inexistante => ` python -c "from src.tools.scraper_tool import enrich_from_web; r=enrich_from_web('FilmQuiNexistePasXyz123'); print('VIDE' if not r else 'PROBLEME')" `
    - Cas limite : article sans section synopsis => ` python -c "from src.tools.scraper_tool import enrich_from_web; enrich_from_web('Python (langage)')" `
    - Titre vide => ` python -c "from src.tools.scraper_tool import enrich_from_web; print(repr(enrich_from_web('')))" `

- src/api/auth.py — Logs des tentatives d'authentification  
  Ne jamais logger le mot de passe en clair, seulement le username et le résultat (succès/échec).  
  Ce qui a changé (aucune signature, aucun comportement HTTP touché) :
    - import time + from loguru import logger ajoutés
    - logger.info en entrée de login() et refresh() — jamais le password, jamais le refresh_token complet (seulement 10 premiers caractères en debug)
    - logger.warning sur chaque branche d'échec utilisateur (username inconnu, mauvais password, refresh invalide), avec la raison précise
    - logger.error distinct pour l'erreur serveur (hash non configuré) — c'est un problème d'infra, pas une tentative malveillante
    - logger.success + durée en ms sur les deux succès, sans jamais afficher les tokens générés

    tests : 
    - ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `
    - ` python -m py_compile src/api/auth.py && echo OK Syntaxe `
    - test réelles via l'API démarrée (uvicorn ou ton main.py) :
        ```
        # Terminal 1 : démarre le serveur
        uvicorn src.main:app --reload

        # Terminal 2 : tests
        # Test 1 : mauvais username
        curl -4 -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"mauvais_user\",\"password\":\"x\"}"

        # Test 2 : mauvais password (remplace "admin" et "motdepasse123" par tes vraies credentials)
        curl -4 -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"mauvais_password\"}"

        # Test 3 : bon login (remplace par tes vraies credentials)
        curl -4 -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"motdepasse123\"}"

        # Test 4 : refresh token invalide
        curl -4 -X POST http://localhost:8000/auth/refresh -H "Content-Type: application/json" -d "{\"refresh_token\":\"token_invalide\"}"

        ```

- src/graph/pipeline.py — Logs de compilation du graphe LangGraph
    tests : 
    - verification syntaxique => ` python -c "import ast; ast.parse(open('src/graph/pipeline.py', encoding='utf-8').read()); print('Syntaxe OK')" `
    - rebuid du conteneur : ` docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build intelligence-api `
    - les logs de compilation => ` docker logs horragor-ia --tail 40 ` ou ` docker logs horragor-ia 2>&1 | findstr /C:"[Graph]" `
    - Vérifier que rien n'est cassé :   
        - dans un Terminal 1 : démarrer le serveur => ` uvicorn src.main:app --reload `
        - dans un autre terminal :  
        Le graphe compilé doit toujours fonctionner. Récupère un token puis interroge /chat => ` curl -4 -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"motdepasse123\"}" `
        Copie l'access_token, puis => ` curl -4 -X POST http://localhost:8000/chat -H "Content-Type: application/json" -H "Authorization: Bearer TON_TOKEN" -d "{\"message\":\"Quels sont les horaires d ouverture ?\"}" `


- src/observability/langfuse_client.py — Remplacer print() par logger  
    langfuse_client.py utilise directement Loguru au lieu du logging standard (pour homogénéiser tout le code avec from loguru import logger partout plutôt que de compter sur une interception implicite).  

5) actions point 5 : Fondations (Données) :
- data_api/config.py (nouveau)
Même pattern que src/config.py : chargement du .env racine, PROJECT_ROOT, puis les 5 variables déjà présentes dans .env.example : LOG_LEVEL, LOG_DIR, LOG_JSON, LOG_FILE_MAX_BYTES, LOG_FILE_BACKUP_COUNT, avec création de LOG_DIR. Rien d'autre (pas de duplication de DATABASE_URL etc., hors scope).

- data_api/observability/ (nouveau : __init__.py, logging_config.py)
Copie auto-suffisante (pas d'import vers src.observability), à cause de la contrainte Docker ci-dessus. Adaptations par rapport à la version src/ :
  - flatten_loguru_record → "service": "data-api" au lieu de "intelligence".
  - LOG_FILE_PATH = LOG_DIR / "data_api.log" (fichier distinct, même dossier logs/ partagé).
  - Liste des loggers stdlib interceptés réduite à uvicorn*, fastapi, starlette (pas httpx/langfuse, absents côté data_api).
  - Import des constantes depuis data_api.config au lieu de src.config.

    Dans src/observability/logging_config.py, la classe JsonFileSink (utilisée quand LOG_JSON=True, qui est la valeur par défaut dans .env.example) appelle flatten_loguru_record() pour transformer chaque enregistrement Loguru en une ligne JSON à plat. Cette fonction vit dans json_serializer.py — ce n'est pas optionnel, sans elle le sink JSON ne peut pas fonctionner.

    Comme data_api/observability/logging_config.py doit être autonome (pas d'import vers src/), il a besoin de cette même fonction, mais avec "service": "data-api" au lieu de "intelligence".

    j ai choisi d'une  Fonction inlinée directement dans data_api/observability/logging_config.py (pas de fichier séparé) plutot que de creer un autre Fichier séparé data_api/observability/json_serializer.py — symétrique avec src/.

- data_api/main.py (modifié)
Appel de setup_logging() tout en haut du fichier, avant l'import de data_api.routers.films (qui déclenche l'import de database.py/psycopg2), exactement comme dans src/main.py.

6) actions point 6 : Chaîne (Données)

    Pour l'item 15 (data_api/database.py) — le point délicat : les requêtes SQL (SELECT, futures INSERT/UPDATE/DELETE) sont exécutées dans data_api/routers/films.py via conn.cursor().execute(...), pas dans database.py lui-même, qui ne fait qu'ouvrir/fermer la connexion. Pour respecter la consigne "modifier database.py uniquement" sans toucher films.py, j'ai :

    - Logger le cycle de vie de la connexion dans get_db_connection() : ouverture réussie (debug) et fermeture (debug), en plus du logger.error déjà présent sur OperationalError.
    - Instrumenter execute() de façon transparente : get_db_connection() retournera une connexion enveloppée dont .cursor(...) produit un curseur enveloppé qui journalise automatiquement, à chaque appel execute() :
        - l'opération détectée (SELECT/INSERT/UPDATE/DELETE, extrait du premier mot de la requête),
        - la durée en ms,
        - le nombre de lignes affectées (rowcount),
        - les erreurs SQL (logger.error avant de relever l'exception).

        Ce wrapper délègue tout le reste (fetchall, fetchone, cursor_factory=RealDictCursor, etc.) au curseur psycopg2 réel via __getattr__ — donc aucune modification de films.py n'est nécessaire, toutes les requêtes existantes et futures sont tracées automatiquement.


7) actions point 7 : Fondations (Frontend) 

- observability/logging_config.py (nouveau, package racine)
  - Auto-suffisant comme la version data_api, mais importe LOG_LEVEL/LOG_DIR/etc. directement depuis src.config (pas de nouveau config.py frontend créé — il n'apparaît pas dans ta table, et docker/frontend.Dockerfile copie déjà tout src/, contrairement à data_api qui n'en copie qu'un extrait). C'est cohérent avec app_frontend.py qui importe déjà API_BASE_URL/API_TIMEOUT depuis src.config.
  - service="frontend", fichier logs/frontend.log.
  - Interception stdlib limitée à streamlit et httpx (pas de fastapi/uvicorn, absents ici).

- app_frontend.py (modifié)
  - Point d'attention important, propre à Streamlit : le script entier se ré-exécute à chaque interaction (clic, saisie...). Appeler setup_logging() sans garde à chaque rerun re-déclencherait toute l'init Loguru en boucle. Je protège l'appel avec st.cache_resource (le mécanisme Streamlit idiomatique garantissant une exécution unique par process), plutôt qu'un simple flag global fragile.
  - Remplace le seul print() du fichier (decode_jwt_payload, ligne 74) par logger.error(...), dans la continuité du remplacement print() → logger déjà fait sur langfuse_client.py (item 11).
  - section auth (login(), refresh_access_token())
    - login() : logger.info avec username bindé si succès, logger.warning si échec (mauvais identifiants) ou logger.error si erreur inattendue (réseau, TLS...).
    - refresh_access_token() : logger.info si le refresh réussit, logger.warning s'il échoue.
  - section chat (call_chat_api())
    - Mesure du temps de réponse avec time.perf_counter() (nouvel import time).
    - logger.debug avant l'envoi (longueur de la question, thread_id bindé).
    - logger.info avec duration_ms à la réception d'une réponse 200 (avant ou après un refresh automatique sur 401).
    - logger.warning/logger.error sur les cas d'échec : token expiré sans refresh possible, erreur HTTP non-200, ConnectError (backend hors ligne), exception inattendue.

    Toutes ces lignes utilisent logger.bind(thread_id=..., username=...) pour rester corrélables entre elles dans les logs JSON. Je garde les st.error/st.info existants intacts (affichage utilisateur), j'ajoute juste les logs en parallèle.

8) actions point 8 :Infrastructure 

    j'ajoute volumes: 
    - ./logs:/app/logs aux 3 services (data-api, intelligence-api, frontend) dans docker-compose.dev.yml — confirmé que les 3 services utilisent déjà LOG_DIR=/app/logs via .env.docker, donc le montage rendra directement visibles data_api.log, intelligence_api.log et frontend.log sur mon PC dans ./logs/.

## 8.3 Prometheus + Grafana + Uptime Kuma #

### 1. Instrumentation des 2 API (code) ###
1. Dépendance (pyproject.toml)  
Ajouter prometheus-fastapi-instrumentator via uv add prometheus-fastapi-instrumentator (une seule commande, pas de code).

2. data_api/main.py
   - Import (après les imports existants, ligne 22-25) :  
        from prometheus_fastapi_instrumentator import Instrumentator

   - Activation (en fin de fichier, après le bloc health_check, ligne 45) :  
   Instrumentator().instrument(app, excluded_handlers=["/health"]).expose(app)

   - Décisions prisent pour ce fichier :
     - /health exclu des métriques : Uptime Kuma va le pinguer en boucle, l'exclure évite de polluer le compteur de requêtes/latence sur Grafana avec du bruit de monitoring.
     - /metrics non protégé par JWT : cohérent avec /health qui n'est déjà pas protégé, et data-api n'a de toute façon aucun port publié vers l'hôte (§ docker-compose.yml) — donc /metrics reste inaccessible depuis ton PC, seul Prometheus (sur le réseau interne) pourra le scraper.
     - Ça enregistre automatiquement un GET /metrics qui expose : nb requêtes par route/méthode/code, histogramme de latence, requêtes en cours. Aucune métrique à coder à la main.

3. src/main.py
- Même import, même ligne, ajoutée en fin de fichier (après health_check, ligne ~406) — ainsi elle s'applique une fois toutes les routes (/chat, /health, /auth/...) déjà enregistrées.

### 2. Prometheus ###
Scrape intelligence-api:8000/metrics et data-api:8001/metrics sur le réseau interne, via un fichier prometheus/prometheus.yml.

Intelligence-api tourne en HTTPS (--ssl-keyfile/--ssl-certfile, Phase 7.3) alors que data-api est en HTTP simple. Ça change la config Prometheus, sinon le scrape de l'API Intelligence échouerait silencieusement

1. prometheus.yml (nouveau fichier, config du scraper)

2. Nouveau service (prometheus) dans docker-compose.yml
   - Image officielle publique (pas de build:, pas de pull_policy: never — contrairement aux 3 services applicatifs) : Docker doit pouvoir la télécharger.
   - Port 9090 publié directement → on pourra ouvrir http://localhost:9092 pour voir les targets et faire des requêtes PromQL.
   - Volume nommé prometheus_data pour persister les données entre docker compose down/up (à déclarer en bas du fichier, section volumes: — nouvelle section à ajouter).

 Tester (docker compose up -d --build + vérifier les targets sur http://localhost:9092/targets),

=> conteneur stable, dashboard accessible sur http://localhost:9092, les 2 API remontent leurs métriques (requêtes, latences, codes de statut), /health exclu du bruit.

### 3. Grafana ###
Datasource Prometheus + un dashboard minimal (requêtes/sec, latence, erreurs)

1. Fichier de provisioning — grafana/provisioning/datasources/datasource.yml

    C'est Grafana lui-même qui impose ce chemin (/etc/grafana/provisioning/datasources/) pour l'auto-configuration au démarrage. Un seul fichier dedans.
    Ça évite de configurer la datasource manuellement à chaque docker compose down/up.

2. Dashboard : pas de provisioning par fichier JSON
Le dashboard (requêtes/sec, latence, erreurs — panels PromQL simples type rate(http_requests_total[1m])) sera creer à la main dans l'UI après le premier
démarrage. Si l'on préfère un fichier JSON peut etre ajouter juste un fichier dansgrafana/provisioning/dashboards/ qui creer le dashborad et que Grafana chargera automatiquement au démarrage (zéro clic)

3. Nouveau service (grafana) dans docker-compose.yml
  grafana:
   - Port hôte 3002 → 3000 interne au conteneur. Pas de conflit avec Langfuse (déjà sur 3000 côté hôte) : les deux 3000 sont internes à des conteneurs différents, seul le mapping hôte compte.
   - Volume nommé grafana_data à ajouter à la section volumes: existante (avec prometheus_data).

4. Executer ` docker compose up -d ` pour démarrer Grafana.
    Grafana tourne sur http://localhost:3002, connecté à Prometheus sans configuration manuelle.

5.  création du dashboard manuel dans l'UI  
    Se connecter avec  (admin/admin)
    
    Étape 1 — Créer le dashboard
    1. Clique sur Dashboards dans le menu de gauche.
    2. En haut à droite, clique sur New → New dashboard.
    3. Clique sur Add visualization.
    4. Une fenêtre te demande la source de données → choisis Prometheus.

    Panel 1 — Requêtes par seconde
    1. Dans la zone de requête en bas, il y a un sélecteur de mode (souvent deux boutons "Builder" / "Code", parfois une icône </>). Clique sur "Code" pour écrire la requête PromQL directement en texte.
    2. Colle cette requête :
    sum(rate(http_requests_total[1m])) by (job)
    3. Appuie sur Shift+Enter (ou clique ailleurs) pour exécuter — le graphique en haut doit se remplir avec 2 courbes (une par job : data-api et intelligence-api).
    4. À droite, dans "Panel options", remplis le champ Title avec : Requêtes par seconde

    Panel 1 terminé. Maintenant :
    1. En haut à droite de l'éditeur de panel, clique sur "Apply" (ou l'icône ✓ / coche) pour valider ce panel et revenir au dashboard.
    2. Tu devrais voir ton dashboard avec le premier graphique "Requêtes par seconde" affiché.
    3. Cherche un bouton "+ Add" (en haut du dashboard) → choisis "Visualization" pour créer le 2ᵉ panel (latence).

    Panel 2 — Latence (p95)
    1. Passe en mode Code (comme précédemment).
    2. Colle cette requête :
    histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
    2. Ça calcule le 95ᵉ centile de latence par API : 95 % des requêtes répondent en dessous de cette valeur.
    3. Garde le type de visualisation Time series.
    4. Dans Panel options (à droite), mets le titre : Latence p95 (secondes)
    5. Clique sur Apply.

    Panel  3ᵉ et dernier panel.

    1. Clique à nouveau sur "+ Add" → "Visualization".
    2. Mode Code, requête :
    sum(rate(http_requests_total{status=~"5.."}[1m])) by (job)
    2. Ça compte le taux d'erreurs serveur (5xx) par seconde, par API. Si tout va bien, la courbe sera à zéro (pas d'erreur) — c'est normal et attendu.
    3. Type de visualisation : Time series.
    4. Titre : Erreurs 5xx / sec
    5. Apply.

    Sauvegarde du dashboard
    1. En haut à droite du dashboard, clique sur l'icône disquette (💾) ou le bouton "Save dashboard".
    2. Une fenêtre demande un titre → mets par exemple : HorRAGor - Vue d'ensemble
    3. Clique sur Save.

### 4. Uptime Kuma ###
Surveille les 3 GET /health (déjà présents depuis la Phase 4.3, y compris _stcore/health pour Streamlit) — se configure surtout via son UI après démarrage, peu de fichiers à écrire.

1. Ajouter le service dans docker-compose.yml :
   - ajout de uptime_kuma_data: dans la section volumes: en bas du fichier.
   Points à noter :
   - Image officielle publique (comme Prometheus/Grafana), pas de build.
   - Port 3003 publié vers l'hôte → UI accessible sur http://localhost:3003.
   - Doit être sur horragor-net pour joindre data-api:8001 et int pas de port publié vers l'hôte — Uptime Kuma doit passer parle réseau interne.

2. Configuration via l'UI (pas de fichier, pas de provisioning) :
    Après docker compose up -d :
    1. Première visite → création du compte admin (admin / admin974).
    2. Créer 3 monitors type HTTP(s) :
    - Data API → http://data-api:8001/health
    - Intelligence API → https://intelligence-api:8000/health — cocher "Ignore TLS/SSL error" (certificat auto-signé, Phase 7.3)
    - Frontend Streamlit → http://frontend:8501/_stcore/health
    - Intervalle : 60s

    Etape 1 :
    1. Dans le menu de gauche, cliquer sur le bouton "Ajouter une nouvelle sonde" (en haut).
    2. Renseigne les champs :
       - Monitor Type : HTTP(s)
       - Friendly Name : Data API
       - URL : http://data-api:8001/health
       - Heartbeat Interval : 60 (secondes) — laisse le reste par défaut (Retries, etc.)
    3. Descends jusqu'à Accepted Status Codes : laisse 200-299 (par défaut).
    4. Clique sur Save (le statut passe au vert ("Up" / "Actif"))

    Etape 2, pour Intelligence API, ajoute une nouvelle sonde avec :
      - Type de sonde : HTTP(s)
      - Nom : Intelligence API
      - URL : https://intelligence-api:8000/health
      - Intervalle : 60 secondes
      - Important : coche l'option "Ignorer les erreurs TLS/SSL" (ou "Ignore TLS/SSL error") — sinon le monitor va échouer à cause du certificat auto-signé de la Phase 7.3.
  
   Etape 3, le Frontend Streamlit :
      - Type de sonde : HTTP(s)
      - Nom : Frontend Streamlit
      - URL : http://frontend:8501/_stcore/health
      - Intervalle : 60 secondes
      - Codes de statut acceptés : 200-299 (par défaut)
      - Pas besoin d'ignorer TLS ici (HTTP simple, pas de certificat).


# Phase 9 : Documentation Sphinx #

## 9.1 Setup Sphinx ##

Initialise Sphinx dans `docs/` (`uv run sphinx-quickstart`).  
   - Installe le thème RTD et le support Markdown :

        `uv add --dev sphinx-rtd-theme myst_parser `

   - Lancer sphinx-quickstart en mode non-interactif (--quiet) pour créer une structure standard, plutôt que l'assistant interactif (qui demande une dizaine de questions une par une) :

        ` uv run sphinx-quickstart docs --quiet --sep -p HorRAGor -a "Nicolas Tchenio" -v 0.1 --language=fr --ext-autodoc --ext-viewcode --makefile --batchfile `

        Ce que ça crée :
        - docs/source/conf.py, docs/source/index.rst (racine de la doc)
        - docs/build/ (dossier de sortie HTML, séparé grâce à --sep)
        - docs/Makefile + docs/make.bat (scripts de build pratiques)
        - Active déjà sphinx.ext.autodoc et sphinx.ext.viewcode dans conf.py

   - Editer conf.py à la main pour :
      - ajouter sphinx_rtd_theme, sphinx.ext.napoleon, myst_parser aux extensions
      - changer html_theme = "alabaster" → "sphinx_rtd_theme"
      - configurer sys.path.insert(0, ...) vers la racine du projet pour qu'autodoc trouve src et data_api

## 9.2 Contenu obligatoire ##

1. **Doc API automatisée** : pour les **deux** API (Données + Intelligence), via `autodoc` (`automodule::` sur `src.main`, `src.api.auth`, `data_api.main`, `data_api.routers.films`, etc.), on s'appuie sur les docstrings déjà rédigées en français dans le code.  
   La doc HTML est dans docs/build/html/index.html.

2. **Schéma relationnel** : documente la base Supabase (tables, relations, clés primaires), y compris la colonne vectorielle ajoutée en Phase 0.3. Génération automatique via un script d'introspection SQL (`information_schema.columns` + `table_constraints`/`key_column_usage`) produisant un tableau par table en RST/Markdown, complété par un diagramme relationnel en `erDiagram` Mermaid — reproductible si le schéma évolue.

   - Nouvelle dépendance nécessaire : pour afficher les diagrammes Mermaid (erDiagram pour la base, et draw_mermaid() plus tard pour le graphe) dans le HTML généré par Sphinx, il faut l'extension sphinxcontrib-mermaid (elle ajoute la directive .. mermaid:: et charge mermaid.js côté navigateur). ` uv add --dev sphinxcontrib-mermaid `

   - Script scripts/generate_db_schema_doc.py — réutilise src.tools.rag_tool._get_db_connection() (même connexion que faiss_to_pgvector.py), interroge le catalogue PostgreSQL (pg_attribute/pg_class + information_schema.table_constraints) pour récupérer, par table du schéma public :
     - colonnes (nom, type exact — y compris vector(768) pour la colonne embedding —, nullable, défaut)
     - clé primaire
     - clés étrangères (relations entre tables)

   - Génération de docs/source/schema_bdd.rst contenant :
     - un erDiagram Mermaid (entités + relations détectées automatiquement)
     - un tableau détaillé par table (colonne / type / nullable / PK-FK)
     - une note précisant que ce fichier est généré, avec la commande pour le régénérer si le schéma évolue

   - Référencer schema_bdd dans le toctree de index.rst, puis rebuild pour vérifier.

3. **Cartographie du graphe** : génère un schéma des nodes, du router et des edges conditionnelles via `graph.get_graph().draw_mermaid()` (texte Mermaid intégré nativement dans une page Sphinx, sans dépendance réseau ni Graphviz).

## 9.3 Build ##

Génère la documentation HTML finale (`uv run sphinx-build -b html docs/source docs/build/html`).

# Phase 10 : Qualité, Tests & Gouvernance #

## 10.5 GitHub Issues ##

Crée un template d'issue dans `.github/ISSUE_TEMPLATE/bug_report.md` avec les champs : nœud concerné (RAG / Scraper / Narration), requête test, résultat attendu, résultat obtenu, logs Langfuse si applicable. Adopte la règle : chaque anomalie détectée = un ticket archivé avant correction.

C'est un fichier Markdown avec un en-tête YAML, placé dans .github/ISSUE_TEMPLATE/, que GitHub reconnaît automatiquement. Quand quelqu'un clique sur "New Issue" sur le repo, au lieu d'une zone de texte vide, GitHub propose ce template pré-rempli avec les sections qu'on a définies — ça force à structurer le rapport de bug au lieu de laisser chacun écrire "ça marche pas" sans contexte.

Structure technique :
```
---
name: Bug Report
about: Signaler une anomalie sur un agent HorRAGor
title: "[BUG] "
labels: bug
---
```

Sections en Markdown normal...  
Le bloc YAML (name, about, title, labels) configure comment ce template apparaît dans le menu "New Issue". Le reste est du Markdown classique, affiché tel quel dans le corps de l'issue à remplir.

## 10.1 Tests unitaires ##
- Teste chaque node indépendamment (mock des outils).
- Teste le router avec des states variés (résultats riches vs résultats vides).
- Teste les endpoints de `data_api` avec la BDD mockée.

Structure proposée:

```
tests/
├── conftest.py              # fixtures partagées (faux curseur/connexion PostgreSQL)
├── test_router.py           # route_after_rag — pur, aucun mock
├── test_nodes.py            # rag_node, scraper_node, narration_node — mocks
├── test_horror_tools.py     # calculate_movie_age, horror_survival_simulator — purs
├── test_security.py         # bcrypt/JWT (src/auth/security.py) — purs
├── test_auth_endpoints.py   # /auth/login, /auth/refresh (TestClient, app minimale)
└── test_data_api_films.py   # /films/search, /fuzzy, /{id}, /{id}/similar (TestClient + DB mockée)
```

Un petit ajout dans pyproject.toml ([tool.pytest.ini_options], pythonpath = ["."]) pour que pytest trouve src et data_api depuis n'importe quel répertoire d'exécution.

Ce qu'on mocke, et pourquoi :

```
┌───────────────────────────┬──────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────┐
│       Fichier testé       │                        Ce qu'on mocke                        │                         Pourquoi                         │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│                           │                                                              │ Fonction 100 % déterministe, on lui passe des dict       │
│ router.py                 │ Rien                                                         │ construits à la main (comme dans tes anciens tests       │
│                           │                                                              │ jetables de Phase 3, mais formalisés en vrais tests      │
│                           │                                                              │ pytest)                                                  │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ nodes.py (rag_node)       │ search_local_horror_lore, query_movie_metadata               │ Éviter tout appel FAISS/HTTP réel                        │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ nodes.py (scraper_node)   │ enrich_from_web                                              │ Éviter un vrai appel réseau à Wikipédia                  │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ nodes.py (narration_node) │ _get_narrator_llm (renvoie un faux LLM),                     │ Éviter tout appel Ollama réel ou requête pgvector        │
│                           │ find_similar_horror_movies                                   │                                                          │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ horror_tools.py           │ Rien (sauf random.randint figé dans un seul test pour un     │ Fonctions pures                                          │
│                           │ résultat déterministe)                                       │                                                          │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ security.py               │ Rien                                                         │ bcrypt/JWT sont déterministes avec une config donnée     │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│                           │ config.AUTH_USERNAME/AUTH_PASSWORD_HASH (monkeypatchés avec  │ On ne connaît pas le vrai mot de passe en clair de ton   │
│ src/api/auth.py           │ un couple utilisateur/mot de passe de test, connu)           │ .env (seul le hash y est) — impossible de tester le      │
│                           │                                                              │ login "correct" sans ça                                  │
├───────────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ data_api/routers/films.py │ get_db_connection (fausse connexion/curseur renvoyant des    │ Éviter toute vraie requête Supabase                      │
│                           │ lignes construites à la main)                                │                                                          │
└───────────────────────────┴──────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────┘
```


## 10.2 Tests d'intégration ##

- Lance l'API, envoie une requête et vérifie que le flux RAG → Narration ou RAG → Scraper → Narration fonctionne.
- Teste le flux d'authentification complet (login / refresh / accès protégé).

## 10.3 Couverture de tests ##

Vise une couverture ≥ 80 % sur les deux API et l'UI (`pytest-cov`).

Étape 1 — Config coverage (pyproject.toml)  
Ajouter `[tool.coverage.run] ` (source = src, data_api, app_frontend.py) et `[tool.coverage.report] ` (fail_under = 80, exclusions type if __name__ == "__main__", pragma: no cover pour le code d'observabilité/infra difficilement testable). Aucun impact sur le code applicatif.

Étape 2 — Mesure de référence (baseline)  
Lancer ` uv run pytest --cov --cov-report=term-missing ` pour obtenir les vrais pourcentages par fichier (lecture seule, aucune modification). Ça remplace mes hypothèses par des chiffres réels avant de décider quoi combler.

Étape 3 — Combler les trous identifiés, probablement :  
  - Tests unitaires pour rag_tool.py et scraper_tool.py (mock aux frontières FAISS/httpx/requests, comme documenté en 10.1).
  - Test léger pour pipeline.py (le graphe compile, contient les 3 nœuds, edges corrects).
  - Tests pour app_frontend.py via streamlit.testing.v1.AppTest (API officielle de test Streamlit, pas de navigateur nécessaire) — à vérifier que la version de Streamlit installée la supporte.
  - Compléments ciblés sur src/main.py si des branches d'erreur ne sont pas couvertes par test_integration_chat.py.

Étape 4 — Re-mesure finale  
Relancer ` pytest --cov ` avec fail_under=80 actif pour valider objectivement l'atteinte du seuil sur les 2 API + l'UI.

Note : Les modules observability/* (logging_config, json_serializer, langfuse_client — Loguru/Langfuse) représentent ~236 lignes peu couvertes. Ce sont majoritairement des wrappers autour de frameworks externes (formatage de logs, envoi de traces). J'ai decider de les exclure du périmètre mesuré (omit dans [tool.coverage.run]) — cohérent avec l'esprit "on ne teste pas la plomberie qui ne peut pas casser côté métier", mais réduit artificiellement le dénominateur.

## 10.4 Pipeline CI/CD ##

Mets en place un pipeline (ex. GitHub Actions) qui lance : lint, tests + couverture, build des images Docker, à chaque push/PR.

Structure du pipeline (.github/workflows/ci.yml)
- Déclencheurs : push (toutes branches) et pull_request (vers main).
- Job lint : uv run ruff check .
- Job test (en parallèle du lint) : uv run pytest --cov --cov-report=term-missing (le seuil fail_under=80 déjà configuré fait échouer le job si la couverture retombe sous 80 %).
- Job build (needs: [lint, test], ne se lance que si les deux précédents passent) : build des 3 images Docker (data_api, intelligence_api, frontend) via docker build -f docker/xxx.Dockerfile ., sans push vers un registre (non demandé par le plan).
- Utilise l'action officielle astral-sh/setup-uv pour l'installation d'uv avec cache.

Les etapes :
- Installer ruff car aucun outil de lint n'est configuré dans le projet actuellement. ajouter en dépendance dev via ` uv add --dev ruff `.

    J'exclus ces deux règles du lint :
    ```
    [tool.ruff.lint]
    select = ["E", "F", "I", "UP"]
    ignore = ["E501", "E402"]
    ```

    car :
    - E501 (123×) — lignes trop longues. Le code contient beaucoup de f-strings/docstrings en français assez longs (logs Loguru détaillés notamment). Les corriger impliquerait de reformater une grande partie du codebase — hors périmètre d'une mise en place de CI, et purement cosmétique.
    - E402 (12×) — imports pas en tête de fichier. Vérifié sur data_api/main.py : c'est volontaire (setup_logging() doit s'exécuter avant l'import des routers pour capter toute l'initialisation — commenté explicitement dans le fichier). Le corriger casserait ce comportement voulu.

- Les tests nécessitent JWT_SECRET_KEY et AUTH_PASSWORD_HASH (sinon src/config.py lève une erreur au chargement) — il n'y a pas de secret réel requis pour les tests (ils sont mockés), donc je fixe des valeurs factices directement dans le workflow.  
    Voici le workflow que je propose pour .github/workflows/ci.yml (j'ai vérifié : uv.lock est bien versionné, donc uv sync --locked est fiable ; les 3 Dockerfiles se build sans secret) :
    ```
    name: CI

    on:
    push:
    pull_request:
        branches: [main]

    jobs:
    lint:
        runs-on: ubuntu-latest
        steps:


    test:
        runs-on: ubuntu-latest
        env:
        JWT_SECRET_KEY: ci_test_secret_key
        AUTH_PASSWORD_HASH: ci_test_password_hash_placeholder
        steps:
        - uses: actions/checkout@v4

        - run: uv run pytest --cov --cov-report=term-missing

    build:
        runs-on: ubuntu-latest
        needs: [lint, test]
        steps:
        - uses: actions/checkout@v4
    er/data_api.Dockerfile -t horragor-data-api:ci .
        - run: docker build -f docker/intelligence_api.Dockerfile -t horragor-intelligence-api:ci .
        - run: docker build -f docker/frontend.Dockerfile -t horragor-frontend:ci .
    ```

    Points notés :
    - JWT_SECRET_KEY/AUTH_PASSWORD_HASH sont des valeurs factices e, tout est mocké dans les tests).
    - build ne se lance que si lint et test réussissent (needs:), pas de push vers un registre (non demandé).
    - fail_under=80 déjà actif dans pyproject.toml fait échouer test si la couverture repasse sous 80 %.

- Le pipeline ne sera réellement validé qu'au premier push vers GitHub 

# Phase 11 : final #

Finaliser le README :
1. Badge CI en haut du README, pointant vers nicolastchenio/simplon_projet7_horagor3 (récupéré depuis votre remote git).
2. Structure du projet : ajouter .github/ (workflows/ci.yml + ISSUE_TEMPLATE/bug_report.md), actuellement absent de l'arborescence.
3. Stack technique : ajouter ruff (lint) à la ligne "Tests".
4. Nouvelle section "🔁 Intégration continue (CI/CD)" décrivant les 3 jobs (lint, test, build) et leur déclenchement.
5. Nouvelle section "🐛 Signaler un bug" pointant vers le template d'issue et la règle "chaque anomalie = un ticket avant correction".

Documentation sphinx sur github pages :  
- creation du fichier ".github/workflows/docs.yml"
    ```
    name: Deploy Sphinx docs to GitHub Pages

    on:
    push:
    quand le schéma/graphe change, comme déjà documenté dans le RE
    2. Sphinx et ses extensions (myst-parser, sphinx-rtd-theme, sphinxcontrib-mermaid) sont dans le groupe dev de pyproject.toml → uv sync (déjà utilisé dans ci.yml) les installe automatiquement.

    Fichier proposé : .github/workflows/docs.yml

    name: Deploy Sphinx docs to GitHub Pages

    on:
    push:
        branches: [main]
    workflow_dispatch:

    permissions:
    contents: read
    pages: write
    id-token: write

    concurrency:
    group: "pages"
    cancel-in-progress: false

    jobs:
    build:
        runs-on: ubuntu-latest
        steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v5
            with:
            python-version: "3.12"
        - run: uv sync --locked
        - run: uv run sphinx-build -b html docs/source public
        - uses: actions/upload-pages-artifact@v3
            with:
            path: public

    deploy:
        needs: build
        runs-on: ubuntu-latest
        environment:
        name: github-pages
        url: ${{ steps.deployment.outputs.page_url }}
        steps:
        - id: deployment
            uses: actions/deploy-pages@v4
    ```
- Se déclenche sur push vers main (+ lancement manuel possible), pas sur les PR.
- Workflow séparé de ci.yml (convention standard pour Pages).

- Dans les Settings du repo GitHub → Pages → Build and deployment → Source : sélectionner "GitHub Actions".

Une fois activé et le premier déploiement passé, la doc sera visible à https://nicolastchenio.github.io/simplon_projet7_horagor3/

Ajout du badge du taux de coverage :
- ajoute genbadge[coverage] comme dépendance de développement => ` uv add --dev "genbadge[coverage]" `
- modification de ci.yml. Génération XML, genbadge, commit conditionnel avec [skip ci] pour éviter la boucle CI.
    ```
    test:
        runs-on: ubuntu-latest
        permissions:
        contents: write
        env:
        JWT_SECRET_KEY: ci_test_secret_key
        AUTH_PASSWORD_HASH: ci_test_password_hash_placeholder
        steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v5
            with:
            python-version: "3.12"
        - run: uv sync --locked
        - run: uv run pytest --cov --cov-report=term-missing --cov-report=xml
        - run: uv run genbadge coverage -i coverage.xml -o coverage.svg
        - name: Commit coverage badge
            if: github.ref == 'refs/heads/main'
            run: |
            git config user.name "github-actions"
            git config user.email "github-actions@github.com"
            git add coverage.svg
            if ! git diff --staged --quiet; then
                git commit -m "chore: update coverage badge [skip ci]"
                git push origin HEAD:main
            fi
    ```
- coverage.xml n'est pas dans .gitignore (c'est un fichier généré, comme .coverage/htmlcov/) — je l'ajoute pour éviter qu'il soit commité par erreur en local.
- Ajout du badge de couverture dans le README.md (avec la bonne URL de repo cette fois).
` ![Coverage](https://raw.githubusercontent.com/nicolastchenio/simplon_projet7_horagor3/main/coverage.svg) `

    Point d'attention : le badge de couverture affichera une image cassée (404) jusqu'au premier push sur main qui exécutera le job test et créera coverage.svg à la racine du repo. C'est normal, ça se résout au premier push.