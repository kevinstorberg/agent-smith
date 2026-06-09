import argparse
import asyncio
import json

from config.loader import load_default_config
from scripts.base import BaseScript
from src.diagnostics.inspectors import inspect_backends, inspect_config, inspect_migrations, inspect_registries
from src.settings import get_settings


class InspectScript(BaseScript):
    name = "inspect"
    description = "Inspect Agent Smith runtime configuration and registries."

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target", choices=["config", "registries", "migrations", "backends"])
        parser.add_argument("--show-values", action="store_true", help="Show unredacted config values")

    def run(self, args: argparse.Namespace) -> int:
        config = load_default_config()
        settings = get_settings()
        if args.target == "config":
            result = inspect_config(config=config, settings=settings, expose_values=args.show_values)
            print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
            return 0
        if args.target == "registries":
            result = inspect_registries(discover=True)
            print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
            return 0
        if args.target == "migrations":
            result = inspect_migrations()
            print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
            return 0
        if args.target == "backends":
            result = asyncio.run(inspect_backends())
            print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
            return 0
        raise ValueError(f"Unknown inspect target: {args.target}")


def main() -> int:
    return InspectScript().execute()


if __name__ == "__main__":
    raise SystemExit(main())
