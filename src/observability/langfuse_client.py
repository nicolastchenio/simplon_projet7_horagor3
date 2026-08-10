"""
src/observability/langfuse_client.py
====================================
Couche d'observabilité Langfuse pour le graphe HorRAGor (Phase 8).

Ce module encapsule **toute** l'interaction avec Langfuse afin que le
reste de l'application n'en dépende jamais directement. Il expose une
fonction unique, :func:`get_langfuse_handler`, qui retourne soit un
``CallbackHandler`` prêt à l'emploi, soit ``None``.

.. admonition:: Principe de dégradation gracieuse
    :class: important

    L'observabilité est un **outil de diagnostic**, jamais une
    dépendance critique. Si Langfuse est désactivé (``LANGFUSE_ENABLED
    = False``), si le paquet n'est pas installé, ou si le serveur est
    injoignable, l'agent doit continuer à répondre aux utilisateurs.
    C'est pourquoi chaque échec est capturé et transformé en ``None``
    plutôt qu'en exception propagée.

Architecture
------------
::

    src/main.py  ──appelle──►  get_langfuse_handler()
                                      │
                                      ├─ Langfuse OFF ──► None
                                      ├─ import KO ─────► None
                                      └─ OK ────────────► CallbackHandler
                                                              │
                                                    (passé dans config
                                                     de graph.invoke)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src import config

# ═══════════════════════════════════════════════════════════════
# Singleton module-level
# ═══════════════════════════════════════════════════════════════
# Le CallbackHandler est thread-safe et réutilisable entre requêtes.
# On l'instancie une seule fois au premier appel pour éviter de
# recréer un client HTTP à chaque message utilisateur.
#
# Le sentinelle `_NOT_INITIALIZED` permet de distinguer trois états :
#   - _NOT_INITIALIZED : jamais tenté
#   - None             : tenté, échoué ou désactivé (ne pas réessayer)
#   - CallbackHandler  : tenté, réussi
# ═══════════════════════════════════════════════════════════════
_NOT_INITIALIZED = object()
_handler: Any = _NOT_INITIALIZED

def _build_handler() -> Any | None:
    """Instancie le ``CallbackHandler`` Langfuse (usage interne).

    Cette fonction n'est appelée qu'une seule fois par
    :func:`get_langfuse_handler`. Elle vérifie successivement :

    1. Que l'observabilité est activée en configuration ;
    2. Que le paquet ``langfuse`` est bien installé ;
    3. Que l'instanciation du handler réussit.

    :returns: Un ``CallbackHandler`` opérationnel, ou ``None`` si l'une
        des trois conditions ci-dessus n'est pas remplie.
    """
    # ── 1. Interrupteur de configuration ──
    # LANGFUSE_ENABLED vaut True uniquement si les deux clés
    # (publique et secrète) sont présentes dans l'environnement.
    if not config.LANGFUSE_ENABLED:
        logger.info("Langfuse désactivé (clés absentes ou LANGFUSE_ENABLED=false).")
        return None

    # ── 2. Import tardif (lazy import) ──
    # On importe ici et non en tête de module : ainsi, si le paquet
    # `langfuse` n'est pas installé, seul ce module échoue silencieusement
    # au lieu de bloquer le démarrage complet de l'API.
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError as exc:
        logger.warning(
            f"Paquet 'langfuse' introuvable ({exc}). "
            "Observabilité désactivée. Installez-le avec : uv pip install langfuse"
        )
        return None

    # ── 3. Instanciation ──
    # Les credentials sont lus automatiquement par le SDK depuis les
    # variables d'environnement LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
    # / LANGFUSE_HOST, que src.config a déjà chargées via python-dotenv.
    try:
        handler = CallbackHandler()
        logger.info(f"✅ Langfuse actif — traces envoyées vers {config.LANGFUSE_HOST}")
        return handler
    except Exception as exc:  # noqa: BLE001 — on veut TOUT capturer ici
        logger.warning(
            f"Échec d'initialisation du CallbackHandler Langfuse : {exc}. "
            "L'agent continue sans observabilité."
        )
        return None

def get_langfuse_handler() -> Any | None:
    """Retourne le ``CallbackHandler`` Langfuse partagé (ou ``None``).

    Point d'entrée public du module. Applique un **cache module-level** :
    la construction n'est tentée qu'une seule fois par processus, les
    appels suivants retournent immédiatement la valeur mémorisée.

    **Usage typique** dans un endpoint FastAPI ::

        handler = get_langfuse_handler()
        callbacks = [handler] if handler else []
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": callbacks,
        }
        result = graph.invoke(state, config)

    :returns: Le handler à injecter dans ``config["callbacks"]``, ou
        ``None`` si l'observabilité est indisponible.
    """
    global _handler

    if _handler is _NOT_INITIALIZED:
        _handler = _build_handler()

    return _handler

def flush_langfuse() -> None:
    """Force l'envoi immédiat des traces en attente vers le serveur.

    Le SDK Langfuse utilise un **buffer asynchrone** : les traces sont
    accumulées en mémoire puis envoyées par lots en tâche de fond. Cela
    évite de ralentir les requêtes utilisateur, mais présente un risque :
    si le processus s'arrête brutalement, les traces non envoyées sont
    perdues.

    Cette fonction est donc appelée dans le ``lifespan`` de FastAPI, à
    l'extinction du serveur, pour garantir qu'aucune trace ne disparaît.

    .. note::
        Sans effet si Langfuse est désactivé.
    """
    handler = get_langfuse_handler()
    if handler is None:
        return

    try:
        # Depuis langfuse v3, le client global expose flush().
        from langfuse import get_client

        get_client().flush()
        logger.info("Traces Langfuse vidées (flush) avant extinction.")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Échec du flush Langfuse : {exc}")