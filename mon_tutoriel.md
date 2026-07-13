# phase 0 :Préparation & Rattrapage des éléments de la Partie 2 #
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

### 1.1 Générer l'index FAISS depuis Supabase ###

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
