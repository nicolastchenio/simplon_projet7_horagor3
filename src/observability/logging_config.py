"""
src/observability/logging_config.py
===================================
Configuration centralisée de Loguru pour la couche Intelligence.

Conformément aux exigences de Phase 8.2 :

1. **Centralisation** — absorbée par ``setup_logging()`` au démarrage,
   avant tout import de module susceptible de logger.
2. **Structuration** — le format JSON aplati ``flatten_loguru_record``
   produisit un enregistrement par ligne avec les champs :
   ``timestamp``, ``level``, ``level_no``, ``message``, ``module``,
   ``function``, ``file``, ``file_path``, ``line``, ``process_id``,
   ``thread_id``, ``thread_name``, ``service`` + clés de ``record["extra"]``.
3. **Contexte** — enrichissement via ``.bind()`` (request_id, user_id…).
4. **Niveaux** — configurables via ``LOG_LEVEL``.
5. **Persistance** — stdout (format lisible) + fichier log au choix :

   - ``LOG_JSON=True`` : une ligne JSON aplatie par message via
     ``JsonFileSink`` (rotation par taille, thread-safe).
   - ``LOG_JSON=False`` : fichier texte formaté avec rotation/retention
     Loguru native.

6. **Interception stdlib** — ``InterceptHandler`` redirige les logs
   ``logging`` (uvicorn, FastAPI, Starlette, httpx, langfuse…)
   vers le pipeline Loguru.

Sorties configurées : ``stdout`` + ``./logs/intelligence_api.log``
(chemin absolu через ``LOG_DIR``).
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import (
    LOG_DIR,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_JSON,
    LOG_LEVEL,
)
from src.observability.json_serializer import flatten_loguru_record

#: Chemin canonique du fichier de log (dérivé de LOG_DIR).
LOG_FILE_PATH: Path = LOG_DIR / "intelligence_api.log"


class JsonFileSink:
    """
    Sink Loguru — sink personnalisé pour logs JSON aplatis.

    Écrit une ligne JSON par message, avec rotation par taille.
    Thread-safe grâce à un ``threading.Lock``.

    Les attributs ``path``, ``max_bytes`` et ``backup_count`` sont
    documentés au niveau de :meth:`__init__` (mêmes noms, mêmes types).

    :note:
        La rotation suit la convention Loguru : ``{path}.1``,
        ``{path}.2``, … ``{path}.{backup_count}``. Les fichiers excedentaires
        sont supprimés.

    .. warning::
        Ce sink ne doit **pas** être utilisé avec ``serialize=True``
        (qui produirait du JSON imbriqué ``{"text":..., "record":{...}}``).
        On utilise ici un callable sink qui appelle directement
        ``flatten_loguru_record(message.record)``.
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int,
        backup_count: int,
    ) -> None:
        """
        Initialise le sink JSON.

        :param path: Chemin du fichier de log.
        :param max_bytes: Seuil de taille (octets) déclenchant la rotation.
        :param backup_count: Nombre de fichiers de backup conservés.
        """
        self.path: Path = path
        self.max_bytes: int = max_bytes
        self.backup_count: int = backup_count
        self._lock: threading.Lock = threading.Lock()

    # ── Interface Loguru ────────────────────────────────────────────────────

    def __call__(self, message: Any) -> None:
        """
        Récepteur invoqué par Loguru pour chaque message.

        Sérialise le record Loguru en JSON aplati, l'écrit dans le
        fichier, puis vérifie si la rotation est nécessaire.

        :param message: Objet ``loguru.Message`` fourni par Loguru.
        :type message: loguru.Message
        """
        record: dict[str, Any] = message.record  # type: ignore[attr-defined]
        flattened: dict[str, Any] = flatten_loguru_record(record)
        line: str = json.dumps(flattened, ensure_ascii=False, default=str) + "\n"

        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)  

        self._rotate()

    def get_path(self) -> Path:
        """
        Retourne le chemin du fichier principal (sans suffixe ``.N``).

        :returns: Chemin du fichier principal.
        :rtype: Path
        """
        return self.path

    # ── Rotation manuelle ────────────────────────────────────────────────────

    def _rotate(self) -> None:
        """
        Vérifie la taille du fichier courant et effectue la rotation
        si ``max_bytes`` est dépassé.

        Déroule les backups d'un cran (``{path}.{n}`` → ``{path}.{n+1}``),
        puis renomme le fichier courant en ``{path}.1``. Supprime les
        fichiers de backup au-delà de ``backup_count``.
        """
        try:
            size: int = self.path.stat().st_size
        except OSError:
            return  # fichier pas encore créé

        if size <= self.max_bytes:
            return

        # Renommage en cascade : .2 → .3, .1 → .2
        for n in range(self.backup_count, 0, -1):
            src: Path = Path(f"{self.path}.{n}")
            dst: Path = Path(f"{self.path}.{n + 1}")
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)

        # Renomme le fichier principal en .1
        bak: Path = Path(f"{self.path}.1")
        if bak.exists():
            bak.unlink()
        self.path.rename(bak)

        # Supprime les backups au-delà de backup_count
        for n in range(self.backup_count + 1, self.backup_count + 10):
            aged: Path = Path(f"{self.path}.{n}")
            if aged.exists():
                aged.unlink()


