from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from .. import output
from ..context import Context
from ...domain.errors import ConflictError, ValidationError
from ...services.import_export_service import DATASETS, FORMATS, IMPORT_MODES
from ...storage import json_repository
from ...storage.seed_data import (
    SEED_START,
    baseline_events,
    entity_ids,
    mock_events,
    renumber_events,
)


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

    export = subparsers.add_parser(
        "export", help="Write the store out as JSON, or one dataset as CSV"
    )
    export.add_argument("--out", required=True, help="File to write")
    export.add_argument(
        "--format",
        dest="fmt",
        choices=FORMATS,
        help="Output format (default: taken from the file extension)",
    )
    export.add_argument(
        "--dataset",
        choices=DATASETS,
        help="Which records to write; required for CSV",
    )
    export.set_defaults(handler=cmd_export)

    importer = subparsers.add_parser(
        "import", help="Load JSON or CSV data into the store"
    )
    importer.add_argument("path", help="File to read")
    importer.add_argument(
        "--format",
        dest="fmt",
        choices=FORMATS,
        help="Input format (default: taken from the file extension)",
    )
    importer.add_argument(
        "--dataset",
        choices=DATASETS,
        help="Which records the file holds; required for CSV",
    )
    importer.add_argument(
        "--mode",
        choices=IMPORT_MODES,
        default="merge",
        help="merge keeps existing data and adds to it; replace discards it first",
    )
    importer.set_defaults(handler=cmd_import)


def _resolve_format(explicit: str | None, path: str | Path) -> str:
    if explicit:
        return explicit
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in FORMATS:
        return suffix
    raise ValidationError(
        f"cannot tell the format of {str(path)!r} from its name; "
        f"pass --format {' or --format '.join(FORMATS)}"
    )


def _resolve_dataset(explicit: str | None, path: str | Path, fmt: str) -> str | None:
    if explicit or fmt != "csv":
        return explicit
    stem = Path(path).stem.lower()
    return stem if stem in DATASETS else None


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
            emit_taxonomy=False,
            reserved_ids=entity_ids(events),
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


def cmd_export(args: argparse.Namespace, ctx: Context) -> int:
    fmt = _resolve_format(args.fmt, args.out)
    dataset = _resolve_dataset(args.dataset, args.out, fmt)
    summary = ctx.transfer.write_export(args.out, fmt=fmt, dataset=dataset)

    if ctx.as_json:
        output.print_json(summary)
        return 0

    if fmt == "json":
        output.info(
            f"Exported {summary['events']} event(s) to {summary['path']}."
        )
    else:
        output.info(
            f"Exported {summary['rows']} {summary['dataset']} row(s) "
            f"to {summary['path']}."
        )
    return 0


def cmd_import(args: argparse.Namespace, ctx: Context) -> int:
    fmt = _resolve_format(args.fmt, args.path)
    dataset = _resolve_dataset(args.dataset, args.path, fmt)
    summary = ctx.transfer.import_file(
        args.path, fmt=fmt, dataset=dataset, mode=args.mode
    )

    if ctx.as_json:
        output.print_json(summary)
        return 0

    if summary["mode"] == "replace":
        output.info(
            f"Replaced the store with {summary['imported']} event(s) "
            f"from {args.path}."
        )
    else:
        skipped = (
            f", skipped {summary['skipped']} already-present event(s)"
            if summary["skipped"]
            else ""
        )
        output.info(f"Imported {summary['imported']} event(s) from {args.path}{skipped}.")
    output.info(f"The store now holds {summary['total_events']} event(s).")
    return 0
