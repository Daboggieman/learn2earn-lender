from __future__ import annotations

import argparse

from .. import output
from ..context import Context

STATUS_COLUMNS = [
    "ID", "NAME", "CATEGORY", "AVAILABLE", "OUT", "FAULTY", "DAMAGED",
    "MISSING", "RETIRED", "NEEDED", "FLAG",
]


def add_export_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", help="Also write the report to this file")
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=("json", "csv"),
        help="File format for --out (default: taken from the file extension)",
    )


def export_report(args, ctx: Context, *, report, payload, headers=None, rows=None):
    if not args.out:
        return None
    return ctx.transfer.write_report(
        args.out,
        report=report,
        payload=output.to_jsonable(payload),
        headers=headers,
        rows=rows,
        fmt=args.fmt,
    )


def announce_export(summary) -> None:
    if summary is None:
        return
    if summary["format"] == "csv":
        output.info(
            f"Wrote {summary['rows']} {summary['report']} row(s) to {summary['path']}."
        )
    else:
        output.info(f"Wrote the {summary['report']} report to {summary['path']}.")


def register(subparsers: argparse._SubParsersAction) -> None:
    status = subparsers.add_parser(
        "report-store-status", help="Show what is available, out, faulty and needed"
    )
    status.add_argument("--all", action="store_true", help="Include removed resources")
    add_export_options(status)
    status.set_defaults(handler=cmd_store_status, writes=False)

    inventory = subparsers.add_parser(
        "report-inventory", help="Summarise inventory levels by category"
    )
    inventory.add_argument("--category", help="Limit to a category")
    inventory.add_argument("--all", action="store_true", help="Include removed resources")
    add_export_options(inventory)
    inventory.set_defaults(handler=cmd_inventory_report, writes=False)

    low = subparsers.add_parser(
        "report-low-stock", help="Resources with fewer than 3 available units"
    )
    add_export_options(low)
    low.set_defaults(handler=cmd_low_stock, writes=False)

    most = subparsers.add_parser(
        "report-most-borrowed", help="Resource(s) with the most units currently borrowed"
    )
    add_export_options(most)
    most.set_defaults(handler=cmd_most_borrowed, writes=False)


def _status_row(row, ctx: Context) -> list[object]:
    return [
        row.resource_id,
        row.name,
        row.category,
        row.available,
        row.issued,
        row.faulty,
        row.damaged,
        row.missing,
        row.retired,
        row.needed,
        "LOW" if row.low_stock else "",
    ]


def _print_totals(totals: dict[str, int]) -> None:
    output.info("")
    output.info(
        f"Totals: {totals['resources']} resource(s), {totals['total']} unit(s) — "
        f"{totals['available']} available, {totals['issued']} out, "
        f"{totals['unavailable']} unavailable, {totals['needed']} needed"
    )


def cmd_store_status(args: argparse.Namespace, ctx: Context) -> int:
    status = ctx.reporting.store_status(include_removed=args.all)
    headers = STATUS_COLUMNS
    rows = [_status_row(row, ctx) for row in status.rows]
    summary = export_report(
        args, ctx, report="store-status", payload=status, headers=headers, rows=rows
    )

    if ctx.as_json:
        output.print_json(summary if summary else status)
        return 0

    output.emit(
        False,
        headers=headers,
        rows=rows,
        empty="The store is empty. Try: lender seed",
    )
    if status.rows:
        _print_totals(status.totals)
    if status.low_stock:
        output.info("")
        output.info(f"Low stock (fewer than 3 available): {len(status.low_stock)}")
        for row in status.low_stock:
            output.info(f"  {row.resource_id}  {row.name}: {row.available} available")
    announce_export(summary)
    return 0


def cmd_inventory_report(args: argparse.Namespace, ctx: Context) -> int:
    report = ctx.reporting.inventory_report(
        category=args.category, include_removed=args.all
    )
    headers = [
        "CATEGORY", "RESOURCES", "TOTAL", "AVAILABLE", "OUT", "UNAVAILABLE", "LOW",
    ]
    rows = [
        [
            item.category,
            item.resources,
            item.total,
            item.available,
            item.issued,
            item.unavailable,
            item.low_stock,
        ]
        for item in report.categories
    ]
    summary = export_report(
        args, ctx, report="inventory", payload=report, headers=headers, rows=rows
    )

    if ctx.as_json:
        output.print_json(summary if summary else report)
        return 0

    output.emit(
        False,
        headers=headers,
        rows=rows,
        empty="No resources found. Try: lender seed",
    )
    if report.rows:
        _print_totals(report.totals)
    announce_export(summary)
    return 0


def cmd_low_stock(args: argparse.Namespace, ctx: Context) -> int:
    rows = ctx.reporting.low_stock()
    headers = ["ID", "NAME", "CATEGORY", "AVAILABLE", "TOTAL", "NEEDED"]
    table = [
        [row.resource_id, row.name, row.category, row.available, row.total, row.needed]
        for row in rows
    ]
    summary = export_report(
        args, ctx, report="low-stock", payload=rows, headers=headers, rows=table
    )

    if summary and ctx.as_json:
        output.print_json(summary)
        return 0

    output.emit(
        ctx.as_json,
        payload=rows,
        headers=headers,
        rows=table,
        empty="No resources are low on stock.",
    )
    announce_export(summary)
    return 0


def cmd_most_borrowed(args: argparse.Namespace, ctx: Context) -> int:
    rows = ctx.reporting.most_borrowed()
    headers = ["ID", "NAME", "UNITS OUT"]
    table = [[row["resource_id"], row["name"], row["borrowed"]] for row in rows]
    summary = export_report(
        args, ctx, report="most-borrowed", payload=rows, headers=headers, rows=table
    )

    if summary and ctx.as_json:
        output.print_json(summary)
        return 0

    output.emit(
        ctx.as_json,
        payload=rows,
        headers=headers,
        rows=table,
        empty="Nothing is currently on loan.",
    )
    if not ctx.as_json and len(rows) > 1:
        output.info(f"\n{len(rows)} resources are tied at the highest count.")
    announce_export(summary)
    return 0
