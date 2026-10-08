import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool
from alembic import context

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None

from services.config import APP_ENV, DATABASE_URL as database_url
from scripts.shared.database_safety import database_identity, sqlalchemy_url

migration_url = sqlalchemy_url(database_url)
if APP_ENV == "production" and config.attributes.get("approved_production_upgrade") != database_identity(database_url)[2]:
    raise RuntimeError("Production migrations require ./db.sh production --confirm-database <database-name>; direct Alembic commands are blocked")


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
