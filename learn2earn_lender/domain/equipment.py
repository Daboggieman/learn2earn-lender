from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import InvariantViolation, ValidationError
from ..validators import quantities as quantity_rules
from ..validators import strings
from ..validators.ids import next_sequential_id, validate_id

LOW_STOCK_THRESHOLD = 3


class Condition(str, Enum):
    GOOD = "good"
    FAULTY = "faulty"
    DAMAGED = "damaged"
    MISSING = "missing"
    RETIRED = "retired"

    @classmethod
    def parse(cls, value: object) -> "Condition":
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        try:
            return cls(text)
        except ValueError as exc:
            allowed = ", ".join(member.value for member in cls)
            raise ValidationError(
                f"unknown condition {value!r}: expected one of {allowed}"
            ) from exc


UNAVAILABLE_CONDITIONS: tuple[Condition, ...] = (
    Condition.FAULTY,
    Condition.DAMAGED,
    Condition.MISSING,
    Condition.RETIRED,
)


class ResourceStatus(str, Enum):
    ACTIVE = "active"
    REMOVED = "removed"

    @classmethod
    def parse(cls, value: object) -> "ResourceStatus":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValidationError(f"unknown resource status {value!r}") from exc


def empty_condition_counts() -> dict[str, int]:
    return {condition.value: 0 for condition in UNAVAILABLE_CONDITIONS}


