from __future__ import annotations

import argparse

from .. import output
from ..context import Context
from ...domain.equipment import Condition
from ...domain.transactions import Transaction
from ...services.lending_service import DEFAULT_LOAN_DAYS

LOAN_COLUMNS = [
    "LOAN",
    "RESOURCE",
    "BORROWER",
    "QTY",
    "OUT",
    "ISSUED",
    "DUE",
    "RETURNED",
    "STATUS",
]


def register(subparsers: argparse._SubParsersAction) -> None:
    checkout = subparsers.add_parser("checkout", help="Lend equipment to a borrower")
    checkout.add_argument("resource", help="Resource ID")
    checkout.add_argument("borrower", help="Borrower ID")
    checkout.add_argument("quantity", type=int, help="How many units")
    checkout.add_argument("--due", help="Due date (YYYY-MM-DD) or timestamp")
    checkout.add_argument(
        "--days",
        type=int,
        help=f"Loan period in days (default: {DEFAULT_LOAN_DAYS})",
    )
    checkout.add_argument("--notes", default="", help="Free-form notes")
    checkout.set_defaults(handler=cmd_checkout)

    give_back = subparsers.add_parser("return", help="Take equipment back from a borrower")
    give_back.add_argument("loan", help="Checkout transaction ID")
    give_back.add_argument(
        "quantity",
        nargs="?",
        type=int,
        help="Units to return (default: everything outstanding)",
    )
    give_back.add_argument(
        "--condition",
        default=Condition.GOOD.value,
        help="Condition on return: good, faulty, damaged, missing or retired",
    )
    give_back.add_argument("--notes", default="", help="Free-form notes")
    give_back.set_defaults(handler=cmd_return)

    history = subparsers.add_parser("history", help="Show lending transactions")
    history.add_argument("--resource", help="Limit to one resource")
    history.add_argument("--borrower", help="Limit to one borrower")
    history.add_argument(
        "--open", action="store_true", help="Only show loans still outstanding"
    )
    history.set_defaults(handler=cmd_history)

    overdue = subparsers.add_parser("overdue", help="Show loans past their due date")
    overdue.add_argument("--borrower", help="Limit to one borrower")
    overdue.set_defaults(handler=cmd_overdue)

    borrower = subparsers.add_parser(
        "report-borrower-history", help="Full lending history for one borrower"
    )
    borrower.add_argument("borrower", help="Borrower ID")
    borrower.set_defaults(handler=cmd_report_borrower_history)


def _loan_row(loan: Transaction, ctx: Context) -> list[object]:
    name = ctx.store.state.resources.get(loan.resource_id)
    person = ctx.store.state.people.get(loan.borrower_id)
    return [
        loan.transaction_id,
        f"{loan.resource_id} {name.name}" if name else loan.resource_id,
        f"{loan.borrower_id} {person.name}" if person else loan.borrower_id,
        loan.quantity,
        loan.outstanding_quantity,
        loan.issued_at[:10],
        loan.due_at[:10],
        loan.returned_at[:10] if loan.returned_at else "—",
        loan.effective_status().value,
    ]


def _emit_loans(loans: list[Transaction], ctx: Context, empty: str) -> None:
    output.emit(
        ctx.as_json,
        payload=[loan.to_dict() for loan in loans],
        headers=LOAN_COLUMNS,
        rows=[_loan_row(loan, ctx) for loan in loans],
        empty=empty,
    )


def cmd_checkout(args: argparse.Namespace, ctx: Context) -> int:
    loan = ctx.lending.check_out(
        args.resource,
        args.borrower,
        args.quantity,
        due_at=args.due,
        days=args.days,
        notes=args.notes,
        actor=ctx.actor,
    )
    if ctx.as_json:
        output.print_json(loan.to_dict())
    else:
        output.info(
            f"Checked out {loan.quantity} unit(s) of {loan.resource_id} to "
            f"{loan.borrower_id} as {loan.transaction_id}; "
            f"due {loan.due_at[:10]}."
        )
    return 0


def cmd_return(args: argparse.Namespace, ctx: Context) -> int:
    loan = ctx.lending.return_units(
        args.loan,
        args.quantity,
        condition=args.condition,
        notes=args.notes,
        actor=ctx.actor,
    )
    if ctx.as_json:
        output.print_json(loan.to_dict())
    else:
        condition = Condition.parse(args.condition)
        if loan.is_returned:
            state = "closed"
        else:
            state = f"{loan.outstanding_quantity} unit(s) still out"
        output.info(
            f"Loan {loan.transaction_id}: {loan.returned_quantity}/"
            f"{loan.quantity} unit(s) of {loan.resource_id} returned from "
            f"{loan.borrower_id} ({condition.value}) — {state}."
        )
    return 0


def cmd_history(args: argparse.Namespace, ctx: Context) -> int:
    loans = ctx.lending.history(
        resource=args.resource,
        borrower=args.borrower,
        outstanding_only=args.open,
    )
    _emit_loans(loans, ctx, "No lending transactions recorded yet.")
    return 0


def cmd_overdue(args: argparse.Namespace, ctx: Context) -> int:
    loans = ctx.lending.overdue(borrower=args.borrower)
    if ctx.as_json:
        output.print_json(
            [
                {**loan.to_dict(), "days_overdue": loan.days_overdue()}
                for loan in loans
            ]
        )
        return 0

    rows = [[*_loan_row(loan, ctx)[:8], loan.days_overdue()] for loan in loans]
    output.emit(
        False,
        payload=[],
        headers=[*LOAN_COLUMNS[:8], "DAYS LATE"],
        rows=rows,
        empty="No overdue loans. Every borrower is up to date.",
    )
    return 0


def cmd_report_borrower_history(args: argparse.Namespace, ctx: Context) -> int:
    summary = ctx.lending.borrower_history(args.borrower)
    loans = summary["loans"]

    if ctx.as_json:
        output.print_json(
            {
                **{
                    key: value
                    for key, value in summary.items()
                    if key not in {"loans", "open_loans", "overdue_loans"}
                },
                "loans": [loan.to_dict() for loan in loans],
                "open_loan_ids": [
                    loan.transaction_id for loan in summary["open_loans"]
                ],
                "overdue_loan_ids": [
                    loan.transaction_id for loan in summary["overdue_loans"]
                ],
            }
        )
        return 0

    output.info(
        f"{summary['name']} ({summary['borrower_id']}, {summary['type']}) — "
        f"{summary['group_name']} [{summary['group_type']}]"
    )
    output.info(
        f"{summary['total_loans']} loan(s) lifetime, "
        f"{summary['lifetime_units']} unit(s) borrowed, "
        f"{len(summary['open_loans'])} still out "
        f"({len(summary['overdue_loans'])} overdue)."
    )
    if not loans:
        output.info("No lending transactions for this borrower yet.")
        return 0
    print()
    output.print_table(LOAN_COLUMNS, [_loan_row(loan, ctx) for loan in loans])
    return 0
