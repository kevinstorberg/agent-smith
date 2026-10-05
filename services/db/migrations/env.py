import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url
from alembic import context

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None

from services.config import DATABASE_URL as database_url
# SQLAlchemy 2.1 defaults to psycopg 3; the application uses psycopg2.
migration_url = make_url(database_url).set(drivername="postgresql+psycopg2")


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        migration_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
