"""
Interface utilisateur Streamlit du projet HorRAGor (Phase 7 - Auth).
"""

import uuid
import httpx
import streamlit as st
from src.config import API_BASE_URL, API_TIMEOUT

# 🔴 DOIT ÊTRE AVANT TOUT AUTRE CODE STREAMLIT
st.set_page_config(
    page_title="HorRAGor - Chat IA",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# INITIALISATION SESSION STATE
# ============================================================================

def init_session_state() -> None:
    """Initialise les variables persistantes dans la session Streamlit."""
    if "access_token" not in st.session_state:
        st.session_state.access_token = None
    if "refresh_token" not in st.session_state:
        st.session_state.refresh_token = None
    if "user" not in st.session_state:
        st.session_state.user = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())

# ============================================================================
# AUTHENTIFICATION
# ============================================================================

def login(username: str, password: str) -> bool:
    """Appelle POST /auth/login et stocke les tokens si succès."""
    url = f"{API_BASE_URL}/auth/login"
    payload = {"username": username, "password": password}

    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()

            data = resp.json()
            st.session_state.access_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.user = username
            return True

    except httpx.HTTPStatusError as exc:
        detail = "Identifiant ou mot de passe incorrect."
        try:
            detail = exc.response.json().get("detail", detail)
        except Exception:
            pass
        st.error(f"❌ Erreur de connexion : {detail}")
        return False

    except Exception as exc:
        st.error(f"❌ Erreur inattendue : {exc}")
        return False

def refresh_access_token() -> bool:
    """Appelle POST /auth/refresh pour obtenir un nouvel access_token."""
    if not st.session_state.refresh_token:
        return False

    url = f"{API_BASE_URL}/auth/refresh"
    payload = {"refresh_token": st.session_state.refresh_token}

    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()

            data = resp.json()
            st.session_state.access_token = data["access_token"]
            if "refresh_token" in data:
                st.session_state.refresh_token = data["refresh_token"]
            return True

    except Exception:
        return False

def logout() -> None:
    """Efface tous les tokens et redéfinit la session."""
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.user = None
    st.session_state.messages = []
    st.session_state.thread_id = str(uuid.uuid4())

# ============================================================================
# APPEL API
# ============================================================================

def call_chat_api(question: str, thread_id: str) -> dict | None:
    """Envoie une question à POST /chat avec authentification JWT."""
    url = f"{API_BASE_URL}/chat"
    payload = {
        "message": question,
        "thread_id": thread_id,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.access_token}",
    }

    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            resp = client.post(url, headers=headers, json=payload)

            if resp.status_code == 200:
                return resp.json()

            elif resp.status_code == 401:
                st.info("🔄 Token expiré, renouvellement en cours...")

                if refresh_access_token():
                    headers["Authorization"] = f"Bearer {st.session_state.access_token}"
                    resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return resp.json()
                    else:
                        st.error("❌ Impossible de se reconnecter après refresh.")
                        logout()
                        st.rerun()
                        return None
                else:
                    st.error("❌ Votre session a expiré. Reconnexion nécessaire.")
                    logout()
                    st.rerun()
                    return None
            else:
                detail = "Erreur interne du backend."
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                st.error(f"❌ Erreur {resp.status_code} : {detail}")
                return None

    except httpx.ConnectError:
        st.error("❌ Impossible de joindre le backend (hors ligne).")
        return None

    except Exception as exc:
        st.error(f"❌ Erreur inattendue : {exc}")
        return None

# ============================================================================
# AFFICHAGE
# ============================================================================

def _render_source(source: dict, index: int) -> None:
    """Affiche une source documentaire."""
    source_type = source.get("type", "inconnu")
    score = source.get("score")
    title = source.get("title")
    year = source.get("year")
    preview = source.get("preview", "")

    display_title = title if title else f"Source {index} ({source_type})"
    st.markdown(f"**{index}. {display_title}**")

    meta_parts = []
    if year is not None:
        meta_parts.append(f"Année : {year}")
    if score is not None:
        meta_parts.append(f"Score : {score:.3f}")
    if meta_parts:
        st.caption(" · ".join(meta_parts))

    if preview:
        snippet = preview if len(preview) <= 300 else preview[:297] + "..."
        st.caption(f"> {snippet}")
    else:
        st.caption("*Aucun aperçu disponible pour cette entrée.*")

    st.divider()

