from __future__ import annotations

import argparse

from .. import output
from ..context import Context
from ...domain.equipment import Condition

COLUMNS = ["ID", "NAME", "CATEGORY", "SUBCATEGORY", "TOTAL", "AVAIL", "OUT", "FAULTY", "DAMAGED", "MISSING", "RETIRED", "NEEDED"]


def register(subparsers: argparse._SubParsersAction) -> None:
    add = subparsers.add_parser("add-resource", help="Add an equipment resource")
    add.add_argument("--name", required=True, help="Resource name, e.g. 'Dell Latitude'")
    add.add_argument("--category", required=True, help="Category ID or name")
    add.add_argument("--subcategory", required=True, help="Subcategory ID or name")
    add.add_argument("--total", required=True, type=int, help="Total units owned")
    add.add_argument("--needed", type=int, default=0, help="Procurement target")
    add.add_argument("--notes", default="", help="Free-form notes")
    add.add_argument("--id", dest="resource_id", help="Explicit resource ID")
    add.set_defaults(handler=cmd_add_resource)

    update = subparsers.add_parser("update-resource", help="Update resource details")
    update.add_argument("resource", help="Resource ID")
    update.add_argument("--name", help="New name")
    update.add_argument("--category", help="New category")
    update.add_argument("--subcategory", help="New subcategory")
    update.add_argument("--total", type=int, help="New total quantity")
    update.add_argument("--needed", type=int, help="New procurement target")
    update.add_argument("--notes", help="New notes")
    update.set_defaults(handler=cmd_update_resource)

    remove = subparsers.add_parser("remove-resource", help="Remove a resource from lending")
    remove.add_argument("resource", help="Resource ID")
    remove.add_argument("--reason", default="", help="Why it is being removed")
    remove.set_defaults(handler=cmd_remove_resource)

    restore = subparsers.add_parser("restore-resource", help="Bring a removed resource back")
    restore.add_argument("resource", help="Resource ID")
    restore.set_defaults(handler=cmd_restore_resource)

    listing = subparsers.add_parser("list-resources", help="List equipment resources")
    listing.add_argument("--category", help="Limit to a category")
    listing.add_argument("--subcategory", help="Limit to a subcategory")
    listing.add_argument("--all", action="store_true", help="Include removed resources")
    listing.set_defaults(handler=cmd_list_resources, writes=False)

    find = subparsers.add_parser("find-resource", help="Find resources by ID or name")
    find.add_argument("term", help="ID, exact name, or partial name")
    find.add_argument("--all", action="store_true", help="Include removed resources")
    find.set_defaults(handler=cmd_find_resource, writes=False)

    by_category = subparsers.add_parser(
        "find-by-category", help="Find resources in a category"
    )
    by_category.add_argument("category", help="Category ID or name")
    by_category.add_argument("--subcategory", help="Limit to a subcategory")
    by_category.add_argument("--all", action="store_true", help="Include removed resources")
    by_category.set_defaults(handler=cmd_find_by_category, writes=False)

    mark = subparsers.add_parser(
        "mark-condition", help="Move units into or out of a condition bucket"
    )
    mark.add_argument("resource", help="Resource ID")
    mark.add_argument(
        "condition",
        help="Condition to apply: faulty, damaged, missing, retired, or good",
    )
    mark.add_argument("quantity", type=int, help="How many units")
    mark.add_argument(
        "--from",
        dest="restore_from",
        help="Source condition when restoring units to good",
    )
    mark.add_argument("--reason", default="", help="Why the condition changed")
    mark.set_defaults(handler=cmd_mark_condition)


def _row(resource, ctx: Context) -> list[object]:
    counts = resource.condition_counts
    return [
        resource.id,
        resource.name,
        ctx.taxonomy.display_name(resource.category_id),
        ctx.taxonomy.display_name(resource.subcategory_id),
        resource.total_quantity,
        resource.available_quantity,
        resource.issued_quantity,
        counts.get(Condition.FAULTY.value, 0),
        counts.get(Condition.DAMAGED.value, 0),
        counts.get(Condition.MISSING.value, 0),
        counts.get(Condition.RETIRED.value, 0),
        resource.needed_quantity,
    ]


