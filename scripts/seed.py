import argparse

from scripts.base import BaseScript


class SeedScript(BaseScript):
    name = "seed"
    description = "Seed the database with initial data"

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--reset", action="store_true", help="Drop and recreate tables before seeding")

    def run(self, args: argparse.Namespace) -> int:
        if args.reset:
            print("Resetting database...")
        print("Seeding database...")
        return 0


if __name__ == "__main__":
    script = SeedScript()
    raise SystemExit(script.execute())
