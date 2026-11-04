from pathlib import Path

from alembic.config import Config
import pytest

from services.db import check_production_schema, get_connection


def _assert_public_indexes_usable(cursor):
    cursor.execute(
        """SELECT namespace.nspname, relation.relname,
                  indexes.indisvalid, indexes.indisready, indexes.indislive
           FROM pg_index AS indexes
           JOIN pg_class AS relation ON relation.oid = indexes.indexrelid
           JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'public'
             AND NOT (indexes.indisvalid AND indexes.indisready AND indexes.indislive)
           ORDER BY namespace.nspname, relation.relname"""
    )
    invalid = cursor.fetchall()
    assert not invalid, (
        f"Unusable public indexes (schema, name, valid, ready, live): {invalid}"
    )


def _assert_public_constraints_validated(cursor):
    cursor.execute(
        """SELECT pg_describe_object('pg_constraint'::regclass, constraints.oid, 0)
           FROM pg_constraint AS constraints
           JOIN pg_namespace AS namespace ON namespace.oid = constraints.connamespace
           WHERE namespace.nspname = 'public' AND NOT constraints.convalidated
           ORDER BY 1"""
    )
    invalid = cursor.fetchall()
    assert not invalid, f"Unvalidated public constraints: {invalid}"


def test_database_health_schema_matches_checkout():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    check_production_schema(config)


def test_database_health_public_indexes_are_valid_ready_and_live():
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        _assert_public_indexes_usable(cursor)


def test_database_health_public_constraints_are_validated():
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        _assert_public_constraints_validated(cursor)


def test_database_health_unvalidated_constraint_reports_its_name_and_rolls_back():
    with pytest.raises(AssertionError, match="ci_database_health_positive") as failure:
        with get_connection() as connection, connection.cursor() as cursor:
            try:
                cursor.execute(
                    "CREATE TABLE public.ci_database_health_probe (value integer)"
                )
                cursor.execute(
                    """ALTER TABLE public.ci_database_health_probe
                       ADD CONSTRAINT ci_database_health_positive CHECK (value > 0) NOT VALID"""
                )
                _assert_public_constraints_validated(cursor)
            finally:
                connection.rollback()

    assert "ci_database_health_probe" in str(failure.value)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SELECT to_regclass('public.ci_database_health_probe')")
        assert cursor.fetchone() == (None,)
        _assert_public_constraints_validated(cursor)
