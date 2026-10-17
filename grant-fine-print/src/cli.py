"""Single dispatcher for the Grant Fine Print command line.

The real entry points are the per-stage ``python -m src.<name>`` CLIs. This
module only routes to them and does not import heavy dependencies at import
time, so ``gfp --help`` stays fast.
"""

from __future__ import annotations

import argparse
import importlib
import sys

SUBCOMMANDS: dict[str, str] = {
    "pull": "src.pull",
    "study": "src.study",
    "extract": "src.extract",
    "match": "src.match",
    "cards": "src.cards",
    "eval": "src.eval",
    "correct": "src.corrections",
    "train": "src.train",
    "storage": "src.storage",
    "discover": "src.discovery",
}

USAGE = (
    "usage: gfp <command> [args...]\n\n"
    "commands:\n"
    + "".join(f"  {name:<10} {module}\n" for name, module in SUBCOMMANDS.items())
)


def _dispatch(command: str, rest: list[str]) -> int:
    module_name = SUBCOMMANDS[command]
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        print(f"{command}: not implemented yet (module {module_name} is missing).")
        print(f"         When it exists, run: python -m {module_name}")
        return 1
    entry = getattr(module, "main", None)
    if entry is None:
        print(f"{command}: {module_name} has no main(); run `python -m {module_name}`.")
        return 1
    result = entry(rest)
    return 0 if result is None else int(result)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="gfp", description="Grant Fine Print dispatcher."
    )
    parser.add_argument("command", nargs="?", help="one of: " + ", ".join(SUBCOMMANDS))
    args, rest = parser.parse_known_args(argv)

    if not args.command:
        print(USAGE)
        return 0
    if args.command not in SUBCOMMANDS:
        print(f"unknown command: {args.command}\n")
        print(USAGE)
        return 2
    return _dispatch(args.command, rest)


if __name__ == "__main__":
    raise SystemExit(main())
