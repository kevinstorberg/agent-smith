import argparse
import sys
from pathlib import Path

from lib.agent_smith_core.generator import ResourceGenerator, parse_resource_spec
from lib.agent_smith_core.paths import get_repo_root
from scripts.base import BaseScript


class GenerateScript(BaseScript):
    name = "generate"
    description = "Generate Agent Smith application resources."

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        subcommands = parser.add_subparsers(dest="command", required=True)
        resource = subcommands.add_parser("resource", help="Generate a CRUD resource")
        resource.add_argument("name", help="singular snake_case resource name")
        resource.add_argument(
            "fields",
            nargs="+",
            help="field specs such as name:string, 'due_date?:date', or 'status:enum[a,b]'",
        )
        resource.add_argument("--frontend", action="store_true", help="also generate a React feature scaffold")
        resource.add_argument("--dry-run", action="store_true", help="print planned files without writing")
        resource.add_argument("--force", action="store_true", help="overwrite existing generated files")
        resource.add_argument("--repo-root", type=Path, default=None, help="override repository root")

    def run(self, args: argparse.Namespace) -> int:
        if args.command != "resource":
            raise ValueError(f"Unknown generate command: {args.command}")

        try:
            spec = parse_resource_spec(args.name, args.fields)
            generator = ResourceGenerator(args.repo_root or get_repo_root(__file__))
            result = generator.generate(spec, dry_run=args.dry_run, force=args.force, frontend=args.frontend)
        except (FileExistsError, ValueError) as e:
            print(f"generate: {e}", file=sys.stderr)
            return 1

        label = "Planned" if result.dry_run else "Generated"
        files = (
            result.planned_files
            if result.dry_run
            else [file for file in result.planned_files if file.path in result.written_files]
        )
        for file in files:
            print(f"{label}: {file.path}")
        return 0


def main() -> int:
    return GenerateScript().execute()


if __name__ == "__main__":
    raise SystemExit(main())
