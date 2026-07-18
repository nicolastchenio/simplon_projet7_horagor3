"""
Interface utilisateur Streamlit du projet HorRAGor (Phase 5.2).

Ce module relie le frontend au backend RAG via des appels HTTP
synchrones avec ``httpx``. Il gère l'affichage des bulles,
la persistance de la conversation par ``thread_id``, ainsi que
le rendu des sources et des indicateurs de scraping.

.. note::
    Le backend FastAPI doit être accessible sur ``localhost:8000``
    pour que le chat fonctionne.
"""

import uuid  # Génération d'identifiant unique de conversation

import httpx  # Client HTTP moderne, remplace ``requests`` et ``urllib``

import streamlit as st  # Framework de l'interface web

# --- Configuration centralisée de la connexion au backend --------------------
# On importe la source unique de vérité pour éviter tout hardcodage.
# L'utilisateur peut surcharger ces valeurs via le fichier .env :
#   API_BASE_URL=http://localhost:8000
#   API_TIMEOUT=120
from src.config import API_BASE_URL, API_TIMEOUT

def init_session_state() -> None:
    """
    Initialise les variables persistantes dans la session Streamlit.

    Crée deux clés dans ``st.session_state`` si elles sont absentes :

    - ``messages`` : liste des échanges (historique de conversation).
    - ``thread_id`` : identifiant UUID v4 servant de clé de session
      pour la mémorisation côté backend (``MemorySaver``).
    """
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "thread_id" not in st.session_state:
        # Génération d'un nouvel identifiant à chaque session navigateur
        st.session_state.thread_id = str(uuid.uuid4())

def call_chat_api(question: str, thread_id: str) -> dict:
    """
    Envoie une question au endpoint ``POST /chat`` du backend.
    """
    url: str = f"{API_BASE_URL}/chat"
    headers = {"Content-Type": "application/json"}
    payload: dict = {
        "message": question,
        "thread_id": thread_id,
    }

    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            resp: httpx.Response = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    except httpx.ConnectError as exc:
        return {
            "response": "Impossible de joindre l'entité HorRAGor (backend hors ligne).",
            "sources": [],
            "metadata": {},
        }

    except httpx.HTTPStatusError as exc:
        detail: str = "Erreur interne du backend."
        try:
            detail = exc.response.json().get("detail", detail)
        except Exception:
            pass
        return {
            "response": f"L'API a retourné une erreur : {detail}",
            "sources": [],
            "metadata": {},
        }

    except Exception as exc:
        return {
            "response": f"Erreur inattendue lors de l'invocation : {exc}",
            "sources": [],
            "metadata": {},
        }
    
def _render_source(source: dict, index: int) -> None:
    """
    Affiche une source documentaire dans un format lisible.

    Cette fonction gère le format réel retourné par l'API HorRAGor
    (``type``, ``score``, ``title``, ``year``, ``preview``). Si les
    champs sont partiellement vides, elle adapte le rendu pour éviter
    les encarts vides ou le JSON brut.

    Paramètres
    ----------
    source : dict
        Dictionnaire représentant une source du RAG.
    index : int
        Numéro d'ordre de la source (affiché devant le titre).
    """
    # Extraction défensive : chaque champ peut être absent ou None
    source_type: str = source.get("type", "inconnu")
    score: float | None = source.get("score")
    title: str | None = source.get("title")
    year: int | None = source.get("year")
    preview: str = source.get("preview", "")

    # Détermination du titre affiché
    display_title: str = title if title else f"Source {index} ({source_type})"

    # En-tête de la source
    st.markdown(f"**{index}. {display_title}**")

    # Ligne de métadonnées (score + année)
    meta_parts: list[str] = []
    if year is not None:
        meta_parts.append(f"Année : {year}")
    if score is not None:
        meta_parts.append(f"Score : {score:.3f}")
    if meta_parts:
        st.caption(" · ".join(meta_parts))

    # Aperçu du contenu
    if preview:
        # Limite à 300 caractères pour garder l'encart compact
        snippet: str = preview if len(preview) <= 300 else preview[:297] + "..."
        st.caption(f"> {snippet}")
    else:
        st.caption("*Aucun aperçu disponible pour cette entrée.*")

    st.divider()

