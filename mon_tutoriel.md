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
