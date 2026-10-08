from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .. import __version__
from ..domain.errors import LenderError
from ..storage.store import Store
from . import output
from .commands import register_all
from .context import Context
from .menu import run as run_menu

EPILOG = """\
examples:
  lender menu
  lender seed
  lender seed --mock-fellows 200 --mock-piscine 60 --mock-equipment 40 --mock-loans 80
  lender add-category "Lab Gear"
  lender add-subcategory "Lab Gear" "Oscilloscopes"
  lender add-resource --name "Dell Latitude" --category Electronics --subcategory laptop --total 12
  lender mark-condition R001 faulty 1 --reason "screen flicker"
  lender add-cohort cluster-5-mar
  lender add-fellow "Ada Lovelace" --cohort cluster-5-mar
  lender add-piscine "Alan Turing" --trial january-2026-trial
  lender checkout R001 F001 2 --days 7
  lender return T000001 --condition damaged
  lender history --borrower F001 --open
  lender overdue
  lender report-borrower-history F001
  lender find-by-category Electronics
  lender report-store-status
  lender report-low-stock
  lender export --out backup.json
  lender export --out resources.csv
  lender import backup.json --mode replace
  lender import loans.csv
  lender report-low-stock --out low-stock.csv
  lender report-store-status --out status.json
"""


def _global_argv(args: argparse.Namespace) -> list[str]:
    argv: list[str] = []
    if args.data_dir:
        argv += ["--data-dir", args.data_dir]
    argv += ["--actor", args.actor]
    if args.as_json:
        argv.append("--json")
    return argv


def cmd_menu(args: argparse.Namespace, ctx: Context) -> int:
    base = _global_argv(args)
    return run_menu(
        lambda argv: main([*base, *argv]),
        intro=f"data directory: {ctx.store.paths.root}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lender",
        description="Learn2Earn Lender — equipment inventory and lending manager.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        help="Directory holding the transaction log and projections (default: ./data)",
    )
    parser.add_argument(
        "--actor",
        default="admin",
        help="Name recorded on every event this run writes (default: admin)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of tables",
    )
    parser.add_argument(
        "--version", action="version", version=f"learn2earn-lender {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    menu = subparsers.add_parser(
        "menu", help="Pick actions from an interactive menu (loops until you exit)"
    )
    menu.set_defaults(handler=cmd_menu)
    register_all(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    output.configure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        store = Store.open(args.data_dir)
    except LenderError as exc:
        output.fail(str(exc))
        return exc.exit_code

    ctx = Context.build(store, actor=args.actor, as_json=args.as_json)

    try:
        return args.handler(args, ctx)
    except LenderError as exc:
        output.fail(str(exc))
        return exc.exit_code
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        output.fail("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
