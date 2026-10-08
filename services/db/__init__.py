from services.db.connection import get_connection
from services.db.pool import init_pool, close_pool
from services.config import APP_ENV, DATABASE_URL, DB_CONNECT_TIMEOUT

__all__ = ["get_connection", "DATABASE_URL", "init_db", "init_pool", "close_pool"]


def init_db() -> None:
    import logging
    import traceback
    from alembic.config import Config
    from alembic import command
    from pathlib import Path

    alembic_ini = Path(__file__).parent.parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    if APP_ENV == "production":
        check_production_schema(alembic_cfg)
        return
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception:
        logging.getLogger("init_db").critical("Migration failed:\n%s", traceback.format_exc())
        raise


def check_production_schema(alembic_cfg) -> None:
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, pool
    from scripts.shared.database_safety import sqlalchemy_url

    expected = set(ScriptDirectory.from_config(alembic_cfg).get_heads())
    engine = create_engine(sqlalchemy_url(DATABASE_URL), poolclass=pool.NullPool,
                           connect_args={"connect_timeout": int(DB_CONNECT_TIMEOUT)})
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            actual = set(MigrationContext.configure(connection).get_current_heads())
        if actual != expected:
            raise RuntimeError(f"Production schema {sorted(actual)} differs from this checkout {sorted(expected)}. Review pending migrations and use ./db.sh production --confirm-database <database-name> to upgrade; startup never changes production schema.")
    finally:
        engine.dispose()
