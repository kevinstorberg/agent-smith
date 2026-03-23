from services.db.connection import get_connection, DATABASE_URL

__all__ = ["get_connection", "DATABASE_URL", "init_db"]


def init_db() -> None:
    from alembic.config import Config
    from alembic import command
    from pathlib import Path

    alembic_ini = Path(__file__).parent.parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    command.upgrade(alembic_cfg, "head")