@dataclass
class Resource:
    id: str
    name: str
    category_id: str
    subcategory_id: str
    total_quantity: int
    available_quantity: int
    issued_quantity: int
    condition_counts: dict[str, int] = field(default_factory=empty_condition_counts)
    needed_quantity: int = 0
    status: ResourceStatus = ResourceStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    @property
    def good_quantity(self) -> int:
        return self.available_quantity + self.issued_quantity

    @property
    def unavailable_quantity(self) -> int:
        return sum(self.condition_counts.values())

    @property
    def is_active(self) -> bool:
        return self.status is ResourceStatus.ACTIVE

    @property
    def is_low_stock(self) -> bool:
        return self.available_quantity < LOW_STOCK_THRESHOLD

    def condition_count(self, condition: Condition) -> int:
        if condition is Condition.GOOD:
            return self.good_quantity
        return self.condition_counts.get(condition.value, 0)

    def check_invariant(self) -> None:
        buckets = {
            "available": self.available_quantity,
            "issued": self.issued_quantity,
            **self.condition_counts,
        }
        for label, value in buckets.items():
            if value < 0:
                raise InvariantViolation(
                    f"resource {self.id}: {label} quantity is negative ({value})"
                )
        accounted = sum(buckets.values())
        if accounted != self.total_quantity:
            detail = " + ".join(f"{name}={value}" for name, value in buckets.items())
            raise InvariantViolation(
                f"resource {self.id}: total_quantity={self.total_quantity} "
                f"but {detail} sums to {accounted}"
            )

    def require_active(self, action: str = "modify") -> None:
        if not self.is_active:
            raise ValidationError(
                f"resource {self.id} is {self.status.value} and cannot be {action}d"
            )

    def set_total_quantity(self, new_total: int) -> None:
        new_total = quantity_rules.require_non_negative(new_total, "total_quantity")
        delta = new_total - self.total_quantity
        if delta == 0:
            return
        if delta > 0:
            self.available_quantity += delta
        else:
            shortfall = -delta
            if shortfall > self.available_quantity:
                raise ValidationError(
                    f"resource {self.id}: cannot reduce total by {shortfall}; "
                    f"only {self.available_quantity} unit(s) are available "
                    f"({self.issued_quantity} issued, {self.unavailable_quantity} unavailable)"
                )
            self.available_quantity -= shortfall
        self.total_quantity = new_total
        self.check_invariant()

    def transfer_condition(
        self, source: Condition, destination: Condition, quantity: int
    ) -> None:
        quantity = quantity_rules.require_positive(quantity, "quantity")
        if source is destination:
            raise ValidationError(
                f"source and destination condition are both {source.value}"
            )

        available_from = self.condition_count(source)
        if quantity > available_from:
            raise ValidationError(
                f"resource {self.id}: cannot move {quantity} unit(s) from "
                f"{source.value}; only {available_from} available there"
            )

        self._adjust_condition(source, -quantity)
        self._adjust_condition(destination, quantity)
        self.check_invariant()

    def issue_units(self, quantity: int) -> None:
        quantity = quantity_rules.require_positive(quantity, "quantity")
        if quantity > self.available_quantity:
            raise ValidationError(
                f"resource {self.id}: cannot issue {quantity} unit(s); "
                f"only {self.available_quantity} available"
            )
        self.available_quantity -= quantity
        self.issued_quantity += quantity
        self.check_invariant()

    def release_units(self, quantity: int, condition_on_return: Condition) -> None:
        quantity = quantity_rules.require_positive(quantity, "quantity")
        if quantity > self.issued_quantity:
            raise ValidationError(
                f"resource {self.id}: cannot return {quantity} unit(s); "
                f"only {self.issued_quantity} are currently on loan"
            )
        self.issued_quantity -= quantity
        self._adjust_condition(condition_on_return, quantity)
        self.check_invariant()

    def _adjust_condition(self, condition: Condition, delta: int) -> None:
        if condition is Condition.GOOD:
            self.available_quantity += delta
            return
        current = self.condition_counts.get(condition.value, 0) + delta
        if current < 0:
            raise InvariantViolation(
                f"resource {self.id}: {condition.value} would become negative"
            )
        self.condition_counts[condition.value] = current

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category_id": self.category_id,
            "subcategory_id": self.subcategory_id,
            "total_quantity": self.total_quantity,
            "available_quantity": self.available_quantity,
            "issued_quantity": self.issued_quantity,
            "condition_counts": dict(self.condition_counts),
            "needed_quantity": self.needed_quantity,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Resource":
        if not isinstance(data, dict):
            raise ValidationError(
                f"resource record must be an object, got {type(data).__name__}"
            )
        missing = [
            key
            for key in ("id", "name", "total_quantity")
            if key not in data or data[key] is None
        ]
        if missing:
            raise ValidationError(f"resource record is missing {', '.join(missing)}")

        total = quantity_rules.require_non_negative(data["total_quantity"], "total_quantity")

        counts = empty_condition_counts()
        raw_counts = data.get("condition_counts") or {}
        if not isinstance(raw_counts, dict):
            raise ValidationError("condition_counts must be an object")
        for key, value in raw_counts.items():
            condition = Condition.parse(key)
            if condition is Condition.GOOD:
                continue
            counts[condition.value] = quantity_rules.require_non_negative(
                value, f"condition_counts.{condition.value}"
            )

        issued = quantity_rules.require_non_negative(
            data.get("issued_quantity", 0), "issued_quantity"
        )
        accounted = sum(counts.values()) + issued
        available = data.get("available_quantity")
        if available is None:
            available = total - accounted
        available = quantity_rules.require_non_negative(available, "available_quantity")

        resource = cls(
            id=validate_id(data["id"], "resource id"),
            name=strings.normalise_name(data["name"], "resource name"),
            category_id=strings.require_non_empty(
                data.get("category_id", ""), "category_id"
            ),
            subcategory_id=strings.require_non_empty(
                data.get("subcategory_id", ""), "subcategory_id"
            ),
            total_quantity=total,
            available_quantity=available,
            issued_quantity=issued,
            condition_counts=counts,
            needed_quantity=quantity_rules.require_non_negative(
                data.get("needed_quantity", 0), "needed_quantity"
            ),
            status=ResourceStatus.parse(data.get("status", ResourceStatus.ACTIVE.value)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            notes=str(data.get("notes", "")),
        )
        resource.check_invariant()
        return resource


def make_resource_id(existing: list[str]) -> str:
    return next_sequential_id("R", existing)