def display_chat_history() -> None:
    """Affiche l'intégralité de la conversation."""
    for msg in st.session_state.messages:
        role = msg.get("role", "assistant")

        with st.chat_message(role):
            st.markdown(msg.get("content", ""))

            if role == "assistant":
                metadata = msg.get("metadata") or {}

                if metadata.get("enriched_from_web") is True:
                    st.caption("🔍 Enrichi via le Web")

                sources = msg.get("sources", [])
                if sources:
                    with st.expander("📚 Sources utilisées", expanded=False):
                        for idx, source in enumerate(sources, start=1):
                            if isinstance(source, dict):
                                _render_source(source, idx)
                            else:
                                st.markdown(f"**{idx}.** {str(source)[:300]}")
                                st.divider()

def handle_user_input() -> None:
    """Gère le cycle complet : saisie utilisateur → appel API → affichage bot."""
    if prompt := st.chat_input("Poser moi une question..."):
        user_msg = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_msg)

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("L'entité HorRAGor consulte les archives..."):
                response_data = call_chat_api(
                    question=prompt,
                    thread_id=st.session_state.thread_id,
                )

            if response_data:
                answer_text = response_data.get("response", "")
                st.markdown(answer_text)

                metadata = response_data.get("metadata") or {}
                if metadata.get("enriched_from_web") is True:
                    st.caption("🔍 Enrichi via le Web")

                sources = response_data.get("sources", [])
                if sources:
                    with st.expander("📚 Sources utilisées", expanded=False):
                        for idx, source in enumerate(sources, start=1):
                            if isinstance(source, dict):
                                _render_source(source, idx)
                            else:
                                st.markdown(f"**{idx}.** {str(source)[:300]}")
                                st.divider()

                assistant_msg = {
                    "role": "assistant",
                    "content": answer_text,
                    "sources": sources,
                    "metadata": metadata,
                }
                st.session_state.messages.append(assistant_msg)

            else:
                error_text = "Désolé, je n'ai pas pu contacter les archives."
                st.error(error_text)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_text,
                    "sources": [],
                    "metadata": {},
                })

# ============================================================================
# PAGE DE LOGIN
# ============================================================================

def show_login_page() -> None:
    """Affiche la page de login."""
    st.title("🧠 HorRAGor")
    st.caption("L'agent IA de l'horreur — Authentification requise")
    st.divider()

    st.subheader("🔐 Connexion")

    username = st.text_input("Identifiant", placeholder="admin", key="login_user")
    password = st.text_input("Mot de passe", type="password", placeholder="motdepasse123", key="login_pass")

    if st.button("Se connecter", use_container_width=True, type="primary"):
        if username and password:
            if login(username, password):
                st.success("✅ Connexion réussie !")
                st.rerun()
        else:
            st.warning("⚠️ Veuillez remplir tous les champs.")

    st.divider()
    st.caption("📝 **Démo :** admin / motdepasse123")

# ============================================================================
# PAGE CHAT
# ============================================================================

def show_chat_page() -> None:
    """Affiche le chat avec le bouton déconnexion dans le sidebar."""

    st.title("🧠 HorRAGor")

    st.caption(
        "L'agent IA de l'horreur (il connait tous les films d'horreur) — "
        "Projet Simplon Data Engineer"
    )
    st.divider()

    # Historique et saisie
    display_chat_history()
    handle_user_input()

    # SIDEBAR - Infos techniques + Bouton déconnexion
    with st.sidebar:
        st.header("🔧 Contexte technique")
        st.markdown(
            f"- **User :** `{st.session_state.user}`\n"
            f"- **Thread ID :** `{st.session_state.thread_id}`\n"
            f"- **Messages :** {len(st.session_state.messages)}\n"
            f"- **Backend :** `{API_BASE_URL}`"
        )
        
        # Divider pour séparer les infos du bouton
        st.sidebar.divider()
        
        # 🔴 BOUTON DÉCONNEXION DANS LE SIDEBAR
        if st.sidebar.button("🚪 Se déconnecter", use_container_width=True, type="secondary", key="logout_btn"):
            logout()
            st.rerun()

# ============================================================================
# POINT D'ENTRÉE PRINCIPAL
# ============================================================================

def main() -> None:
    """Point d'entrée : affiche login OU chat selon l'authentification."""
    init_session_state()

    if not st.session_state.access_token:
        show_login_page()
    else:
        show_chat_page()

if __name__ == "__main__":
    main()