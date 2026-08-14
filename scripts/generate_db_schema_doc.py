"""
scripts/generate_db_schema_doc.py
==================================
Génère automatiquement la page Sphinx du schéma relationnel
(``docs/source/schema_bdd.rst``) à partir d'une introspection directe
du catalogue PostgreSQL de Supabase.

Ce script est un outil ponctuel (comme ``build_faiss_index.py`` ou
``faiss_to_pgvector.py``) : il se connecte directement à Supabase via
``data_api.database.get_db_connection()`` (même connexion que le
data-api), en dehors de toute requête HTTP applicative. Il n'écrit
jamais dans la base, il ne fait que lire le catalogue système.

Relancer ce script si le schéma évolue :
    uv run python scripts/generate_db_schema_doc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

from data_api.database import get_db_connection

DOCS_SOURCE_DIR = PROJECT_ROOT / "docs" / "source"
OUTPUT_RST = DOCS_SOURCE_DIR / "schema_bdd.rst"

# ═══════════════════════════════════════════════════════════════
# Requêtes d'introspection (catalogue système PostgreSQL)
# ═══════════════════════════════════════════════════════════════

TABLES_QUERY = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name;
"""

# On passe par pg_attribute/format_type (et non information_schema.columns)
# car c'est la seule façon d'obtenir le type complet avec son modificateur,
# ex. "vector(768)" pour la colonne embedding — information_schema aurait
# juste renvoyé "USER-DEFINED".
COLUMNS_QUERY = """
    SELECT
        c.relname AS table_name,
        a.attname AS column_name,
        format_type(a.atttypid, a.atttypmod) AS data_type,
        NOT a.attnotnull AS is_nullable,
        a.attnum AS ordinal_position
    FROM pg_attribute a
    JOIN pg_class c ON a.attrelid = c.oid
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum;
"""

PRIMARY_KEYS_QUERY = """
    SELECT tc.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
       AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public';
"""

FOREIGN_KEYS_QUERY = """
    SELECT
        tc.table_name AS table_name,
        kcu.column_name AS column_name,
        ccu.table_name AS ref_table,
        ccu.column_name AS ref_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
       AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
        ON tc.constraint_name = ccu.constraint_name
       AND tc.table_schema = ccu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public';
"""


# ═══════════════════════════════════════════════════════════════
# Extraction
# ═══════════════════════════════════════════════════════════════

def _fetch_tables(cur) -> list[str]:
    """
    Liste les tables de base du schéma ``public``.

    :param cur: Curseur psycopg2 ouvert.
    :returns: Noms de tables, triés alphabétiquement.
    """
    cur.execute(TABLES_QUERY)
    return [row[0] for row in cur.fetchall()]


def _fetch_columns(cur) -> dict[str, list[dict]]:
    """
    Récupère les colonnes de toutes les tables, groupées par table.

    :param cur: Curseur psycopg2 ouvert.
    :returns: ``{table_name: [{"name", "type", "nullable"}, ...]}``,
        colonnes ordonnées selon leur position réelle dans la table.
    """
    cur.execute(COLUMNS_QUERY)
    columns_by_table: dict[str, list[dict]] = {}
    for table_name, column_name, data_type, is_nullable, _position in cur.fetchall():
        columns_by_table.setdefault(table_name, []).append(
            {"name": column_name, "type": data_type, "nullable": is_nullable}
        )
    return columns_by_table


def _fetch_primary_keys(cur) -> dict[str, set[str]]:
    """
    Récupère les colonnes de clé primaire, groupées par table.

    :param cur: Curseur psycopg2 ouvert.
    :returns: ``{table_name: {colonne_pk, ...}}``.
    """
    cur.execute(PRIMARY_KEYS_QUERY)
    pks: dict[str, set[str]] = {}
    for table_name, column_name in cur.fetchall():
        pks.setdefault(table_name, set()).add(column_name)
    return pks


def _fetch_foreign_keys(cur) -> list[dict]:
    """
    Récupère toutes les clés étrangères du schéma ``public``.

    :param cur: Curseur psycopg2 ouvert.
    :returns: Liste de ``{"table", "column", "ref_table", "ref_column"}``.
    """
    cur.execute(FOREIGN_KEYS_QUERY)
    return [
        {"table": t, "column": c, "ref_table": rt, "ref_column": rc}
        for t, c, rt, rc in cur.fetchall()
    ]


# ═══════════════════════════════════════════════════════════════
# Génération reST / Mermaid
# ═══════════════════════════════════════════════════════════════

def _sanitize_mermaid_type(pg_type: str) -> str:
    """
    Convertit un type PostgreSQL en identifiant compatible Mermaid.

    Mermaid n'accepte pas les parenthèses ni les espaces dans un type
    d'attribut ``erDiagram`` (ex. ``vector(768)`` casserait le rendu) :
    on les remplace par des underscores.

    :param pg_type: Type PostgreSQL brut (ex. ``"vector(768)"``).
    :returns: Type assaini (ex. ``"vector_768"``).
    """
    return "".join(ch if ch.isalnum() else "_" for ch in pg_type).strip("_")


