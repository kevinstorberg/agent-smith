from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config

from scripts.shared.database_safety import database_identity
from services.config import APP_ENV, DATABASE_URL


def main() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    if APP_ENV == "production":
        name = database_identity(DATABASE_URL)[2]
        if os.environ.get("AGENT_SMITH_CONFIRM_DATABASE") != name:
            raise SystemExit("Production upgrade requires --confirm-database matching the database name. Review/back up the data before explicitly applying migrations.")
        config.attributes["approved_production_upgrade"] = name
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
