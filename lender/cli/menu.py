from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..domain.equipment import Condition
from ..services.import_export_service import DATASETS, IMPORT_MODES
from ..validators.strings import truncate
from . import output

EXITS = frozenset({"0", "q", "quit", "exit", "bye", "done"})
HELP_WORDS = frozenset({"?", "h", "help", "commands"})
CONDITIONS = tuple(condition.value for condition in Condition)


@dataclass(frozen=True)
class Field:
    label: str
    flag: str | None = None
    kind: type = str
    optional: bool = False
    choices: tuple[str, ...] = ()
    hint: str = ""


@dataclass(frozen=True)
class Entry:
    key: str
    title: str
    command: tuple[str, ...]
    section: str
    fields: tuple[Field, ...] = ()


ENTRIES: tuple[Entry, ...] = (
    Entry(
        "list-resources",
        "List every resource",
        ("list-resources",),
        "Resources",
    ),
    Entry(
        "find-resource",
        "Find a resource by name or ID",
        ("find-resource",),
        "Resources",
        (Field("Name or ID"),),
    ),
    Entry(
        "find-by-category",
        "Filter resources by category",
        ("find-by-category",),
        "Resources",
        (Field("Category name or ID"),),
    ),
    Entry(
        "add-resource",
        "Add a resource",
        ("add-resource",),
        "Resources",
        (
            Field("Name", flag="--name", hint="e.g. Dell Latitude"),
            Field("Category", flag="--category"),
            Field("Subcategory", flag="--subcategory"),
            Field("Total units", flag="--total", kind=int),
            Field(
                "Units still needed",
                flag="--needed",
                kind=int,
                optional=True,
                hint="blank for none",
            ),
            Field("Notes", flag="--notes", optional=True, hint="blank for none"),
        ),
    ),
    Entry(
        "update-resource",
        "Update a resource's details",
        ("update-resource",),
        "Resources",
        (
            Field("Resource ID"),
            Field("New name", flag="--name", optional=True, hint="blank to keep"),
            Field("New total units", flag="--total", kind=int, optional=True, hint="blank to keep"),
            Field(
                "Units still needed",
                flag="--needed",
                kind=int,
                optional=True,
                hint="blank to keep",
            ),
        ),
    ),
    Entry(
        "mark-condition",
        "Record faulty, damaged, missing or retired units",
        ("mark-condition",),
        "Resources",
        (
            Field("Resource ID"),
            Field("Condition", choices=CONDITIONS),
            Field("How many units", kind=int),
            Field("Reason", flag="--reason", optional=True, hint="blank for none"),
        ),
    ),
    Entry(
        "list-borrowers",
        "List registered borrowers",
        ("list-borrowers",),
        "Borrowers",
    ),
    Entry(
        "find-borrower",
        "Find a borrower by name or ID",
        ("find-borrower",),
        "Borrowers",
        (Field("Name or ID"),),
    ),
    Entry(
        "add-fellow",
        "Register a Fellow",
        ("add-fellow",),
        "Borrowers",
        (Field("Full name"), Field("Cohort name or ID", flag="--cohort")),
    ),
    Entry(
        "add-piscine",
        "Register a Piscine trial candidate",
        ("add-piscine",),
        "Borrowers",
        (Field("Full name"), Field("Trial group name or ID", flag="--trial")),
    ),
    Entry(
        "add-cohort",
        "Create a cohort",
        ("add-cohort",),
        "Borrowers",
        (Field("Cohort name", hint="e.g. cluster-5-mar"),),
    ),
    Entry(
        "add-trial",
        "Create a Piscine trial group",
        ("add-trial",),
        "Borrowers",
        (Field("Trial group name", hint="e.g. january-2026-trial"),),
    ),
    Entry(
        "list-groups",
        "List cohorts and trial groups",
        ("list-groups",),
        "Borrowers",
    ),
    Entry(
        "checkout",
        "Lend equipment to a borrower",
        ("checkout",),
        "Lending",
        (
            Field("Resource ID"),
            Field("Borrower ID"),
            Field("How many units", kind=int),
            Field(
                "Loan period in days",
                flag="--days",
                kind=int,
                optional=True,
                hint="blank for 14",
            ),
            Field("Notes", flag="--notes", optional=True, hint="blank for none"),
        ),
    ),
    Entry(
        "return",
        "Take equipment back",
        ("return",),
        "Lending",
        (
            Field("Loan ID", hint="e.g. T000001"),
            Field("How many units", optional=True, hint="blank to return everything"),
            Field(
                "Condition on return",
                flag="--condition",
                choices=CONDITIONS,
                optional=True,
                hint="blank for good",
            ),
            Field("Notes", flag="--notes", optional=True, hint="blank for none"),
        ),
    ),
    Entry(
        "history",
        "Show lending transactions",
        ("history",),
        "Lending",
        (
            Field("Borrower ID", flag="--borrower", optional=True, hint="blank for everyone"),
            Field("Resource ID", flag="--resource", optional=True, hint="blank for every resource"),
        ),
    ),
    Entry(
        "history-open",
        "Show loans that are still out",
        ("history", "--open"),
        "Lending",
    ),
    Entry(
        "overdue",
        "Show overdue loans",
        ("overdue",),
        "Lending",
    ),
    Entry(
        "report-borrower-history",
        "One borrower's full lending history",
        ("report-borrower-history",),
        "Lending",
        (Field("Borrower ID"),),
    ),
    Entry(
        "report-store-status",
        "What is available, out, faulty and needed",
        ("report-store-status",),
        "Reports",
    ),
    Entry(
        "report-inventory",
        "Inventory levels by category",
        ("report-inventory",),
        "Reports",
        (Field("Category", flag="--category", optional=True, hint="blank for every category"),),
    ),
    Entry(
        "report-low-stock",
        "Resources with fewer than 3 available",
        ("report-low-stock",),
        "Reports",
    ),
    Entry(
        "report-most-borrowed",
        "Resource(s) with the most units out",
        ("report-most-borrowed",),
        "Reports",
    ),
    Entry(
        "taxonomy",
        "List categories and subcategories",
        ("list-categories",),
        "Setup",
    ),
    Entry(
        "add-category",
        "Create a category",
        ("add-category",),
        "Setup",
        (Field("Category name"),),
    ),
    Entry(
        "add-subcategory",
        "Create a subcategory",
        ("add-subcategory",),
        "Setup",
        (Field("Category name or ID"), Field("Subcategory name")),
    ),
    Entry(
        "seed",
        "Load the startup data into an empty store",
        ("seed",),
        "Setup",
    ),
    Entry(
        "export-json",
        "Back the whole store up to a JSON file",
        ("export",),
        "Setup",
        (Field("File to write", flag="--out", hint="e.g. backup.json"),),
    ),
    Entry(
        "export-csv",
        "Write one dataset out as CSV",
        ("export",),
        "Setup",
        (
            Field("File to write", flag="--out", hint="e.g. resources.csv"),
            Field("Dataset", flag="--dataset", choices=DATASETS),
        ),
    ),
    Entry(
        "import",
        "Load a JSON or CSV file into the store",
        ("import",),
        "Setup",
        (
            Field("File to read"),
            Field(
                "Dataset",
                flag="--dataset",
                choices=DATASETS,
                optional=True,
                hint="needed for CSV",
            ),
            Field(
                "Mode",
                flag="--mode",
                choices=IMPORT_MODES,
                optional=True,
                hint="merge or replace",
            ),
        ),
    ),
)