def _build_mermaid_er_diagram(
    tables: list[str],
    columns: dict[str, list[dict]],
    pks: dict[str, set[str]],
    fks: list[dict],
) -> str:
    """
    Construit le bloc ``erDiagram`` Mermaid (entités + relations).

    :param tables: Noms de toutes les tables.
    :param columns: Colonnes par table (cf. :func:`_fetch_columns`).
    :param pks: Clés primaires par table (cf. :func:`_fetch_primary_keys`).
    :param fks: Clés étrangères (cf. :func:`_fetch_foreign_keys`).
    :returns: Code Mermaid ``erDiagram`` complet, indenté pour la
        directive ``.. mermaid::`` de Sphinx.
    """
    fk_columns_by_table = {
        (fk["table"], fk["column"]) for fk in fks
    }
    lines = ["erDiagram"]

    for table in tables:
        lines.append(f"    {table} {{")
        for col in columns.get(table, []):
            mermaid_type = _sanitize_mermaid_type(col["type"])
            key_suffix = ""
            if col["name"] in pks.get(table, set()):
                key_suffix = " PK"
            elif (table, col["name"]) in fk_columns_by_table:
                key_suffix = " FK"
            lines.append(f"        {mermaid_type} {col['name']}{key_suffix}")
        lines.append("    }")

    # Une relation "1 table parente -> N table enfant" par clé étrangère :
    # la table référencée (ref_table) est le côté "1", la table porteuse
    # de la FK (table) est le côté "N".
    for fk in fks:
        lines.append(
            f'    {fk["ref_table"]} ||--o{{ {fk["table"]} : "{fk["column"]}"'
        )

    return "\n".join(lines)


def _build_rst_table_section(
    table: str,
    columns: list[dict],
    pks: set[str],
    fks: list[dict],
) -> str:
    """
    Construit la section reST (``list-table``) détaillant une table.

    :param table: Nom de la table.
    :param columns: Colonnes de cette table.
    :param pks: Colonnes de clé primaire de cette table.
    :param fks: Toutes les clés étrangères du schéma (filtrées ici sur
        ``table``).
    :returns: Bloc reST prêt à insérer dans le document.
    """
    fk_by_column = {
        fk["column"]: f'{fk["ref_table"]}.{fk["ref_column"]}'
        for fk in fks
        if fk["table"] == table
    }

    title = f"Table ``{table}``"
    underline = "-" * len(title)
    rows = [
        "\n".join(
            [
                "   * - " + col["name"],
                "     - " + col["type"],
                "     - " + ("Oui" if col["nullable"] else "Non"),
                "     - "
                + (
                    "PK"
                    if col["name"] in pks
                    else (f"FK → {fk_by_column[col['name']]}" if col["name"] in fk_by_column else "")
                ),
            ]
        )
        for col in columns
    ]
    return (
        f"{title}\n{underline}\n\n"
        ".. list-table::\n"
        "   :header-rows: 1\n\n"
        "   * - Colonne\n"
        "     - Type\n"
        "     - Nullable\n"
        "     - Clé\n"
        + "\n".join(rows)
        + "\n"
    )


def _build_rst_document(
    tables: list[str],
    columns: dict[str, list[dict]],
    pks: dict[str, set[str]],
    fks: list[dict],
) -> str:
    """
    Assemble le document reST complet (diagramme + tables détaillées).

    :param tables: Noms de toutes les tables.
    :param columns: Colonnes par table.
    :param pks: Clés primaires par table.
    :param fks: Clés étrangères du schéma.
    :returns: Contenu complet de ``schema_bdd.rst``.
    """
    mermaid_block = _build_mermaid_er_diagram(tables, columns, pks, fks)
    indented_mermaid = "\n".join(
        f"   {line}" if line else "" for line in mermaid_block.splitlines()
    )

    sections = [
        _build_rst_table_section(table, columns.get(table, []), pks.get(table, set()), fks)
        for table in tables
    ]

    return (
        "Schéma relationnel de la base de données\n"
        "==========================================\n\n"
        "Ce document est **généré automatiquement** par "
        "``scripts/generate_db_schema_doc.py`` à partir d'une introspection "
        "du catalogue PostgreSQL de Supabase (schéma ``public``). Relancez "
        "ce script si le schéma évolue :\n\n"
        "::\n\n"
        "    uv run python scripts/generate_db_schema_doc.py\n\n"
        "Cartographie des relations\n"
        "----------------------------\n\n"
        ".. mermaid::\n\n"
        f"{indented_mermaid}\n\n"
        + "\n".join(sections)
    )


def main() -> None:
    """
    Point d'entrée : introspecte Supabase et écrit ``schema_bdd.rst``.
    """
    logger.info("[SchemaDoc] Connexion à Supabase pour introspection du schéma...")
    with get_db_connection() as conn:
        cur = conn.cursor()
        tables = _fetch_tables(cur)
        columns = _fetch_columns(cur)
        pks = _fetch_primary_keys(cur)
        fks = _fetch_foreign_keys(cur)

    logger.info(f"[SchemaDoc] {len(tables)} table(s) détectée(s) : {tables}")

    content = _build_rst_document(tables, columns, pks, fks)
    OUTPUT_RST.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_RST.write_text(content, encoding="utf-8")

    logger.success(f"[SchemaDoc] Écrit : {OUTPUT_RST}")


if __name__ == "__main__":
    main()
