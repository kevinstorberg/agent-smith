import argparse

from scripts.base import BaseScript
from scripts.seed import SeedScript


class FakeScript(BaseScript):
    name = "fake"
    description = "Fake script"

    def __init__(self) -> None:
        self.received_value = ""
        super().__init__()

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--value", required=True)

    def run(self, args: argparse.Namespace) -> int:
        self.received_value = args.value
        return 7


def test_base_script_execute_parses_argv_and_returns_exit_code():
    script = FakeScript()

    exit_code = script.execute(["--value", "configured"])

    assert exit_code == 7
    assert script.received_value == "configured"


def test_seed_script_returns_success_and_supports_reset_flag(capsys):
    exit_code = SeedScript().execute(["--reset"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Resetting database..." in output
    assert "Seeding database..." in output