def _emit_resources(resources, ctx: Context, empty: str) -> None:
    output.emit(
        ctx.as_json,
        payload=[resource.to_dict() for resource in resources],
        headers=COLUMNS,
        rows=[_row(resource, ctx) for resource in resources],
        empty=empty,
    )


def cmd_add_resource(args: argparse.Namespace, ctx: Context) -> int:
    resource = ctx.inventory.add_resource(
        name=args.name,
        category=args.category,
        subcategory=args.subcategory,
        total_quantity=args.total,
        needed_quantity=args.needed,
        notes=args.notes,
        resource_id=args.resource_id,
        actor=ctx.actor,
    )
    if ctx.as_json:
        output.print_json(resource.to_dict())
    else:
        output.info(
            f"Added {resource.id} ({resource.name}): "
            f"{resource.total_quantity} unit(s) available"
        )
    return 0


def cmd_update_resource(args: argparse.Namespace, ctx: Context) -> int:
    resource = ctx.inventory.update_resource(
        args.resource,
        name=args.name,
        category=args.category,
        subcategory=args.subcategory,
        total_quantity=args.total,
        needed_quantity=args.needed,
        notes=args.notes,
        actor=ctx.actor,
    )
    if ctx.as_json:
        output.print_json(resource.to_dict())
    else:
        output.info(
            f"Updated {resource.id} ({resource.name}): "
            f"{resource.total_quantity} total, {resource.available_quantity} available"
        )
    return 0


def cmd_remove_resource(args: argparse.Namespace, ctx: Context) -> int:
    resource = ctx.inventory.remove_resource(
        args.resource, reason=args.reason, actor=ctx.actor
    )
    if ctx.as_json:
        output.print_json(resource.to_dict())
    else:
        output.info(
            f"Removed {resource.id} ({resource.name}). "
            "Lending history is preserved."
        )
    return 0


def cmd_restore_resource(args: argparse.Namespace, ctx: Context) -> int:
    resource = ctx.inventory.restore_resource(args.resource, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(resource.to_dict())
    else:
        output.info(f"Restored {resource.id} ({resource.name})")
    return 0


def cmd_list_resources(args: argparse.Namespace, ctx: Context) -> int:
    resources = ctx.inventory.list_resources(
        category=args.category,
        subcategory=args.subcategory,
        include_removed=args.all,
    )
    _emit_resources(resources, ctx, "No resources found.")
    return 0


def cmd_find_resource(args: argparse.Namespace, ctx: Context) -> int:
    resources = ctx.inventory.search_resources(args.term, include_removed=args.all)
    _emit_resources(resources, ctx, f"No resource matches {args.term!r}.")
    return 0


def cmd_find_by_category(args: argparse.Namespace, ctx: Context) -> int:
    if args.subcategory:
        resources = ctx.inventory.find_by_subcategory(
            args.subcategory, category=args.category, include_removed=args.all
        )
    else:
        resources = ctx.inventory.find_by_category(
            args.category, include_removed=args.all
        )
    _emit_resources(resources, ctx, f"No resources in {args.category!r}.")
    return 0


def cmd_mark_condition(args: argparse.Namespace, ctx: Context) -> int:
    resource = ctx.inventory.mark_condition(
        args.resource,
        args.condition,
        args.quantity,
        restore_from=args.restore_from,
        reason=args.reason,
        actor=ctx.actor,
    )
    if ctx.as_json:
        output.print_json(resource.to_dict())
    else:
        target = Condition.parse(args.condition)
        if target is Condition.GOOD:
            message = (
                f"Restored {args.quantity} unit(s) of {resource.id} "
                f"to good from {Condition.parse(args.restore_from).value}"
            )
        else:
            message = (
                f"Marked {args.quantity} unit(s) of {resource.id} as {target.value}"
            )
        output.info(
            f"{message}. {resource.available_quantity} available, "
            f"{resource.unavailable_quantity} unavailable."
        )
    return 0
