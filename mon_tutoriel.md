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
4. creation du .gitIgnre