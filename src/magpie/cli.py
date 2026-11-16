"""`magpie` entry point. Each track owns its own subcommands in its own
package and exposes `register(subparsers)`; this file only wires them up."""

import argparse
import sys

from .pipeline import cli as pipeline_cli
from .sources import cli as sources_cli
from .web import cli as web_cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="magpie", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    for track in (sources_cli, pipeline_cli, web_cli):
        track.register(sub)
    if argv is None:
        argv = sys.argv[1:]
    # The camera roll is the main way in: plain `magpie` opens it.
    args = parser.parse_args(argv or ["web"])
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
