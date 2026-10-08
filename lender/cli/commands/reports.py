from __future__ import annotations

import argparse

from .. import output
from ..context import Context

STATUS_COLUMNS = [
    "ID", "NAME", "CATEGORY", "AVAILABLE", "OUT", "FAULTY", "DAMAGED",
    "MISSING", "RETIRED", "NEEDED", "FLAG",
]


def register(subparsers: argparse._SubParsersAction) -> None:
    status = subparsers.add_parser(
        "report-store-status", help="Show what is available, out, faulty and needed"
    )
    status.add_argument("--all", action="store_true", help="Include removed resources")
    status.set_defaults(handler=cmd_store_status)

    inventory = subparsers.add_parser(
        "report-inventory", help="Summarise inventory levels by category"
    )
    inventory.add_argument("--category", help="Limit to a category")
    inventory.add_argument("--all", action="store_true", help="Include removed resources")
    inventory.set_defaults(handler=cmd_inventory_report)

    low = subparsers.add_parser(
        "report-low-stock", help="Resources with fewer than 3 available units"
    )
    low.set_defaults(handler=cmd_low_stock)

    most = subparsers.add_parser(
        "report-most-borrowed", help="Resource(s) with the most units currently borrowed"
    )
    most.set_defaults(handler=cmd_most_borrowed)


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

    if ctx.as_json:
        output.print_json(status)
        return 0

    output.emit(
        False,
        headers=STATUS_COLUMNS,
        rows=[_status_row(row, ctx) for row in status.rows],
        empty="The store is empty. Try: lender seed",
    )
    if status.rows:
        _print_totals(status.totals)
    if status.low_stock:
        output.info("")
        output.info(f"Low stock (fewer than 3 available): {len(status.low_stock)}")
        for row in status.low_stock:
            output.info(f"  {row.resource_id}  {row.name}: {row.available} available")
    return 0


def cmd_inventory_report(args: argparse.Namespace, ctx: Context) -> int:
    report = ctx.reporting.inventory_report(
        category=args.category, include_removed=args.all
    )

    if ctx.as_json:
        output.print_json(report)
        return 0

    output.emit(
        False,
        headers=["CATEGORY", "RESOURCES", "TOTAL", "AVAILABLE", "OUT", "UNAVAILABLE", "LOW"],
        rows=[
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
        ],
        empty="No resources found. Try: lender seed",
    )
    if report.rows:
        _print_totals(report.totals)
    return 0


def cmd_low_stock(args: argparse.Namespace, ctx: Context) -> int:
    rows = ctx.reporting.low_stock()
    output.emit(
        ctx.as_json,
        payload=rows,
        headers=["ID", "NAME", "CATEGORY", "AVAILABLE", "TOTAL", "NEEDED"],
        rows=[
            [row.resource_id, row.name, row.category, row.available, row.total, row.needed]
            for row in rows
        ],
        empty="No resources are low on stock.",
    )
    return 0


def cmd_most_borrowed(args: argparse.Namespace, ctx: Context) -> int:
    rows = ctx.reporting.most_borrowed()
    output.emit(
        ctx.as_json,
        payload=rows,
        headers=["ID", "NAME", "UNITS OUT"],
        rows=[[row["resource_id"], row["name"], row["borrowed"]] for row in rows],
        empty="Nothing is currently on loan.",
    )
    if not ctx.as_json and len(rows) > 1:
        output.info(f"\n{len(rows)} resources are tied at the highest count.")
    return 0
