from __future__ import annotations

from ..domain.equipment import Condition, Resource, ResourceStatus
from ..domain.errors import ConflictError, NotFoundError, ValidationError
from ..domain.events import SYSTEM_ACTOR, EventType
from ..storage.projections import State
from ..storage.store import Store
from ..validators.dates import now_iso
from ..validators.ids import next_sequential_id, validate_id
from ..validators.quantities import require_non_negative, require_positive
from ..validators.strings import normalise_name
from .taxonomy_service import TaxonomyService


class InventoryService:
    def __init__(self, store: Store, taxonomy: TaxonomyService | None = None) -> None:
        self._store = store
        self._taxonomy = taxonomy or TaxonomyService(store)

    @property
    def _state(self) -> State:
        return self._store.state

    def add_resource(
        self,
        *,
        name: str,
        category: str,
        subcategory: str,
        total_quantity: int,
        needed_quantity: int = 0,
        notes: str = "",
        resource_id: str | None = None,
        actor: str = SYSTEM_ACTOR,
    ) -> Resource:
        clean_name = normalise_name(name, "resource name")
        total = require_positive(total_quantity, "total_quantity")
        needed = require_non_negative(needed_quantity, "needed_quantity")
        cat, sub = self._resolve_pair(category, subcategory)

        if resource_id:
            identifier = validate_id(resource_id, "resource id")
            if identifier in self._state.resources:
                raise ConflictError(f"resource {identifier} already exists")
        else:
            identifier = next_sequential_id("R", list(self._state.resources))

        moment = now_iso()
        resource = Resource(
            id=identifier,
            name=clean_name,
            category_id=cat.id,
            subcategory_id=sub.id,
            total_quantity=total,
            available_quantity=total,
            issued_quantity=0,
            needed_quantity=needed,
            status=ResourceStatus.ACTIVE,
            created_at=moment,
            updated_at=moment,
            notes=notes.strip(),
        )
        resource.check_invariant()
        self._store.append(
            EventType.RESOURCE_CREATED, {"resource": resource.to_dict()}, actor=actor
        )
        return self._state.resources[identifier]

    def update_resource(
        self,
        resource_id: str,
        *,
        name: str | None = None,
        category: str | None = None,
        subcategory: str | None = None,
        total_quantity: int | None = None,
        needed_quantity: int | None = None,
        notes: str | None = None,
        actor: str = SYSTEM_ACTOR,
    ) -> Resource:
        resource = self.get_resource(resource_id)
        resource.require_active("update")

        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = normalise_name(name, "resource name")
        if notes is not None:
            changes["notes"] = notes.strip()
        if needed_quantity is not None:
            changes["needed_quantity"] = require_non_negative(
                needed_quantity, "needed_quantity"
            )
        if total_quantity is not None:
            changes["total_quantity"] = require_positive(
                total_quantity, "total_quantity"
            )

        if category is not None or subcategory is not None:
            current_sub = self._state.taxonomy_or_raise(resource.subcategory_id)
            category_ref = category if category is not None else current_sub.parent_id
            subcategory_ref = subcategory if subcategory is not None else resource.subcategory_id
            cat, sub = self._resolve_pair(str(category_ref), str(subcategory_ref))
            changes["category_id"] = cat.id
            changes["subcategory_id"] = sub.id

        if not changes:
            return resource

        self._store.append(
            EventType.RESOURCE_UPDATED,
            {"resource_id": resource.id, "changes": changes},
            actor=actor,
        )
        return self._state.resources[resource.id]

    def remove_resource(
        self, resource_id: str, *, reason: str = "", actor: str = SYSTEM_ACTOR
    ) -> Resource:
        resource = self.get_resource(resource_id)
        resource.require_active("remove")
        if resource.issued_quantity:
            raise ConflictError(
                f"cannot remove resource {resource.id}: "
                f"{resource.issued_quantity} unit(s) are still on loan. "
                "Return them first."
            )
        self._store.append(
            EventType.RESOURCE_REMOVED,
            {"resource_id": resource.id, "reason": reason.strip()},
            actor=actor,
        )
        return self._state.resources[resource.id]

    def restore_resource(self, resource_id: str, *, actor: str = SYSTEM_ACTOR) -> Resource:
        resource = self.get_resource(resource_id)
        if resource.is_active:
            raise ConflictError(f"resource {resource.id} is already active")
        self._store.append(
            EventType.RESOURCE_UPDATED,
            {"resource_id": resource.id, "changes": {"status": ResourceStatus.ACTIVE.value}},
            actor=actor,
        )
        return self._state.resources[resource.id]

    def mark_condition(
        self,
        resource_id: str,
        condition: str | Condition,
        quantity: int,
        *,
        restore_from: str | Condition | None = None,
        reason: str = "",
        actor: str = SYSTEM_ACTOR,
    ) -> Resource:
        resource = self.get_resource(resource_id)
        resource.require_active("modify")
        target = Condition.parse(condition)
        amount = require_positive(quantity, "quantity")

        if target is Condition.GOOD:
            if restore_from is None:
                raise ValidationError(
                    "restoring units to good requires --from (faulty, damaged, "
                    "missing or retired)"
                )
            source = Condition.parse(restore_from)
            if source is Condition.GOOD:
                raise ValidationError("--from must name a condition other than good")
        else:
            source = Condition.GOOD

        self._store.append(
            EventType.RESOURCE_CONDITION_CHANGED,
            {
                "resource_id": resource.id,
                "from": source.value,
                "to": target.value,
                "quantity": amount,
                "reason": reason.strip(),
            },
            actor=actor,
        )
        return self._state.resources[resource.id]

    def get_resource(self, reference: str, *, include_removed: bool = True) -> Resource:
        text = validate_id(reference, "resource reference")
        resource = self._state.resources.get(text)
        if resource is None:
            raise NotFoundError(f"no resource with ID {reference!r}")
        if not include_removed and not resource.is_active:
            raise NotFoundError(f"resource {resource.id} has been removed")
        return resource

    def search_resources(
        self, term: str, *, include_removed: bool = False, limit: int | None = None
    ) -> list[Resource]:
        text = normalise_name(term, "search term").lower()
        matches = [
            resource
            for resource in self._state.resources.values()
            if (include_removed or resource.is_active)
            and (
                resource.id.lower() == text
                or resource.name.lower() == text
                or text in resource.name.lower()
            )
        ]
        matches.sort(key=lambda r: (r.name.lower() != text, r.id))
        return matches[:limit] if limit else matches

    def find_by_category(
        self, category: str, *, include_removed: bool = False
    ) -> list[Resource]:
        node = self._taxonomy.resolve_category(category)
        matches = self._state.resources_in_category(node.id)
        if not include_removed:
            matches = [r for r in matches if r.is_active]
        return matches

    def find_by_subcategory(
        self, subcategory: str, *, category: str | None = None, include_removed: bool = False
    ) -> list[Resource]:
        node = self._taxonomy.resolve_subcategory(subcategory, category)
        matches = self._state.resources_in_subcategory(node.id)
        if not include_removed:
            matches = [r for r in matches if r.is_active]
        return matches

    def list_resources(
        self,
        *,
        category: str | None = None,
        subcategory: str | None = None,
        include_removed: bool = False,
    ) -> list[Resource]:
        if subcategory:
            return self.find_by_subcategory(
                subcategory, category=category, include_removed=include_removed
            )
        if category:
            return self.find_by_category(category, include_removed=include_removed)
        resources = sorted(self._state.resources.values(), key=lambda r: r.id)
        if not include_removed:
            resources = [r for r in resources if r.is_active]
        return resources

    def _resolve_pair(self, category: str, subcategory: str):
        cat = self._taxonomy.resolve_category(category)
        if not cat.is_active:
            raise ValidationError(f"category {cat.name!r} has been removed")
        sub = self._taxonomy.resolve_subcategory(subcategory, cat.id)
        if not sub.is_active:
            raise ValidationError(f"subcategory {sub.name!r} has been removed")
        if sub.parent_id != cat.id:
            raise ValidationError(
                f"subcategory {sub.name!r} does not belong to category {cat.name!r}"
            )
        return cat, sub
