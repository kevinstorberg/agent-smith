import argparse
import sys

from scripts.generate import GenerateScript


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-smith")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("generate", help="Generate Agent Smith application artifacts", add_help=False)
    args, remainder = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    if args.command == "generate":
        return GenerateScript().execute(remainder)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
