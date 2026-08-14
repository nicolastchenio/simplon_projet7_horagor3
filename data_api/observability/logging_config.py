"""
data_api/observability/logging_config.py
=========================================
Configuration centralisée de Loguru pour la couche Données (data-api).

Copie auto-suffisante de ``src/observability/logging_config.py`` : ce
module n'importe rien depuis ``src/observability`` (l'image Docker de
data_api ne copie que ``data_api/``, cf. ``docker/data_api.Dockerfile``).

Différences avec la version Intelligence :

- Constantes lues depuis ``data_api.config`` (et non ``src.config``).
- Fichier de sortie ``data_api.log`` (au lieu de ``intelligence_api.log``),
  dans le même ``LOG_DIR`` partagé.
- Champ ``service`` fixé à ``"data-api"`` dans le JSON aplati.
- Aplatissement du record (``flatten_loguru_record``) inliné ici plutôt
  que dans un module ``json_serializer.py`` séparé : cette fonction n'est
  utilisée par aucun autre module de data_api.
- Liste de loggers stdlib interceptés réduite à ceux réellement présents
  côté data_api (pas de ``httpx``/``langfuse``, absents de ce service).
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from data_api.config import (
    LOG_DIR,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_JSON,
    LOG_LEVEL,
)

#: Chemin canonique du fichier de log (dérivé de LOG_DIR).
LOG_FILE_PATH: Path = LOG_DIR / "data_api.log"


def flatten_loguru_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Aplatit un enregistrement Loguru en un dictionnaire JSON à un seul niveau.

    Équivalent de ``src.observability.json_serializer.flatten_loguru_record``,
    dupliqué ici pour rester autonome (voir docstring du module) — seule
    différence : ``service`` vaut ``"data-api"``.

    :param record: Enregistrement Loguru vivant (``message.record``).
    :returns: Dictionnaire plat prêt à être sérialisé en JSON.
    """
    r = record.get("record", record)

    def _get(obj: Any, key: str, attr: str, default: Any = "") -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, attr, default)

    time_info = r.get("time")
    level_info = r.get("level")
    file_info = r.get("file")
    elapsed = r.get("elapsed")
    process = r.get("process")
    thread = r.get("thread")
    extra_info = r.get("extra", {}) or {}

    if isinstance(time_info, dict):
        timestamp = time_info.get("repr", "")
    elif time_info is not None:
        timestamp = time_info.isoformat()
    else:
        timestamp = ""

    if isinstance(elapsed, dict):
        elapsed_seconds = elapsed.get("seconds", 0)
    elif elapsed is not None:
        elapsed_seconds = elapsed.total_seconds()
    else:
        elapsed_seconds = 0

    flattened = {
        "timestamp": timestamp,
        "elapsed_seconds": elapsed_seconds,
        "level": _get(level_info, "name", "name"),
        "level_no": _get(level_info, "no", "no", None),
        "message": r.get("message", ""),
        "module": r.get("name", ""),
        "function": r.get("function", ""),
        "file": _get(file_info, "name", "name"),
        "file_path": str(_get(file_info, "path", "path")),
        "line": r.get("line"),
        "process_id": _get(process, "id", "id", None),
        "process_name": _get(process, "name", "name", None),
        "thread_id": _get(thread, "id", "id", None),
        "thread_name": _get(thread, "name", "name", None),
        "service": "data-api",
    }

    if extra_info:
        flattened.update(extra_info)

    return {k: v for k, v in flattened.items() if v is not None}


class JsonFileSink:
    """
    Sink Loguru — écrit une ligne JSON aplatie par message, avec rotation
    par taille. Thread-safe grâce à un ``threading.Lock``.
    """

    def __init__(self, path: Path, max_bytes: int, backup_count: int) -> None:
        self.path: Path = path
        self.max_bytes: int = max_bytes
        self.backup_count: int = backup_count
        self._lock: threading.Lock = threading.Lock()

    def __call__(self, message: Any) -> None:
        record: dict[str, Any] = message.record  # type: ignore[attr-defined]
        flattened: dict[str, Any] = flatten_loguru_record(record)
        line: str = json.dumps(flattened, ensure_ascii=False, default=str) + "\n"

        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            self._rotate()

    def get_path(self) -> Path:
        return self.path

    def _rotate(self) -> None:
        try:
            size: int = self.path.stat().st_size
        except OSError:
            return  # fichier pas encore créé

        if size <= self.max_bytes:
            return

        for n in range(self.backup_count, 0, -1):
            src: Path = Path(f"{self.path}.{n}")
            dst: Path = Path(f"{self.path}.{n + 1}")
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)

        bak: Path = Path(f"{self.path}.1")
        if bak.exists():
            bak.unlink()
        self.path.rename(bak)

        for n in range(self.backup_count + 1, self.backup_count + 10):
            aged: Path = Path(f"{self.path}.{n}")
            if aged.exists():
                aged.unlink()


class InterceptHandler(logging.Handler):
    """
    Handler stdlib redirigeant vers Loguru — intercepte les logs émis
    par uvicorn/FastAPI/Starlette et les ré-expédie dans le pipeline
    Loguru en conservant niveau, message et frame d'origine.
    """

    _INTERNAL_SUFFIXES: tuple[str, ...] = (
        "logging/__init__.py",
        "logging\\__init__.py",  # équivalent Windows
        "logging_config.py",     # ce fichier : frame de emit()
    )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname.upper()).name
        except (ValueError, AttributeError):
            level = record.levelno

        frame = sys._getframe(0)
        depth: int = 0
        while frame is not None and frame.f_code.co_filename.endswith(
            self._INTERNAL_SUFFIXES
        ):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _configure_stdlib_interception() -> None:
    """
    Redirige les loggers stdlib de data_api vers Loguru via
    ``InterceptHandler`` (uvicorn, FastAPI, Starlette — pas de httpx
    ni de langfuse, absents de ce service).
    """
    basic_handler = InterceptHandler()
    logging.basicConfig(
        handlers=[basic_handler],
        level=0,
        force=True,
    )

    targets: list[str] = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "uvicorn.asgi",
        "fastapi",
        "starlette",
    ]
    for name in targets:
        loggr = logging.getLogger(name)
        loggr.handlers.clear()
        loggr.propagate = True


def setup_logging() -> None:
    """
    Configure le pipeline de logging Loguru pour data_api.

    Appeler **une seule fois**, au tout début de ``data_api/main.py``,
    avant l'import des routers (qui déclenchent l'import de
    ``data_api/database.py``).

    :raises ValueError: Si ``LOG_DIR`` n'est pas accessible ou créable.
    """
    if not LOG_DIR.exists():
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(
                f"Impossible de créer le répertoire de log {LOG_DIR} : {e}"
            ) from e

    logger.remove()

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

    if LOG_JSON:
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
        logger.add(
            str(LOG_FILE_PATH),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            level=LOG_LEVEL,
            rotation=LOG_FILE_MAX_BYTES,
            retention=LOG_FILE_BACKUP_COUNT,
            enqueue=True,
        )

    _configure_stdlib_interception()

    logger.bind(
        log_level=LOG_LEVEL,
        log_dir=str(LOG_DIR),
        log_json_enabled=LOG_JSON,
        log_file_path=str(LOG_FILE_PATH),
    ).info("🚀 Loguru initialisé (data-api)")