def display_chat_history() -> None:
    """
    Affiche l'intégralité de la conversation depuis ``st.session_state``.

    Cette fonction boucle sur les messages stockés et restitue :

    - Les bulles utilisateur (texte simple).
    - Les bulles assistant (texte + sources + badge de scraping).

    .. note::
        Les sources et métadonnées ne sont affichées que si elles ont
        été préalablement stockées dans le message assistant.
    """
    for msg in st.session_state.messages:
        role: str = msg.get("role", "assistant")

        with st.chat_message(role):
            # Contenu textuel principal
            st.markdown(msg.get("content", ""))

            # --- Rendu spécifique aux réponses du bot -----------------------
            if role == "assistant":
                metadata: dict = msg.get("metadata") or {}

                # Badge indiquant un passage par le scraper Wikipédia
                if metadata.get("enriched_from_web") is True:
                    st.caption("🔍 Enrichi via le Web")

                # Encart dépliable listant les sources du RAG
                sources: list = msg.get("sources", [])
                if sources:
                    with st.expander("📚 Sources utilisées", expanded=False):
                        for idx, source in enumerate(sources, start=1):
                            if isinstance(source, dict):
                                _render_source(source, idx)
                            else:
                                # Filet de sécurité si une source serait une chaîne
                                st.markdown(f"**{idx}.** {str(source)[:300]}")
                                st.divider()

def handle_user_input() -> None:
    """
    Gère le cycle complet : saisie utilisateur → appel API → affichage bot.

    Cette fonction orchestre l'interaction :

    1. Récupère la saisie via ``st.chat_input``.
    2. Affiche immédiatement la bulle utilisateur.
    3. Déclenche l'appel au backend dans un **spinner**.
    4. Affiche la réponse, les sources et le badge éventuel.
    5. Persiste le message assistant (y compris ses métadonnées) dans le
       ``session_state`` pour les prochains rafraîchissements.
    """
    if prompt := st.chat_input("Poser moi une question..."):
        # 1. Persistance et affichage immédiat du message utilisateur
        user_msg = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_msg)

        with st.chat_message("user"):
            st.markdown(prompt)

        # 2. Appel au backend avec retour visuel pendant la latence
        with st.chat_message("assistant"):
            with st.spinner("L'entité HorRAGor consulte les archives..."):
                response_data: dict = call_chat_api(
                    question=prompt,
                    thread_id=st.session_state.thread_id,
                )

            # 3. Traitement de la réponse ou gestion d'une erreur vide
            if response_data:
                answer_text: str = response_data.get("response", "")
                st.markdown(answer_text)

                # Badge scraper (affiché seulement si le backend l'indique)
                metadata: dict = response_data.get("metadata") or {}
                if metadata.get("enriched_from_web") is True:
                    st.caption("🔍 Enrichi via le Web")

                # Encart des sources (affiché seulement si la liste est non vide)
                sources: list = response_data.get("sources", [])
                if sources:
                    with st.expander("📚 Sources utilisées", expanded=False):
                        for idx, source in enumerate(sources, start=1):
                            if isinstance(source, dict):
                                _render_source(source, idx)
                            else:
                                st.markdown(f"**{idx}.** {str(source)[:300]}")
                                st.divider()

                # 4. Stockage riche dans l'historique pour persistance complète
                assistant_msg = {
                    "role": "assistant",
                    "content": answer_text,
                    "sources": sources,
                    "metadata": metadata,
                }
                st.session_state.messages.append(assistant_msg)

            else:
                # ``call_chat_api`` a déjà affiché l'erreur via ``st.error``,
                # mais on sauvegarde un message d'échec pour l'historique.
                error_text: str = "Désolé, je n'ai pas pu contacter les archives."
                st.error(error_text)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_text,
                    "sources": [],
                    "metadata": {},
                })
  
def main() -> None:
    """
    Point d'entrée de l'application Streamlit.

    Configure la page, initialise l'état, affiche l'historique existant
    et écoute les nouvelles questions utilisateur.
    """
    st.set_page_config(
        page_title="HorRAGor - Archives Vivantes",
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    # --- Style minimal : suppression de la bannière "Help agents" (optionnel) ---
    st.markdown(
        """
        <style>
        [data-testid="stToolbar"] {display: none !important;}
        </style>
        """,
        unsafe_allow_html=True
    )

    st.title("🧠 HorRAGor")
    st.caption(
        "L'agent ia de l'horreur (il connait tout les films sur l'horreur) — "
        "Projet Simplon Data Engineer"
    )
    st.divider()

    # Initialisation et affichage
    init_session_state()
    display_chat_history()
    handle_user_input()

    # Sidebar de debug / contexte
    with st.sidebar:
        st.header("🔧 Contexte technique")
        st.markdown(
            f"- **Thread ID :** `{st.session_state.thread_id}`\n"
            f"- **Messages en mémoire :** {len(st.session_state.messages)}\n"
            f"- **Backend visé :** `{API_BASE_URL}`"
        )
        

if __name__ == "__main__":
    main()