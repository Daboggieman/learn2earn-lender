from __future__ import annotations

import argparse

from .. import output
from ..context import Context


def register(subparsers: argparse._SubParsersAction) -> None:
    create = subparsers.add_parser("add-category", help="Create an equipment category")
    create.add_argument("name", help="Category display name")
    create.set_defaults(handler=cmd_add_category)

    listing = subparsers.add_parser("list-categories", help="List equipment categories")
    listing.add_argument("--all", action="store_true", help="Include removed categories")
    listing.set_defaults(handler=cmd_list_categories, writes=False)

    update = subparsers.add_parser("update-category", help="Rename a category")
    update.add_argument("category", help="Category ID or name")
    update.add_argument("--name", required=True, help="New category name")
    update.set_defaults(handler=cmd_update_category)

    remove = subparsers.add_parser("remove-category", help="Remove an empty category")
    remove.add_argument("category", help="Category ID or name")
    remove.set_defaults(handler=cmd_remove_category)

    add_sub = subparsers.add_parser("add-subcategory", help="Create a subcategory")
    add_sub.add_argument("category", help="Parent category ID or name")
    add_sub.add_argument("name", help="Subcategory display name")
    add_sub.set_defaults(handler=cmd_add_subcategory)

    list_sub = subparsers.add_parser("list-subcategories", help="List subcategories")
    list_sub.add_argument("category", nargs="?", help="Limit to one category")
    list_sub.add_argument("--all", action="store_true", help="Include removed subcategories")
    list_sub.set_defaults(handler=cmd_list_subcategories, writes=False)

    update_sub = subparsers.add_parser("update-subcategory", help="Rename a subcategory")
    update_sub.add_argument("subcategory", help="Subcategory ID or name")
    update_sub.add_argument("--name", required=True, help="New subcategory name")
    update_sub.add_argument("--category", help="Disambiguate by parent category")
    update_sub.set_defaults(handler=cmd_update_subcategory)

    remove_sub = subparsers.add_parser("remove-subcategory", help="Remove an unused subcategory")
    remove_sub.add_argument("subcategory", help="Subcategory ID or name")
    remove_sub.add_argument("--category", help="Disambiguate by parent category")
    remove_sub.set_defaults(handler=cmd_remove_subcategory)


def _resource_count(ctx: Context, node_id: str) -> int:
    return len(
        [
            resource
            for resource in ctx.store.state.resources.values()
            if node_id in (resource.category_id, resource.subcategory_id)
        ]
    )


def cmd_add_category(args: argparse.Namespace, ctx: Context) -> int:
    node = ctx.taxonomy.create_category(args.name, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(node.to_dict())
    else:
        output.info(f"Created category {node.id} ({node.name})")
    return 0


def cmd_list_categories(args: argparse.Namespace, ctx: Context) -> int:
    nodes = ctx.taxonomy.list_categories(include_removed=args.all)
    rows = [
        [node.id, node.name, node.status.value, _resource_count(ctx, node.id)]
        for node in nodes
    ]
    output.emit(
        ctx.as_json,
        payload=[node.to_dict() for node in nodes],
        headers=["ID", "NAME", "STATUS", "RESOURCES"],
        rows=rows,
        empty="No categories yet. Try: lender add-category Electronics",
    )
    return 0


def cmd_update_category(args: argparse.Namespace, ctx: Context) -> int:
    node = ctx.taxonomy.rename_category(args.category, args.name, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(node.to_dict())
    else:
        output.info(f"Renamed category {node.id} to {node.name!r}")
    return 0


def cmd_remove_category(args: argparse.Namespace, ctx: Context) -> int:
    node = ctx.taxonomy.remove_category(args.category, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(node.to_dict())
    else:
        output.info(f"Removed category {node.id} ({node.name})")
    return 0


def cmd_add_subcategory(args: argparse.Namespace, ctx: Context) -> int:
    node = ctx.taxonomy.create_subcategory(args.category, args.name, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(node.to_dict())
    else:
        parent = ctx.taxonomy.display_name(node.parent_id)
        output.info(f"Created subcategory {node.id} ({node.name}) under {parent}")
    return 0


def cmd_list_subcategories(args: argparse.Namespace, ctx: Context) -> int:
    nodes = ctx.taxonomy.list_subcategories(args.category, include_removed=args.all)
    rows = [
        [
            node.id,
            node.name,
            ctx.taxonomy.display_name(node.parent_id),
            node.status.value,
            _resource_count(ctx, node.id),
        ]
        for node in nodes
    ]
    output.emit(
        ctx.as_json,
        payload=[node.to_dict() for node in nodes],
        headers=["ID", "NAME", "CATEGORY", "STATUS", "RESOURCES"],
        rows=rows,
        empty="No subcategories found.",
    )
    return 0


def cmd_update_subcategory(args: argparse.Namespace, ctx: Context) -> int:
    node = ctx.taxonomy.resolve_subcategory(args.subcategory, args.category)
    updated = ctx.taxonomy.rename_subcategory(node.id, args.name, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(updated.to_dict())
    else:
        output.info(f"Renamed subcategory {updated.id} to {updated.name!r}")
    return 0


def cmd_remove_subcategory(args: argparse.Namespace, ctx: Context) -> int:
    node = ctx.taxonomy.resolve_subcategory(args.subcategory, args.category)
    removed = ctx.taxonomy.remove_subcategory(node.id, actor=ctx.actor)
    if ctx.as_json:
        output.print_json(removed.to_dict())
    else:
        output.info(f"Removed subcategory {removed.id} ({removed.name})")
    return 0
