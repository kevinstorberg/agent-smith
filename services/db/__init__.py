from services.db.connection import get_connection
from services.db.pool import init_pool, close_pool
from services.config import DATABASE_URL

__all__ = ["get_connection", "DATABASE_URL", "init_db", "init_pool", "close_pool"]


def init_db() -> None:
    import logging
    import traceback
    from alembic.config import Config
    from alembic import command
    from pathlib import Path

    alembic_ini = Path(__file__).parent.parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception:
        logging.getLogger("init_db").critical("Migration failed:\n%s", traceback.format_exc())
        raise