class InterceptHandler(logging.Handler):
    """
    Handler stdlib ``logging.Handler`` redirigeant vers Loguru.

    Intercepte tout ``logging.log()`` émis par la stdlib ou ses
    bibliothèques dérivées (uvicorn, FastAPI, Starlette, httpx,
    langfuse…) et les ré-expedie dans le pipeline Loguru en conservant
    le niveau, le message et les informations d'exception.

    :note:
        Le calcul de ``depth`` compense les appels internes du module
        ``logging`` en remontant la pile jusqu'au premier frame
        **extérieur** à ``logging/__init__.py`` et à ce fichier-ci.
        Sans cette remontée, Loguru attribuerait chaque log intercepté
        à ``logging:callHandlers:1762`` au lieu du module réellement
        émetteur (``uvicorn.error``, ``faiss.loader``…).
    """

    #: Suffixes de chemins considérés comme des frames « internes »,
    #: à traverser lors de la remontée de pile.
    #:
    #: On compare sur le *suffixe* du chemin plutôt que sur
    #: ``logging.__file__`` : ce dernier peut différer du ``co_filename``
    #: réel (``.pyc``, symlink, chemin résolu différemment dans l'image
    #: Docker), ce qui faisait échouer silencieusement la comparaison.
    #:
    #: ``logging_config.py`` figure dans la liste car la remontée démarre
    #: à l'intérieur de :meth:`emit`, défini dans ce module.
    _INTERNAL_SUFFIXES: tuple[str, ...] = (
        "logging/__init__.py",
        "logging\\__init__.py",   # équivalent Windows
        "logging_config.py",      # ce fichier : frame de emit()
    )

    def emit(self, record: logging.LogRecord) -> None:
        """Convertit un enregistrement stdlib en message Loguru.

        :param record: L'enregistrement émis par le logging standard.
        :type record: logging.LogRecord
        :rtype: None

        .. note::
            Uvicorn déclare ses niveaux en minuscules (``"info"``). Loguru
            n'accepte que les noms canoniques en majuscules. On normalise
            donc systématiquement, puis on retombe sur le numéro de niveau
            si le nom reste inconnu.
        """
        # ── 1. Résolution robuste du niveau ──
        try:
            level: str | int = logger.level(record.levelname.upper()).name
        except (ValueError, AttributeError):
            # Niveau inconnu de Loguru : on utilise sa valeur numérique,
            # que Loguru accepte également comme argument de .log().
            level = record.levelno

        # ── 2. Calcul de la profondeur de pile ──
        # On démarre au frame de `emit()` lui-même (``sys._getframe(0)``),
        # puis on remonte tant que l'on reste dans un frame interne
        # (ce module, ou le module `logging` de la stdlib).
        # Le premier frame extérieur est le véritable appelant — uvicorn,
        # faiss, httpx — et c'est lui que Loguru doit créditer.
        #
        # L'ancienne version partait de ``logging.currentframe()``, qui
        # renvoie le frame de `emit()` : celui-ci appartenant à
        # `logging_config.py` et non à `logging/__init__.py`, la condition
        # de boucle était fausse dès le premier tour et `depth` restait
        # figé à 2.
        frame = sys._getframe(0)
        depth: int = 0
        while frame is not None and frame.f_code.co_filename.endswith(
            self._INTERNAL_SUFFIXES
        ):
            frame = frame.f_back
            depth += 1

        # ── 3. Réémission via Loguru ──
        # `depth` indique à Loguru de quel frame extraire
        # name / function / file / line.
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _configure_stdlib_interception() -> None:
    """
    Redirige les loggers stdlib principaux vers Loguru via
    ``InterceptHandler``.

    Configure ``logging.basicConfig`` avec un seul handler
    ``InterceptHandler`` puis itère sur la liste des loggers nommés
    pour vider leurs handlers existants et activer ``propagate``.
    Cela garantit que uvicorn, FastAPI, Starlette, httpx et langfuse
    utilisent le pipeline Loguru sans duplication.
    """
    basic_handler = InterceptHandler()
    logging.basicConfig(
        handlers=[basic_handler],
        level=0,
        force=True,
    )

    # Vide et configure les loggers nommés
    targets: list[str] = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "uvicorn.asgi",
        "fastapi",
        "starlette",
        "httpx",
        "langfuse",
    ]
    for name in targets:
        loggr = logging.getLogger(name)
        loggr.handlers.clear()
        loggr.propagate = True


