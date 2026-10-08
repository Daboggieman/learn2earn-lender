from __future__ import annotations

from dataclasses import dataclass

from ..services.inventory_service import InventoryService
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
    reporting: ReportingService

    @classmethod
    def build(cls, store: Store, *, actor: str, as_json: bool) -> "Context":
        taxonomy = TaxonomyService(store)
        inventory = InventoryService(store, taxonomy)
        return cls(
            store=store,
            actor=actor,
            as_json=as_json,
            taxonomy=taxonomy,
            inventory=inventory,
            reporting=ReportingService(store, taxonomy),
        )
