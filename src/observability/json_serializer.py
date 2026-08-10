"""
src/observability/json_serializer.py
====================================
Post-traitement du JSON Loguru pour monitoring/Langfuse.

Objectif : transformer le JSON brut Loguru en JSON simplifié
et pré-enrichi pour les outils de monitoring (Uptime Kuma, Langfuse, etc.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def flatten_loguru_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Aplatit un enregistrement Loguru en un dictionnaire JSON à un seul niveau.

    Loguru produit nativement des structures imbriquées (``time``, ``level``,
    ``file``, ``process``, ``thread``…). Ces objets sont peu exploitables tels
    quels par un collecteur de logs. Cette fonction les réduit à des clés
    scalaires de premier niveau, directement indexables par Loki, Uptime Kuma
    ou Langfuse.

    La fonction est **bimodale** : elle accepte indifféremment

    * le *record vivant* fourni par un sink Loguru personnalisé, dont les
      sous-champs sont de vrais objets Python (``datetime``, ``timedelta``,
      ``RecordLevel``, ``RecordFile``…) ;
    * le *record sérialisé* issu de ``serialize=True``, de forme
      ``{"text": ..., "record": {...}}``, dont les sous-champs sont des ``dict``.

    Cette double compatibilité permet d'utiliser la même fonction en temps réel
    dans le pipeline de logging et en post-traitement sur un fichier déjà écrit.

    Parameters
    ----------
    record : dict[str, Any]
        Enregistrement Loguru, brut ou sérialisé. Si la clé ``"record"`` est
        présente, son contenu est utilisé ; sinon le dictionnaire est traité
        comme étant lui-même le record.

    Returns
    -------
    dict[str, Any]
        Dictionnaire plat prêt à être sérialisé en JSON. Les clés dont la
        valeur est ``None`` sont retirées afin de ne pas polluer la sortie.
        Les champs injectés via ``logger.bind()`` (présents dans ``extra``)
        sont fusionnés au premier niveau.

    :note: Le champ ``module`` est extrait de ``record["name"]`` et non de
        ``record["module"]``. Loguru place dans ``name`` le chemin complet du
        module (ex. ``src.graph.nodes``), alors que ``module`` ne contient que
        le nom court du fichier. C'est ``name`` qui est pertinent pour tracer
        l'origine d'un log dans une arborescence de packages.

    :note: Le champ ``service`` est codé en dur à ``"intelligence"``. Il permet
        de distinguer les logs de ce conteneur de ceux de ``data-api`` lorsque
        les deux flux sont agrégés dans le même collecteur.

    Example
    -------
    >>> flatten_loguru_record({"record": {
    ...     "time": {"repr": "2026-08-03T11:14:27+00:00"},
    ...     "level": {"name": "INFO", "no": 20},
    ...     "message": "Graphe compilé",
    ...     "name": "src.main",
    ... }})["module"]
    'src.main'
    """
    # Accepte soit le record vivant, soit le JSON sérialisé {"text","record"}
    r = record.get("record", record)

    def _get(obj: Any, key: str, attr: str, default: Any = "") -> Any:
        """
        Lit une valeur qu'``obj`` soit un ``dict`` (JSON) ou un objet (live).

        Parameters
        ----------
        obj : Any
            Sous-structure du record (niveau, fichier, processus, thread…).
        key : str
            Nom de la clé à lire si ``obj`` est un dictionnaire.
        attr : str
            Nom de l'attribut à lire si ``obj`` est un objet Python.
        default : Any, optional
            Valeur retournée si la clé ou l'attribut est absent.

        Returns
        -------
        Any
            La valeur extraite, ou ``default``.
        """
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, attr, default)

    # --- Extraction des sous-structures du record -------------------------
    time_info  = r.get("time")
    level_info = r.get("level")
    file_info  = r.get("file")
    elapsed    = r.get("elapsed")
    process    = r.get("process")
    thread     = r.get("thread")
    extra_info = r.get("extra", {}) or {}

    # --- Horodatage -------------------------------------------------------
    # En mode sérialisé, Loguru fournit une clé "repr" déjà formatée ISO 8601.
    # En mode vivant, il s'agit d'un datetime qu'il faut convertir explicitement.
    if isinstance(time_info, dict):
        timestamp = time_info.get("repr", "")
    elif time_info is not None:
        timestamp = time_info.isoformat()
    else:
        timestamp = ""

    # --- Temps écoulé depuis le démarrage du processus --------------------
    # Sérialisé : {"seconds": N}. Vivant : timedelta → total_seconds().
    if isinstance(elapsed, dict):
        elapsed_seconds = elapsed.get("seconds", 0)
    elif elapsed is not None:
        elapsed_seconds = elapsed.total_seconds()
    else:
        elapsed_seconds = 0

    # --- Construction du dictionnaire plat --------------------------------
    flattened = {
        "timestamp": timestamp,
        "elapsed_seconds": elapsed_seconds,
        "level": _get(level_info, "name", "name"),
        "level_no": _get(level_info, "no", "no", None),
        "message": r.get("message", ""),
        "module": r.get("name", ""),          # ⚠️ "name", pas "module"
        "function": r.get("function", ""),
        "file": _get(file_info, "name", "name"),
        "file_path": str(_get(file_info, "path", "path")),
        "line": r.get("line"),
        "process_id": _get(process, "id", "id", None),
        "process_name": _get(process, "name", "name", None),
        "thread_id": _get(thread, "id", "id", None),
        "thread_name": _get(thread, "name", "name", None),
        "service": "intelligence",
    }

    # Les champs contextuels ajoutés par logger.bind() sont remontés
    # au premier niveau (log_level, log_dir, session_id, username…).
    if extra_info:
        flattened.update(extra_info)

    # Nettoyage final : on ne conserve pas les clés à None.
    return {k: v for k, v in flattened.items() if v is not None}


def process_loguru_json_file(input_path: str, output_path: str) -> None:
    """
    Lit un fichier JSON Loguru brut et écrit un fichier JSON simplifié.

    Parameters
    ----------
    input_path : str
        Chemin du fichier JSON Loguru (ex: logs/intelligence_api.log.json)
    output_path : str
        Chemin du fichier JSON simplifié (ex: logs/intelligence_api.log.processed.json)

    Example
    -------
    >>> process_loguru_json_file(
    ...     "logs/intelligence_api.log.json",
    ...     "logs/intelligence_api.log.processed.json"
    ... )
    ✅ 4 logs traités → logs/intelligence_api.log.processed.json
    """
    count = 0
    with open(input_path, "r", encoding="utf-8") as f_in, open(
        output_path, "w", encoding="utf-8"
    ) as f_out:
        for line in f_in:
            try:
                raw_record = json.loads(line)
                flattened = flatten_loguru_record(raw_record)
                f_out.write(json.dumps(flattened, ensure_ascii=False) + "\n")
                count += 1
            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️  Erreur traitement ligne : {e}")

    print(f"✅ {count} logs traités → {output_path}")


if __name__ == "__main__":
    # Test
    process_loguru_json_file(
        "logs/intelligence_api.log.json",
        "logs/intelligence_api.log.processed.json",
    )