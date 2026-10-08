"""Lending records — the read model built from checkout and return events.

A loan is a checkout event plus, once it comes back, the return event that
points at it. Storing the pairing explicitly (rather than recording returns as
free-floating events) is what lets the history report answer "what did this
borrower take, when was it due, and what shape did it come back in".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .equipment import Condition
from .errors import ValidationError
from ..validators.dates import parse_datetime
from ..validators.quantities import require_positive


class TransactionType(str, Enum):
    CHECKOUT = "checkout"
    RETURN = "return"

    @classmethod
    def parse(cls, value: object) -> "TransactionType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown transaction type {value!r}") from exc


class LoanStatus(str, Enum):
    """Lifecycle of a loan. ``overdue`` is derived, never stored."""

    ACTIVE = "active"
    RETURNED = "returned"
    OVERDUE = "overdue"
    LOST = "lost"
    CANCELLED = "cancelled"


# ----------------------------------------------------------------------
# Event payload builders
#
# The service layer writes these; the projection layer reads them. Keeping
# the key names in one place is what stops the two from drifting apart.
# ----------------------------------------------------------------------


def checkout_payload(
    *,
    transaction_id: str,
    resource_id: str,
    borrower_id: str,
    quantity: int,
    due_at: str,
    condition_on_issue: Condition,
    issued_by: str,
    notes: str = "",
) -> dict[str, Any]:
    """Payload for :attr:`EventType.LOAN_CHECKED_OUT`."""
    return {
        "transaction_id": transaction_id,
        "resource_id": resource_id,
        "borrower_id": borrower_id,
        "quantity": quantity,
        "due_at": due_at,
        "condition_on_issue": condition_on_issue.value,
        "issued_by": issued_by,
        "notes": notes,
    }


def return_payload(
    *,
    transaction_id: str,
    checkout_transaction_id: str,
    resource_id: str,
    borrower_id: str,
    quantity: int,
    condition_on_return: Condition,
    returned_by: str,
    notes: str = "",
) -> dict[str, Any]:
    """Payload for :attr:`EventType.LOAN_RETURNED`.

    ``checkout_transaction_id`` is the link back to the originating checkout.
    """
    return {
        "transaction_id": transaction_id,
        "checkout_transaction_id": checkout_transaction_id,
        "resource_id": resource_id,
        "borrower_id": borrower_id,
        "quantity": quantity,
        "condition_on_return": condition_on_return.value,
        "returned_by": returned_by,
        "notes": notes,
    }


@dataclass
class Transaction:
    """A loan: one checkout and, optionally, the return that closed it."""

    transaction_id: str
    resource_id: str
    borrower_id: str
    transaction_type: TransactionType
    quantity: int
    issued_at: str
    due_at: str
    condition_on_issue: Condition
    issued_by: str
    returned_at: str | None = None
    returned_quantity: int = 0
    condition_on_return: Condition | None = None
    returned_by: str | None = None
    notes: str = ""
    return_notes: str = ""

    @property
    def outstanding_quantity(self) -> int:
        """Units still in the borrower's hands."""
        return self.quantity - self.returned_quantity

    @property
    def is_returned(self) -> bool:
        """True once every issued unit has come back."""
        return self.returned_quantity >= self.quantity

    def is_overdue(self, at: datetime | None = None) -> bool:
        """True when an open loan is past its due date."""
        if self.is_returned:
            return False
        reference = at or datetime.now()
        return reference > self.due_datetime

    def days_overdue(self, at: datetime | None = None) -> int:
        """Whole days past due; 0 when not overdue."""
        if not self.is_overdue(at):
            return 0
        reference = at or datetime.now()
        return (reference - self.due_datetime).days

    @property
    def due_datetime(self) -> datetime:
        return parse_datetime(self.due_at, "due_at")

    @property
    def issued_datetime(self) -> datetime:
        return parse_datetime(self.issued_at, "issued_at")

    def effective_status(self, at: datetime | None = None) -> LoanStatus:
        """Status including the derived ``overdue`` state."""
        if self.is_returned:
            return LoanStatus.RETURNED
        return LoanStatus.OVERDUE if self.is_overdue(at) else LoanStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "resource_id": self.resource_id,
            "borrower_id": self.borrower_id,
            "transaction_type": self.transaction_type.value,
            "quantity": self.quantity,
            "outstanding_quantity": self.outstanding_quantity,
            "returned_quantity": self.returned_quantity,
            "issued_at": self.issued_at,
            "due_at": self.due_at,
            "returned_at": self.returned_at,
            "condition_on_issue": self.condition_on_issue.value,
            "condition_on_return": (
                self.condition_on_return.value if self.condition_on_return else None
            ),
            "issued_by": self.issued_by,
            "returned_by": self.returned_by,
            "notes": self.notes,
            "return_notes": self.return_notes,
            "status": self.effective_status().value,
        }

    @classmethod
    def from_checkout_event(cls, payload: Mapping[str, Any], occurred_at: str) -> "Transaction":
        """Build an open loan from a ``loan.checked_out`` payload."""
        return cls(
            transaction_id=str(payload["transaction_id"]),
            resource_id=str(payload["resource_id"]),
            borrower_id=str(payload["borrower_id"]),
            transaction_type=TransactionType.CHECKOUT,
            quantity=require_positive(payload["quantity"], "quantity"),
            issued_at=occurred_at,
            due_at=str(payload["due_at"]),
            condition_on_issue=Condition.parse(payload.get("condition_on_issue", "good")),
            issued_by=str(payload.get("issued_by", "")),
            notes=str(payload.get("notes", "")),
        )

    def apply_return(self, payload: Mapping[str, Any], occurred_at: str) -> None:
        """Record units coming back against this loan.

        Accumulates rather than overwrites, so a loan returned in two trips
        is represented correctly.
        """
        quantity = require_positive(payload["quantity"], "quantity")
        if quantity > self.outstanding_quantity:
            raise ValidationError(
                f"loan {self.transaction_id}: cannot return {quantity} unit(s); "
                f"only {self.outstanding_quantity} outstanding "
                f"(invariant: never over-return)"
            )
        self.returned_quantity += quantity
        self.returned_at = occurred_at
        self.condition_on_return = Condition.parse(
            payload.get("condition_on_return", Condition.GOOD.value)
        )
        self.returned_by = str(payload.get("returned_by", ""))
        self.return_notes = str(payload.get("notes", ""))


def checkout_status(
    loans: list[Transaction], transaction_id: str
) -> Transaction | None:
    """Find a loan by its checkout transaction ID."""
    for loan in loans:
        if loan.transaction_id == transaction_id:
            return loan
    return None
