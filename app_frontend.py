"""
Interface utilisateur Streamlit du projet HorRAGor (Phase 7 - Auth + TLS).

Ce module gère :
- L'authentification JWT (login, refresh, logout)
- La communication HTTPS sécurisée avec l'API Intelligence
- L'affichage du chat avec gestion des sources
- L'expiration automatique des tokens
"""

import os
import uuid
import json
import base64
from datetime import datetime, timedelta
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
# CONFIGURATION TLS (Phase 7.3)
# ============================================================================

# 🔒 Certificat auto-signé de l'API Intelligence.
# 
# httpx doit faire confiance à CE certificat précis (pas verify=False !).
# La variable d'env SSL_CERT_PATH est définie dans docker-compose.yml.
# En local (hors Docker), elle prend la valeur par défaut /app/certs/cert.pem.
#
# Pourquoi ? Parce que l'API Intelligence est maintenant en HTTPS (TLS).
# Sans ce certificat, httpx refuse la connexion avec : SSL: CERTIFICATE_VERIFY_FAILED
SSL_VERIFY = os.getenv("SSL_CERT_PATH", "/app/certs/cert.pem")

# ============================================================================
# UTILITAIRES JWT
# ============================================================================

def decode_jwt_payload(token: str) -> dict | None:
    """
    Décode le payload d'un JWT sans vérifier la signature.
    
    Format JWT : header.payload.signature
    
    Args:
        token: Le token JWT complet (string)
    
    Returns:
        dict | None: Le contenu du payload (claims), ou None si erreur
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Le payload est la 2e partie, avec padding base64
        payload = parts[1]
        # Ajouter le padding si nécessaire
        padding = 4 - (len(payload) % 4)
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)

    except Exception as e:
        print(f"❌ Erreur décodage JWT : {e}")
        return None


def get_token_expiration(token: str) -> datetime | None:
    """
    Retourne la date/heure d'expiration du token.
    
    Args:
        token: Le token JWT
    
    Returns:
        datetime | None: La date d'expiration, ou None si pas trouvée
    """
    payload = decode_jwt_payload(token)
    if payload and "exp" in payload:
        return datetime.fromtimestamp(payload["exp"])
    return None


def is_token_expired_soon(token: str, threshold_seconds: int = 300) -> bool:
    """
    Vérifie si le token expire dans moins de threshold_seconds (default 5 min).
    
    Args:
        token: Le token JWT
        threshold_seconds: Seuil d'alerte avant expiration (en secondes)
    
    Returns:
        bool: True si le token expire bientôt ou est déjà expiré
    """
    expiration = get_token_expiration(token)
    if not expiration:
        return True  # Token invalide = considéré comme expiré

    now = datetime.utcnow()
    time_until_expiry = (expiration - now).total_seconds()

    return time_until_expiry < threshold_seconds


def get_token_remaining_time(token: str) -> str:
    """
    Retourne un texte lisible du temps restant avant expiration du token.
    
    Args:
        token: Le token JWT
    
    Returns:
        str: Texte formaté du temps restant (ex: "⏱️ 12m 34s")
    """
    expiration = get_token_expiration(token)
    if not expiration:
        return "❓ Impossible à déterminer"

    now = datetime.utcnow()
    remaining = expiration - now

    if remaining.total_seconds() <= 0:
        return "⏰ EXPIRÉ"

    minutes = int(remaining.total_seconds() // 60)
    seconds = int(remaining.total_seconds() % 60)

    if minutes > 0:
        return f"⏱️ {minutes}m {seconds}s"
    else:
        return f"⏱️ {seconds}s"


# ============================================================================
# INITIALISATION SESSION STATE
# ============================================================================

def init_session_state() -> None:
    """
    Initialise les variables persistantes dans la session Streamlit.
    
    Crée les clés suivantes si elles n'existent pas :
    - access_token: Le JWT pour accéder à l'API
    - refresh_token: Le JWT pour renouveler l'access_token
    - user: Le nom d'utilisateur connecté
    - messages: L'historique du chat
    - thread_id: L'identifiant de la conversation
    """
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
    """
    Appelle POST /auth/login et stocke les tokens en cas de succès.
    
    Cette fonction :
    1. Envoie les credentials à l'endpoint /auth/login (HTTPS)
    2. Reçoit access_token + refresh_token
    3. Les stocke dans st.session_state
    
    Args:
        username: L'identifiant de l'utilisateur
        password: Le mot de passe
    
    Returns:
        bool: True si login réussi, False sinon
    """
    url = f"{API_BASE_URL}/auth/login"
    payload = {"username": username, "password": password}

    try:
        # 🔒 MODIFICATION TLS : ajout de verify=SSL_VERIFY
        # Cela dit à httpx de faire confiance au certificat dans SSL_VERIFY
        with httpx.Client(timeout=API_TIMEOUT, verify=SSL_VERIFY) as client:
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
    """
    Appelle POST /auth/refresh pour obtenir un nouvel access_token.
    
    Utilise le refresh_token stocké pour demander un nouvel access_token
    sans que l'utilisateur ait à se reconnecter.
    
    Returns:
        bool: True si refresh réussi, False sinon
    """
    if not st.session_state.refresh_token:
        return False

    url = f"{API_BASE_URL}/auth/refresh"
    payload = {"refresh_token": st.session_state.refresh_token}

    try:
        # 🔒 MODIFICATION TLS : ajout de verify=SSL_VERIFY
        with httpx.Client(timeout=API_TIMEOUT, verify=SSL_VERIFY) as client:
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
    """
    Efface tous les tokens et réinitialise la session.
    
    Appelée quand :
    - L'utilisateur clique sur "Se déconnecter"
    - Le token est expiré et impossible à renouveler
    """
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.user = None
    st.session_state.messages = []
    st.session_state.thread_id = str(uuid.uuid4())


# ============================================================================
# APPEL API
# ============================================================================

def call_chat_api(question: str, thread_id: str) -> dict | None:
    """
    Envoie une question à POST /chat avec authentification JWT.
    
    Cette fonction gère :
    1. Vérification proactive de l'expiration du token (refresh si besoin)
    2. Envoi de la question avec le header Authorization: Bearer <token>
    3. Gestion des réponses 200, 401 (token expiré), et erreurs
    4. Appel automatique du refresh si 401
    
    Args:
        question: La question posée par l'utilisateur
        thread_id: L'identifiant de la conversation
    
    Returns:
        dict | None: La réponse JSON de l'API, ou None si erreur
    """

    # 🔴 VÉRIFICATION PROACTIVE : Token expire bientôt ?
    # Si oui, on le renouvelle AVANT de faire l'appel API
    if st.session_state.access_token and is_token_expired_soon(st.session_state.access_token, threshold_seconds=300):
        if refresh_access_token():
            st.info("🔄 Token renouvelé automatiquement.")
        else:
            st.error("❌ Impossible de renouveler le token. Reconnexion nécessaire.")
            logout()
            st.rerun()
            return None

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
        # 🔒 MODIFICATION TLS : ajout de verify=SSL_VERIFY
        with httpx.Client(timeout=API_TIMEOUT, verify=SSL_VERIFY) as client:
            resp = client.post(url, headers=headers, json=payload)

            if resp.status_code == 200:
                return resp.json()

            elif resp.status_code == 401:
                # Token expiré → essai de refresh + retry
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
    """
    Affiche une source documentaire dans un format lisible.
    
    Affiche : titre, année, score de pertinence, et aperçu du contenu.
    
    Args:
        source: Dictionnaire contenant les métadatas de la source
        index: Numéro de la source (pour l'affichage)
    """
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
    """
    Affiche l'intégralité de la conversation.
    
    Pour chaque message :
    - Affiche le rôle (user/assistant) avec sa bulle de chat
    - Si assistant : affiche les sources et métadatas
    """
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
    """
    Gère le cycle complet : saisie utilisateur → appel API → affichage bot.
    
    Flux :
    1. Récupère la saisie via st.chat_input()
    2. Ajoute le message utilisateur à l'historique
    3. Appelle call_chat_api()
    4. Affiche la réponse du bot + sources
    5. Ajoute le message assistant à l'historique
    """
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
    """
    Affiche la page de login.
    
    Contient :
    - Formulaire (username + password)
    - Bouton "Se connecter"
    - Message d'aide avec identifiants de démo
    """
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
    """
    Affiche le chat avec le bouton déconnexion dans le sidebar.
    
    Contient :
    - Titre et description du projet
    - Historique du chat
    - Saisie utilisateur
    - Sidebar avec infos techniques + bouton de déconnexion
    """

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

        # 🔴 Affichage de l'expiration du token
        remaining_time = get_token_remaining_time(st.session_state.access_token) if st.session_state.access_token else "N/A"

        st.markdown(
            f"- **User :** `{st.session_state.user}`\n"
            f"- **Thread ID :** `{st.session_state.thread_id}`\n"
            f"- **Messages :** {len(st.session_state.messages)}\n"
            f"- **Token expire :** {remaining_time}\n"
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
    """
    Point d'entrée principal : affiche login OU chat selon l'authentification.
    
    Logique :
    - Si pas de access_token → affiche la page de login
    - Si access_token présent → affiche la page de chat
    """
    init_session_state()

    if not st.session_state.access_token:
        show_login_page()
    else:
        show_chat_page()


if __name__ == "__main__":
    main()