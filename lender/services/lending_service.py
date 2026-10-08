from __future__ import annotations

from datetime import datetime

from ..domain.equipment import Condition, Resource
from ..domain.errors import ConflictError, NotFoundError, ValidationError
from ..domain.events import SYSTEM_ACTOR, EventType
from ..domain.people import Person
from ..domain.transactions import Transaction, checkout_payload, return_payload
from ..storage.projections import State
from ..storage.store import Store
from ..validators.dates import (
    add_days,
    now,
    now_iso,
    parse_date,
    parse_datetime,
    require_not_before,
    to_iso,
)
from ..validators.quantities import require_positive
from ..validators.strings import normalise_name

DEFAULT_LOAN_DAYS = 14
TRANSACTION_PREFIX = "T"


def _resource_or_raise(state: State, reference: str) -> Resource:
    text = normalise_name(reference, "resource reference")
    resource = state.resources.get(text)
    if resource is None:
        raise NotFoundError(f"no resource with ID {reference!r}")
    return resource


def _person_or_raise(state: State, reference: str) -> Person:
    text = normalise_name(reference, "borrower reference")
    person = state.people.get(text)
    if person is None:
        raise NotFoundError(f"no borrower with ID {reference!r}")
    return person


class LendingService:
    def __init__(self, store: Store) -> None:
        self._store = store

    @property
    def _state(self) -> State:
        return self._store.state

    def check_out(
        self,
        resource: str,
        borrower: str,
        quantity: int,
        *,
        due_at: str | datetime | None = None,
        days: int | None = None,
        notes: str = "",
        actor: str = SYSTEM_ACTOR,
    ) -> Transaction:
        item = _resource_or_raise(self._state, resource)
        item.require_active("lend")
        person = _person_or_raise(self._state, borrower)
        person.require_can_borrow()

        amount = require_positive(quantity, "quantity")
        if amount > item.available_quantity:
            raise ConflictError(
                f"cannot check out {amount} unit(s) of {item.id} ({item.name}): "
                f"only {item.available_quantity} available"
            )

        issued = now()
        moment = to_iso(issued)
        deadline = self._resolve_due_at(due_at, days, issued)
        require_not_before(
            parse_datetime(deadline, "due date"),
            issued,
            "due date",
            "issue date",
        )

        transaction_id = self._next_transaction_id()
        self._store.append(
            EventType.LOAN_CHECKED_OUT,
            checkout_payload(
                transaction_id=transaction_id,
                resource_id=item.id,
                borrower_id=person.id,
                quantity=amount,
                due_at=deadline,
                condition_on_issue=Condition.GOOD,
                issued_by=actor,
                notes=notes.strip(),
            ),
            actor=actor,
            occurred_at=moment,
        )
        return self._state.loans[transaction_id]

    def return_units(
        self,
        checkout: str,
        quantity: int | None = None,
        *,
        condition: str | Condition = Condition.GOOD,
        notes: str = "",
        actor: str = SYSTEM_ACTOR,
    ) -> Transaction:
        loan = self.get_loan(checkout)
        if loan.is_returned:
            raise ConflictError(
                f"loan {loan.transaction_id} is already fully returned"
            )

        amount = (
            loan.outstanding_quantity
            if quantity is None
            else require_positive(quantity, "quantity")
        )
        if amount > loan.outstanding_quantity:
            raise ValidationError(
                f"loan {loan.transaction_id}: cannot return {amount} unit(s); "
                f"only {loan.outstanding_quantity} outstanding"
            )

        returned_condition = Condition.parse(condition)
        moment = now_iso()
        self._store.append(
            EventType.LOAN_RETURNED,
            return_payload(
                transaction_id=self._next_transaction_id(),
                checkout_transaction_id=loan.transaction_id,
                resource_id=loan.resource_id,
                borrower_id=loan.borrower_id,
                quantity=amount,
                condition_on_return=returned_condition,
                returned_by=actor,
                notes=notes.strip(),
            ),
            actor=actor,
            occurred_at=moment,
        )
        return self._state.loans[loan.transaction_id]

    def get_loan(self, reference: str) -> Transaction:
        text = normalise_name(reference, "loan reference")
        loan = self._state.loans.get(text)
        if loan is None:
            raise NotFoundError(f"no loan with transaction ID {reference!r}")
        return loan

    def history(
        self,
        *,
        resource: str | None = None,
        borrower: str | None = None,
        outstanding_only: bool = False,
    ) -> list[Transaction]:
        loans = list(self._state.loans.values())

        if resource is not None:
            item = _resource_or_raise(self._state, resource)
            loans = [loan for loan in loans if loan.resource_id == item.id]
        if borrower is not None:
            person = _person_or_raise(self._state, borrower)
            loans = [loan for loan in loans if loan.borrower_id == person.id]
        if outstanding_only:
            loans = [loan for loan in loans if not loan.is_returned]

        return sorted(loans, key=lambda loan: (loan.issued_at, loan.transaction_id))

    def overdue(
        self, *, at: datetime | None = None, borrower: str | None = None
    ) -> list[Transaction]:
        reference = at or now()
        loans = [loan for loan in self._state.loans.values() if loan.is_overdue(reference)]
        if borrower is not None:
            person = _person_or_raise(self._state, borrower)
            loans = [loan for loan in loans if loan.borrower_id == person.id]
        return sorted(loans, key=lambda loan: (loan.due_at, loan.transaction_id))

    def borrower_history(
        self, reference: str, *, at: datetime | None = None
    ) -> dict[str, object]:
        person = _person_or_raise(self._state, reference)
        reference_time = at or now()
        loans = self.history(borrower=person.id)
        open_loans = [loan for loan in loans if not loan.is_returned]
        overdue = [loan for loan in open_loans if loan.is_overdue(reference_time)]

        group = self._state.groups.get(person.group_id)
        return {
            "borrower_id": person.id,
            "name": person.name,
            "type": person.type.value,
            "status": person.status.value,
            "group_id": person.group_id,
            "group_name": group.name if group else person.group_id,
            "group_type": group.type.value if group else "",
            "loans": loans,
            "total_loans": len(loans),
            "open_loans": open_loans,
            "overdue_loans": overdue,
            "lifetime_units": sum(loan.quantity for loan in loans),
            "outstanding_units": sum(loan.outstanding_quantity for loan in open_loans),
        }

    def _resolve_due_at(
        self,
        due_at: str | datetime | None,
        days: int | None,
        issued: datetime,
    ) -> str:
        if due_at is not None and days is not None:
            raise ValidationError("use either --due or --days, not both")
        if due_at is not None:
            if isinstance(due_at, datetime):
                return to_iso(due_at)
            text = str(due_at).strip()
            if not text:
                raise ValidationError("due date must not be empty")
            if len(text) == 10:
                day = parse_date(text, "due date")
                return to_iso(datetime(day.year, day.month, day.day, 23, 59, 59))
            return to_iso(parse_datetime(text, "due date"))
        period = DEFAULT_LOAN_DAYS if days is None else require_positive(days, "days")
        return to_iso(add_days(issued, period))

    def _next_transaction_id(self) -> str:
        highest = 0
        for transaction_id in self._state.loans:
            digits = transaction_id[len(TRANSACTION_PREFIX) :]
            if digits.isdigit():
                highest = max(highest, int(digits))
        return f"{TRANSACTION_PREFIX}{highest + 1:06d}"
