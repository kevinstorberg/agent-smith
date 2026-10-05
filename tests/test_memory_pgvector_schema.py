from __future__ import annotations

from services.db import get_connection


def test_pgvector_extension_and_memory_schema_are_installed():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            extension = cur.fetchone()
            cur.execute(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute AS a
                WHERE a.attrelid = 'memories'::regclass
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                """
            )
            embedding_type = cur.fetchone()

    assert extension is not None
    assert embedding_type == ("vector(384)",)


def test_pgvector_executes_exact_cosine_query_transactionally():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 - ('[1,0,0]'::vector <=> '[1,0,0]'::vector)"
            )
            similarity = cur.fetchone()[0]

    assert similarity == 1.0
