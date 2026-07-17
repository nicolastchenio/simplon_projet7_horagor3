"""
Interface utilisateur Streamlit du projet HorRAGor.

Ce module implémente le frontend du chatbot (Phase 5). Il gère
l'affichage de l'historique de conversation sous forme de bulles,
la saisie utilisateur et le feedback visuel (spinner) pendant
le traitement des requêtes par le backend RAG.

L'appel réseau vers l'API FastAPI (``localhost:8000/chat``) sera
intégré lors de la Phase 5.2.

.. note::
    Pour l'instant, la réponse du bot est simulée afin de valider
    le rendu graphique de l'interface.
"""

import uuid  # Permet de générer un identifiant unique de conversation
import time  # Utilisé temporairement pour simuler la latence de l'API

import streamlit as st  # Framework de l'interface web

def init_session_state() -> None:
    """
    Initialise les variables persistantes dans la session Streamlit.

    Cette fonction s'assure que les clés suivantes existent dans
    ``st.session_state`` dès le premier chargement de la page :

    - ``messages`` : liste des échanges (bulles affichées).
    - ``thread_id`` : identifiant unique de conversation, transmis
      au backend pour gérer l'historique via ``MemorySaver``.

    .. warning::
        Cette fonction doit être appelée avant tout affichage
        pour éviter les erreurs d'accès à des clés inexistantes.
    """
    # Historique des messages : chaque entrée est un dictionnaire
    # décrivant un échange (rôle, contenu, sources éventuelles).
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Identifiant de conversation (thread) pour la mémoire LangGraph.
    # Généré une seule fois et conservé tant que l'onglet est ouvert.
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
        
def display_chat_history() -> None:
    """
    Parcourt et affiche l'historique des messages en mémoire.

    Utilise :func:`streamlit.chat_message` pour rendre chaque échange
    sous forme de bulle. Les rôles reconnus sont ``user`` et
    ``assistant`` (avatars différents automatiquement).

    Si un message contient des sources (clé ``sources``), celles-ci
    sont affichées dans un encart repliable sous la bulle du bot.
    """
    # Boucle sur tous les messages stockés dans la session
    for message in st.session_state.messages:
        role = message.get("role", "assistant")
        content = message.get("content", "")

        # Affichage de la bulle avec l'avatar adapté (👤 / 🤖)
        with st.chat_message(role):
            st.markdown(content)

            # Encart pour les métadonnées de type "source" (préparation Phase 5.2)
            sources = message.get("sources")
            if sources:
                with st.expander("📚 Sources consultées", expanded=False):
                    for src in sources:
                        st.caption(f"• {src}")
                        
def handle_user_input() -> None:
    """
    Gère la saisie utilisateur et l'affichage de la réponse du bot.

    1. Capture le texte via :func:`streamlit.chat_input`.
    2. Ajoute immédiatement la bulle utilisateur à l'historique.
    3. Déclenche un spinner visuel pendant le "traitement".
    4. Simule une réponse (placeholder) et l'affiche en bulle assistant.

    .. todo::
        Remplacer la simulation ``time.sleep`` par un appel ``httpx``
        vers le endpoint ``POST /chat`` du backend (Phase 5.2).
    """
    # Zone de saisie fixée en bas de l'écran.
    # Renvoie ``None`` tant que l'utilisateur n'a pas appuyé sur Entrée.
    user_message = st.chat_input("Parlez à l'entité HorRAGor...")

    if user_message:
        # -- 1. Stockage et affichage immédiat du message utilisateur --
        st.session_state.messages.append({
            "role": "user",
            "content": user_message,
            "sources": None
        })

        with st.chat_message("user"):
            st.markdown(user_message)

        # -- 2. Phase de "réflexion" du bot avec spinner --
        # Le bloc ``with st.spinner()`` affiche une animation en haut de
        # l'écran pendant que le backend (simulé ici) travaille.
        with st.spinner("L'entité HorRAGor consulte les archives..."):
            # SIMULATION (à supprimer dès la Phase 5.2) :
            # On attend 1,5 seconde pour imiter la latence réseau + RAG.
            time.sleep(1.5)

            # Réponse factice permettant de valider le rendu de l'UI.
            # En vrai, ce contenu proviendra de la clé ``response`` du JSON
            # renvoyé par FastAPI.
            bot_content = (
                f"**Écho de l'entité :** j'ai capté votre message.\n\n"
                f"🔗 *La vraie connexion API sera établie en Phase 5.2*\n\n"
                f"🆔 Thread ID : `{st.session_state.thread_id}`"
            )
            bot_sources = []  # Placeholder : liste des chunks/scraper metadata

        # -- 3. Stockage et affichage de la réponse assistant --
        st.session_state.messages.append({
            "role": "assistant",
            "content": bot_content,
            "sources": bot_sources
        })

        with st.chat_message("assistant"):
            st.markdown(bot_content)
            
def main() -> None:
    """
    Point d'entrée principal de l'application Streamlit.

    Configure la page (titre, icône, layout), initialise l'état de
    session, affiche l'historique existant et se met en écoute des
    nouvelles entrées utilisateur.
    """
    # Configuration du rendu de la page dans le navigateur
    st.set_page_config(
        page_title="HorRAGor - Archives Vivantes",
        page_icon="🧠",            # Emoji de l'onglet
        layout="centered",         # Design centré, lisible sur mobile
        initial_sidebar_state="collapsed"
    )

    # En-tête visuel de l'application
    st.title("🧠 HorRAGor")
    st.caption(
        "Assistant conversationnel pour l'exploration des archives de l'ESILV — "
        "Projet Simplon Data Engineer"
    )
    st.divider()

    # Initialisation des variables de session (historique + thread_id)
    init_session_state()

    # Affichage des bulles déjà présentes en mémoire
    display_chat_history()

    # Écoute et traitement de la saisie interactive
    handle_user_input()

    # -- Sidebar informative (optionnel, utile pour le debug / la soutenance) --
    with st.sidebar:
        st.header("🔧 Contexte technique")
        st.markdown(
            f"- **Thread ID :** `{st.session_state.thread_id}`\n"
            f"- **Messages en mémoire :** {len(st.session_state.messages)}\n"
            f"- **Étape en cours :** 5.1 (UI nude)"
        )


if __name__ == "__main__":
    main()