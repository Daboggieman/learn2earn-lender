from __future__ import annotations

import argparse
from datetime import timedelta

from .. import output
from ..context import Context
from ...domain.errors import ConflictError
from ...storage import json_repository
from ...storage.seed_data import SEED_START, baseline_events, mock_events, renumber_events


def register(subparsers: argparse._SubParsersAction) -> None:
    seed = subparsers.add_parser(
        "seed", help="Initialise the data directory with startup data"
    )
    seed.add_argument("--mock-fellows", type=int, default=0, help="Mock Fellows to generate")
    seed.add_argument(
        "--mock-piscine", type=int, default=0, help="Mock Piscine candidates to generate"
    )
    seed.add_argument(
        "--mock-equipment", type=int, default=0, help="Mock equipment resources to generate"
    )
    seed.add_argument("--mock-cohorts", type=int, default=4, help="Mock cohorts to generate")
    seed.add_argument("--mock-trials", type=int, default=6, help="Mock trial periods")
    seed.add_argument(
        "--mock-loans", type=int, default=0, help="Mock checkout/return transactions"
    )
    seed.add_argument(
        "--random-seed", type=int, default=20260101, help="RNG seed for mock data"
    )
    seed.add_argument(
        "--force",
        action="store_true",
        help="Discard existing data and start over (destructive)",
    )
    seed.set_defaults(handler=cmd_seed)


def _wipe(ctx: Context) -> int:
    removed = 0
    for directory in (ctx.store.paths.transactions_dir, ctx.store.paths.current_dir):
        for path in json_repository.list_json_files(directory):
            json_repository.delete_file(path)
            removed += 1
    return removed


def cmd_seed(args: argparse.Namespace, ctx: Context) -> int:
    if not ctx.store.is_empty() and not args.force:
        raise ConflictError(
            "this data directory already contains data. "
            "Re-run with --force to discard it and start over, or point "
            "--data-dir at a fresh directory."
        )

    removed = _wipe(ctx) if args.force else 0

    events = baseline_events()
    mock_counts = {
        "fellows": args.mock_fellows,
        "piscine": args.mock_piscine,
        "equipment": args.mock_equipment,
        "loans": args.mock_loans,
    }
    if any(mock_counts.values()) or args.mock_cohorts or args.mock_trials:
        if any(mock_counts.values()):
            events = events + mock_events(
                fellows=args.mock_fellows,
                piscine=args.mock_piscine,
                equipment=args.mock_equipment,
                cohorts=args.mock_cohorts,
                trials=args.mock_trials,
                loans=args.mock_loans,
                seed=args.random_seed,
                start=SEED_START + timedelta(days=1),
            )

    events = renumber_events(events)
    ctx.store.extend(events)

    state = ctx.store.state
    summary = {
        "events": len(events),
        "removed_files": removed,
        "resources": len(state.resources),
        "taxonomy_nodes": len(state.taxonomy),
        "groups": len(state.groups),
        "people": len(state.people),
        "loans": len(state.loans),
        "data_dir": str(ctx.store.paths.root),
    }
    if ctx.as_json:
        output.print_json(summary)
        return 0

    if removed:
        output.info(f"Discarded {removed} existing data file(s).")
    output.info(
        f"Seeded {summary['events']} event(s) into {summary['data_dir']}: "
        f"{summary['taxonomy_nodes']} taxonomy nodes, {summary['groups']} groups, "
        f"{summary['resources']} resources, {summary['people']} borrowers, "
        f"{summary['loans']} loans."
    )
    return 0
