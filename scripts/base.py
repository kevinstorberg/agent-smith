import argparse
import sys
from abc import ABC, abstractmethod


class BaseScript(ABC):
    name: str = "script"
    description: str = ""

    def __init__(self):
        self.parser = argparse.ArgumentParser(prog=self.name, description=self.description)
        self.configure_args(self.parser)

    def configure_args(self, parser: argparse.ArgumentParser) -> None:
        pass

    @abstractmethod
    def run(self, args: argparse.Namespace) -> int: ...

    def execute(self, argv: list[str] | None = None) -> int:
        args = self.parser.parse_args(argv or sys.argv[1:])
        return self.run(args)
