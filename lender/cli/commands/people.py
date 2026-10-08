from __future__ import annotations

import argparse

from .. import output
from ..context import Context
from ...domain.errors import ValidationError


def register(subparsers: argparse._SubParsersAction) -> None:
    fellow = subparsers.add_parser("add-fellow", help="Register a Fellow")
    fellow.add_argument("name", help="Borrower full name")
    fellow.add_argument("--cohort", required=True, help="Cohort ID or name")
    fellow.add_argument("--id", dest="person_id", help="Explicit borrower ID")
    fellow.add_argument("--notes", default="", help="Free-form notes")
    fellow.set_defaults(handler=cmd_add_fellow)

    piscine = subparsers.add_parser("add-piscine", help="Register a Piscine trial candidate")
    piscine.add_argument("name", help="Borrower full name")
    piscine.add_argument("--trial", required=True, help="Trial group ID or name")
    piscine.add_argument("--id", dest="person_id", help="Explicit borrower ID")
    piscine.add_argument("--notes", default="", help="Free-form notes")
    piscine.set_defaults(handler=cmd_add_piscine)

    listing = subparsers.add_parser("list-borrowers", help="List registered borrowers")
    listing.add_argument("--cohort", help="Limit to a cohort")
    listing.add_argument("--trial", help="Limit to a Piscine trial group")
    listing.add_argument(
        "--type", choices=["fellow", "piscine"], help="Limit to one borrower type"
    )
    listing.add_argument("--all", action="store_true", help="Include removed borrowers")
    listing.set_defaults(handler=cmd_list_borrowers)

    find = subparsers.add_parser("find-borrower", help="Find a borrower by ID or name")
    find.add_argument("term", help="ID, exact name, or partial name")
    find.add_argument("--all", action="store_true", help="Include removed borrowers")
    find.set_defaults(handler=cmd_find_borrower)

    cohort = subparsers.add_parser("add-cohort", help="Create a cohort group")
    cohort.add_argument("name", help="Cohort name, e.g. cluster-1-feb")
    cohort.set_defaults(handler=cmd_add_cohort)

    trial = subparsers.add_parser("add-trial", help="Create a Piscine trial group")
    trial.add_argument("name", help="Trial group name, e.g. trial-period-1")
    trial.set_defaults(handler=cmd_add_trial)

    groups = subparsers.add_parser("list-groups", help="List cohorts and trial groups")
    groups.add_argument("--type", choices=["cohort", "trial"], help="Limit to one type")
    groups.add_argument("--all", action="store_true", help="Include archived groups")
    groups.set_defaults(handler=cmd_list_groups)


def _group_label(ctx: Context, person) -> str:
    name = ctx.people.group_name(person.group_id)
    return f"{name} ({person.type.value})"


def cmd_add_fellow(args: argparse.Namespace, ctx: Context) -> int:
    person = ctx.people.add_fellow(
        args.name,
        args.cohort,
        person_id=args.person_id,
        notes=args.notes,
        actor=ctx.actor,
    )
    return _announce(person, ctx, f"Registered Fellow {person.id} ({person.name})")


def cmd_add_piscine(args: argparse.Namespace, ctx: Context) -> int:
    person = ctx.people.add_piscine(
        args.name,
        args.trial,
        person_id=args.person_id,
        notes=args.notes,
        actor=ctx.actor,
    )
    return _announce(
        person, ctx, f"Registered Piscine candidate {person.id} ({person.name})"
    )


def _announce(person, ctx: Context, message: str) -> int:
    if ctx.as_json:
        output.print_json(
            {**person.to_dict(), "group_name": ctx.people.group_name(person.group_id)}
        )
    else:
        output.info(f"{message} in {ctx.people.group_name(person.group_id)}")
    return 0


def cmd_list_borrowers(args: argparse.Namespace, ctx: Context) -> int:
    if args.cohort and args.trial:
        raise ValidationError("use either --cohort or --trial, not both")
    group = args.cohort or args.trial

    people = ctx.people.list_borrowers(
        group=group,
        person_type=args.type,
        include_removed=args.all,
    )
    known = {
        group.id: group
        for group in [
            *ctx.people.list_groups("cohort", include_removed=True),
            *ctx.people.list_groups("trial", include_removed=True),
        ]
    }

    rows = [
        [
            person.id,
            person.name,
            person.type.value,
            ctx.people.group_name(person.group_id),
            known[person.group_id].type.value if person.group_id in known else "—",
            person.status.value,
        ]
        for person in people
    ]
    output.emit(
        ctx.as_json,
        payload=[
            {
                **person.to_dict(),
                "group_name": ctx.people.group_name(person.group_id),
            }
            for person in people
        ],
        headers=["ID", "NAME", "TYPE", "GROUP", "GROUP TYPE", "STATUS"],
        rows=rows,
        empty="No borrowers yet. Try: lender add-fellow 'Ada Lovelace' --cohort cluster-1-feb",
    )
    return 0


def cmd_find_borrower(args: argparse.Namespace, ctx: Context) -> int:
    people = ctx.people.search_borrowers(args.term, include_removed=args.all)
    rows = [
        [
            person.id,
            person.name,
            person.type.value,
            ctx.people.group_name(person.group_id),
            person.status.value,
        ]
        for person in people
    ]
    output.emit(
        ctx.as_json,
        payload=[
            {
                **person.to_dict(),
                "group_name": ctx.people.group_name(person.group_id),
            }
            for person in people
        ],
        headers=["ID", "NAME", "TYPE", "GROUP", "STATUS"],
        rows=rows,
        empty=f"No borrower matches {args.term!r}.",
    )
    return 0


def cmd_add_cohort(args: argparse.Namespace, ctx: Context) -> int:
    group = ctx.people.add_cohort(args.name, actor=ctx.actor)
    return _announce_group(group, ctx, f"Created cohort {group.id} ({group.name})")


def cmd_add_trial(args: argparse.Namespace, ctx: Context) -> int:
    group = ctx.people.add_trial(args.name, actor=ctx.actor)
    return _announce_group(
        group, ctx, f"Created trial group {group.id} ({group.name})"
    )


def _announce_group(group, ctx: Context, message: str) -> int:
    if ctx.as_json:
        output.print_json(group.to_dict())
    else:
        output.info(message)
    return 0


def cmd_list_groups(args: argparse.Namespace, ctx: Context) -> int:
    groups = ctx.people.list_groups(args.type, include_removed=args.all)
    rows = [
        [
            group.id,
            group.name,
            group.type.value,
            group.status.value,
            len(ctx.store.state.people_in_group(group.id)),
        ]
        for group in groups
    ]
    output.emit(
        ctx.as_json,
        payload=[
            {
                **group.to_dict(),
                "members": len(ctx.store.state.people_in_group(group.id)),
            }
            for group in groups
        ],
        headers=["ID", "NAME", "TYPE", "STATUS", "MEMBERS"],
        rows=rows,
        empty="No groups yet. Try: lender add-cohort cluster-1-feb",
    )
    return 0