def setup_logging() -> None:
    """
    Configure le pipeline de logging Loguru pour l'application.

    Appeler **une seule fois**, au plus tôt dans le cycle de vie
    (recommander dans ``main.py`` avant tout import de module
    susceptible de logger).

    :raises ValueError: Si ``LOG_DIR`` n'est pas accessible ou créable.

    .. note::
        Les handlers sont ajoutés avec ``enqueue=True`` pour garantir
        la thread-safety dans un contexte serveur (uvicorn, asyncio).
    """
    # 1️⃣ Crée LOG_DIR sinon ValueError
    if not LOG_DIR.exists():
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(
                f"Impossible de créer le répertoire de log {LOG_DIR} : {e}"
            ) from e

    # 2️⃣ Supprimer tous les handlers par défaut de Loguru
    logger.remove()

    # 3️⃣ Handler stdout (format lisible, colorisé)
    #    Attendez-vous à une sortie comme :
    #    INFO     | src.observability.logging_config:setup_logging:69 | Loguru initialisé
    logger.add(
        sys.stdout,
        format=(
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=LOG_LEVEL,
        colorize=True,
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    # 4️⃣ Handler fichier — selon mode JSON ou texte
    if LOG_JSON:
        # Sink JSON personnalisé : une ligne JSON aplatie par message
        # via JsonFileSink (rotation par taille, thread-safe).
        json_sink = JsonFileSink(
            path=LOG_FILE_PATH,
            max_bytes=LOG_FILE_MAX_BYTES,
            backup_count=LOG_FILE_BACKUP_COUNT,
        )
        logger.add(
            json_sink,
            level=LOG_LEVEL,
            enqueue=True,
        )
    else:
        # Handler fichier texte standard avec rotation/retention Loguru.
        # rotation  : taille fixe ( LOG_FILE_MAX_BYTES )
        # retention : nombre de backups ( LOG_FILE_BACKUP_COUNT )
        logger.add(
            str(LOG_FILE_PATH),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            level=LOG_LEVEL,
            rotation=LOG_FILE_MAX_BYTES,
            retention=LOG_FILE_BACKUP_COUNT,
            enqueue=True,
        )

    # 5️⃣ Interception des loggers stdlib (uvicorn, FastAPI…)
    _configure_stdlib_interception()

    # 6️⃣ Log du démarrage — bind() pour les metadata (kwargs non supportés par loguru)
    logger.bind(
        log_level=LOG_LEVEL,
        log_dir=str(LOG_DIR),
        log_json_enabled=LOG_JSON,
        log_file_path=str(LOG_FILE_PATH),
    ).info("🚀 Loguru initialisé")
