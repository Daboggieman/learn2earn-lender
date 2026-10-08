from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain.equipment import Condition, Resource
from ..storage.store import Store
from ..validators.dates import now_iso
from .taxonomy_service import TaxonomyService


@dataclass(frozen=True)
class ResourceStatusRow:
    resource_id: str
    name: str
    category: str
    subcategory: str
    status: str
    total: int
    available: int
    issued: int
    faulty: int
    damaged: int
    missing: int
    retired: int
    needed: int
    low_stock: bool


@dataclass(frozen=True)
class CategorySummaryRow:
    category: str
    resources: int
    total: int
    available: int
    issued: int
    unavailable: int
    low_stock: int


@dataclass(frozen=True)
class StoreStatus:
    rows: list[ResourceStatusRow]
    totals: dict[str, int]
    low_stock: list[ResourceStatusRow]
    generated_at: str


@dataclass(frozen=True)
class InventoryReport:
    rows: list[ResourceStatusRow]
    categories: list[CategorySummaryRow]
    totals: dict[str, int]
    generated_at: str


class ReportingService:
    def __init__(self, store: Store, taxonomy: TaxonomyService | None = None) -> None:
        self._store = store
        self._taxonomy = taxonomy or TaxonomyService(store)

    def _row(self, resource: Resource) -> ResourceStatusRow:
        counts = resource.condition_counts
        return ResourceStatusRow(
            resource_id=resource.id,
            name=resource.name,
            category=self._taxonomy.display_name(resource.category_id),
            subcategory=self._taxonomy.display_name(resource.subcategory_id),
            status=resource.status.value,
            total=resource.total_quantity,
            available=resource.available_quantity,
            issued=resource.issued_quantity,
            faulty=counts.get(Condition.FAULTY.value, 0),
            damaged=counts.get(Condition.DAMAGED.value, 0),
            missing=counts.get(Condition.MISSING.value, 0),
            retired=counts.get(Condition.RETIRED.value, 0),
            needed=resource.needed_quantity,
            low_stock=resource.is_low_stock,
        )

    @staticmethod
    def _totals(rows: list[ResourceStatusRow]) -> dict[str, int]:
        return {
            "resources": len(rows),
            "total": sum(row.total for row in rows),
            "available": sum(row.available for row in rows),
            "issued": sum(row.issued for row in rows),
            "faulty": sum(row.faulty for row in rows),
            "damaged": sum(row.damaged for row in rows),
            "missing": sum(row.missing for row in rows),
            "retired": sum(row.retired for row in rows),
            "unavailable": sum(
                row.faulty + row.damaged + row.missing + row.retired for row in rows
            ),
            "needed": sum(row.needed for row in rows),
        }

    def store_status(self, *, include_removed: bool = False) -> StoreStatus:
        resources = self._store.state.active_resources() if not include_removed else sorted(
            self._store.state.resources.values(), key=lambda r: r.id
        )
        rows = [self._row(resource) for resource in resources]
        return StoreStatus(
            rows=rows,
            totals=self._totals(rows),
            low_stock=[row for row in rows if row.low_stock],
            generated_at=now_iso(),
        )

    def inventory_report(
        self, *, category: str | None = None, include_removed: bool = False
    ) -> InventoryReport:
        resources = sorted(self._store.state.resources.values(), key=lambda r: r.id)
        if category:
            node = self._taxonomy.resolve_category(category)
            resources = [r for r in resources if r.category_id == node.id]
        if not include_removed:
            resources = [r for r in resources if r.is_active]

        rows = [self._row(resource) for resource in resources]
        by_category: dict[str, list[ResourceStatusRow]] = {}
        for row in rows:
            by_category.setdefault(row.category, []).append(row)

        summaries = [
            CategorySummaryRow(
                category=name,
                resources=len(group),
                total=sum(row.total for row in group),
                available=sum(row.available for row in group),
                issued=sum(row.issued for row in group),
                unavailable=sum(
                    row.faulty + row.damaged + row.missing + row.retired for row in group
                ),
                low_stock=sum(1 for row in group if row.low_stock),
            )
            for name, group in sorted(by_category.items())
        ]
        return InventoryReport(
            rows=rows,
            categories=summaries,
            totals=self._totals(rows),
            generated_at=now_iso(),
        )

    def low_stock(self, *, include_removed: bool = False) -> list[ResourceStatusRow]:
        return [
            row
            for row in self.store_status(include_removed=include_removed).rows
            if row.low_stock
        ]

    def most_borrowed(self, *, at: datetime | None = None) -> list[dict[str, int | str]]:
        borrowed: dict[str, int] = {}
        for loan in self._store.state.loans.values():
            if loan.is_returned:
                continue
            borrowed[loan.resource_id] = (
                borrowed.get(loan.resource_id, 0) + loan.outstanding_quantity
            )
        if not borrowed:
            return []
        highest = max(borrowed.values())
        leaders = [
            {
                "resource_id": resource_id,
                "name": self._store.state.resources[resource_id].name,
                "borrowed": quantity,
            }
            for resource_id, quantity in borrowed.items()
            if quantity == highest
        ]
        leaders.sort(key=lambda row: str(row["resource_id"]))
        return leaders
