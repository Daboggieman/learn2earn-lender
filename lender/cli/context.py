from __future__ import annotations

from dataclasses import dataclass

from ..services.inventory_service import InventoryService
from ..services.lending_service import LendingService
from ..services.people_service import PeopleService
from ..services.reporting_service import ReportingService
from ..services.taxonomy_service import TaxonomyService
from ..storage.store import Store


@dataclass
class Context:
    store: Store
    actor: str
    as_json: bool
    taxonomy: TaxonomyService
    inventory: InventoryService
    people: PeopleService
    lending: LendingService
    reporting: ReportingService

    @classmethod
    def build(cls, store: Store, *, actor: str, as_json: bool) -> "Context":
        taxonomy = TaxonomyService(store)
        return cls(
            store=store,
            actor=actor,
            as_json=as_json,
            taxonomy=taxonomy,
            inventory=InventoryService(store, taxonomy),
            people=PeopleService(store),
            lending=LendingService(store),
            reporting=ReportingService(store, taxonomy),
        )