def _read(prompt: str) -> str | None:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        return None


def _render_menu() -> None:
    output.info("")
    section = ""
    for index, entry in enumerate(ENTRIES, 1):
        if entry.section != section:
            section = entry.section
            output.info("")
            output.info(f"  {section}")
        output.info(f"    {index:>2}. {entry.title}")
    output.info("")
    output.info("    ?  list every command")
    output.info("    0  exit")
    output.info("")
    output.info("  Press Enter to print this menu again; Ctrl+C abandons the action you are in.")


def _describe(field: Field) -> str:
    details = []
    if field.choices:
        separator = " or " if len(field.choices) == 2 else ", "
        details.append(separator.join(field.choices))
    if field.hint:
        details.append(field.hint)
    if field.optional:
        details.append("optional")
    return f" ({'; '.join(details)})" if details else ""


def _collect(entry: Entry) -> list[str] | None:
    argv = list(entry.command)
    for field in entry.fields:
        while True:
            raw = _read(f"{field.label}{_describe(field)}: ")
            if raw is None:
                return None
            text = raw.strip()

            if not text:
                if field.optional:
                    break
                output.warn(f"{field.label} is required.")
                continue
            if field.choices and text.lower() not in field.choices:
                output.warn(f"{field.label} must be one of {', '.join(field.choices)}")
                continue
            if field.kind is int:
                try:
                    int(text)
                except ValueError:
                    output.warn(f"{field.label} must be a whole number, got {text!r}")
                    continue

            if field.flag:
                argv.extend([field.flag, text])
            else:
                argv.append(text)
            break
    return argv


def _lookup(text: str) -> Entry | None:
    if text.isdigit():
        position = int(text)
        if 1 <= position <= len(ENTRIES):
            return ENTRIES[position - 1]
        return None
    lowered = text.lower()
    for entry in ENTRIES:
        if entry.key == lowered:
            return entry
    return None


def _run(dispatch: Callable[[Sequence[str]], int], argv: Sequence[str]) -> None:
    try:
        dispatch(list(argv))
    except SystemExit:
        pass


def run(dispatch: Callable[[Sequence[str]], int], *, intro: str = "") -> int:
    output.info("")
    output.info("Learn2Earn Lender — equipment inventory and lending")
    if intro:
        output.info(intro)

    while True:
        _render_menu()
        raw = _read("Select an option: ")
        if raw is None:
            output.info("")
            output.info("Leaving the menu.")
            return 0
        output.info("")

        text = raw.strip()
        if not text:
            continue
        if text.lower() in EXITS:
            output.info("Leaving the menu.")
            return 0
        if text.lower() in HELP_WORDS:
            _run(dispatch, ["--help"])
            continue

        entry = _lookup(text)
        if entry is None:
            output.warn(
                f"{truncate(text, 24)!r} is not one of the options — enter a number "
                f"from 1 to {len(ENTRIES)}, ? for the command list, or 0 to exit."
            )
            continue

        argv = _collect(entry)
        if argv is None:
            output.info("Cancelled.")
            continue
        _run(dispatch, argv)
