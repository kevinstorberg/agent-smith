#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from services.db import get_connection  # noqa: E402


def get_tables() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            return [row[0] for row in cur.fetchall()]


def get_columns(table: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """, (table,))
            return [
                {"name": r[0], "type": r[1], "nullable": r[2] == "YES", "default": r[3]}
                for r in cur.fetchall()
            ]


def get_primary_keys(table: str) -> set[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_schema = 'public' AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
            """, (table,))
            return {r[0] for r in cur.fetchall()}


def get_foreign_keys() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    kcu.table_name AS from_table,
                    kcu.column_name AS from_column,
                    ccu.table_name AS to_table,
                    ccu.column_name AS to_column
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage kcu
                  ON rc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                  ON rc.unique_constraint_name = ccu.constraint_name
                WHERE kcu.table_schema = 'public'
            """)
            return [
                {"from_table": r[0], "from_col": r[1], "to_table": r[2], "to_col": r[3]}
                for r in cur.fetchall()
            ]


IMPLICIT_RELATIONSHIPS = [
    {"from_table": "harness_configs", "from_col": "item_id", "to_table": "harness_rules", "to_col": "id"},
    {"from_table": "harness_configs", "from_col": "item_id", "to_table": "harness_skills", "to_col": "id"},
    {"from_table": "harness_configs", "from_col": "item_id", "to_table": "harness_tools", "to_col": "id"},
    {"from_table": "harness_configs", "from_col": "item_id", "to_table": "harness_hooks", "to_col": "id"},
    {"from_table": "harness_configs", "from_col": "item_id", "to_table": "harness_agents", "to_col": "id"},
]


def short_type(t: str) -> str:
    mapping = {
        "integer": "int", "bigint": "bigint", "smallint": "smallint",
        "text": "text", "character varying": "varchar", "boolean": "bool",
        "jsonb": "jsonb", "json": "json", "ARRAY": "array",
        "timestamp with time zone": "timestamptz", "timestamp without time zone": "timestamp",
        "double precision": "float", "numeric": "numeric", "real": "real",
    }
    return mapping.get(t, t)


def main() -> int:
    import graphviz

    parser = argparse.ArgumentParser(prog="generate_erd.py")
    parser.add_argument("-o", "--output", default=str(Path(__file__).parent.parent / "docs" / "erd.png"))
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmt = output.suffix.lstrip(".")

    from services.db import init_db
    init_db()

    tables = get_tables()
    fks = get_foreign_keys()

    dot = graphviz.Digraph("ERD", format=fmt, graph_attr={
        "rankdir": "LR", "bgcolor": "#1a1a2e", "fontcolor": "#e0e0e0",
        "pad": "0.5", "nodesep": "0.8", "ranksep": "1.2",
    }, node_attr={
        "shape": "none", "fontname": "Helvetica", "fontsize": "11",
    }, edge_attr={
        "color": "#5b8def", "fontcolor": "#5b8def", "fontsize": "9", "fontname": "Helvetica",
    })

    skip = {"alembic_version"}

    for table in tables:
        if table in skip:
            continue
        cols = get_columns(table)
        pks = get_primary_keys(table)

        header = f'<TR><TD COLSPAN="2" BGCOLOR="#16213e" ALIGN="CENTER"><FONT COLOR="#e94560"><B>{table}</B></FONT></TD></TR>'
        rows = []
        for c in cols:
            pk = " PK" if c["name"] in pks else ""
            nn = "" if c["nullable"] else " NN"
            rows.append(
                f'<TR><TD ALIGN="LEFT"><FONT COLOR="#e0e0e0">{c["name"]}{pk}</FONT></TD>'
                f'<TD ALIGN="RIGHT"><FONT COLOR="#8888aa">{short_type(c["type"])}{nn}</FONT></TD></TR>'
            )

        label = f'<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" BGCOLOR="#0f3460" COLOR="#5b8def">{header}{"".join(rows)}</TABLE>>'
        dot.node(table, label=label)

    all_relationships = fks + IMPLICIT_RELATIONSHIPS
    for fk in all_relationships:
        if fk["from_table"] in skip or fk["to_table"] in skip:
            continue
        style = {"style": "dashed", "color": "#e94560"} if fk in IMPLICIT_RELATIONSHIPS else {}
        dot.edge(fk["from_table"], fk["to_table"], label=f'{fk["from_col"]} → {fk["to_col"]}', **style)

    out_path = str(output).removesuffix(f".{fmt}")
    dot.render(out_path, cleanup=True)
    print(f"ERD generated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
