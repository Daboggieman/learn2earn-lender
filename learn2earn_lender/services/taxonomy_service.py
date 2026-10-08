from __future__ import annotations

from ..domain.errors import ConflictError, NotFoundError, ValidationError
from ..domain.events import SYSTEM_ACTOR, EventType
from ..domain.taxonomy import TaxonomyNode, TaxonomyStatus, TaxonomyType
from ..storage.projections import State
from ..storage.store import Store
from ..validators.dates import now_iso
from ..validators.strings import normalise_name, slugify


class TaxonomyService:
    def __init__(self, store: Store) -> None:
        self._store = store

    @property
    def _state(self) -> State:
        return self._store.state

    def create_category(self, name: str, *, actor: str = SYSTEM_ACTOR) -> TaxonomyNode:
        clean = normalise_name(name, "category name")
        self._require_unique_name(clean, parent_id=None)

        node_id = self._unique_id(slugify(clean), self._state.taxonomy)
        moment = now_iso()
        node = TaxonomyNode(
            id=node_id,
            name=clean,
            type=TaxonomyType.CATEGORY,
            parent_id=None,
            status=TaxonomyStatus.ACTIVE,
            created_at=moment,
            updated_at=moment,
        )
        self._store.append(
            EventType.TAXONOMY_CREATED, {"node": node.to_dict()}, actor=actor
        )
        return self._state.taxonomy[node_id]

    def list_categories(self, *, include_removed: bool = False) -> list[TaxonomyNode]:
        nodes = self._state.categories()
        if not include_removed:
            nodes = [node for node in nodes if node.is_active]
        return nodes

    def rename_category(
        self, reference: str, new_name: str, *, actor: str = SYSTEM_ACTOR
    ) -> TaxonomyNode:
        node = self.resolve_category(reference)
        clean = normalise_name(new_name, "category name")
        self._require_unique_name(clean, parent_id=None, excluding=node.id)
        self._store.append(
            EventType.TAXONOMY_UPDATED,
            {"node_id": node.id, "changes": {"name": clean}},
            actor=actor,
        )
        return self._state.taxonomy[node.id]

    def remove_category(
        self, reference: str, *, actor: str = SYSTEM_ACTOR
    ) -> TaxonomyNode:
        node = self.resolve_category(reference)
        children = [child for child in self._state.subcategories(node.id) if child.is_active]
        if children:
            names = ", ".join(child.name for child in children)
            raise ConflictError(
                f"cannot remove category {node.name!r}: it still has "
                f"{len(children)} subcategory(ies) ({names}). Remove those first."
            )
        in_use = self._state.resources_in_category(node.id)
        if in_use:
            raise ConflictError(
                f"cannot remove category {node.name!r}: {len(in_use)} resource(s) "
                f"still reference it ({', '.join(r.id for r in in_use)}). "
                "Reassign or remove them first."
            )
        self._store.append(EventType.TAXONOMY_REMOVED, {"node_id": node.id}, actor=actor)
        return self._state.taxonomy[node.id]

    def create_subcategory(
        self, category: str, name: str, *, actor: str = SYSTEM_ACTOR
    ) -> TaxonomyNode:
        parent = self.resolve_category(category)
        if not parent.is_active:
            raise ValidationError(
                f"cannot add a subcategory to removed category {parent.name!r}"
            )
        clean = normalise_name(name, "subcategory name")
        self._require_unique_name(clean, parent_id=parent.id)

        node_id = self._unique_id(f"{parent.id}-{slugify(clean)}", self._state.taxonomy)
        moment = now_iso()
        node = TaxonomyNode(
            id=node_id,
            name=clean,
            type=TaxonomyType.SUBCATEGORY,
            parent_id=parent.id,
            status=TaxonomyStatus.ACTIVE,
            created_at=moment,
            updated_at=moment,
        )
        self._store.append(
            EventType.TAXONOMY_CREATED, {"node": node.to_dict()}, actor=actor
        )
        return self._state.taxonomy[node_id]

    def list_subcategories(
        self, category: str | None = None, *, include_removed: bool = False
    ) -> list[TaxonomyNode]:
        parent_id = self.resolve_category(category).id if category else None
        nodes = self._state.subcategories(parent_id)
        if not include_removed:
            nodes = [node for node in nodes if node.is_active]
        return nodes

    def rename_subcategory(
        self, reference: str, new_name: str, *, actor: str = SYSTEM_ACTOR
    ) -> TaxonomyNode:
        node = self.resolve_subcategory(reference)
        clean = normalise_name(new_name, "subcategory name")
        self._require_unique_name(clean, parent_id=node.parent_id, excluding=node.id)
        self._store.append(
            EventType.TAXONOMY_UPDATED,
            {"node_id": node.id, "changes": {"name": clean}},
            actor=actor,
        )
        return self._state.taxonomy[node.id]

    def remove_subcategory(
        self, reference: str, *, actor: str = SYSTEM_ACTOR
    ) -> TaxonomyNode:
        node = self.resolve_subcategory(reference)
        in_use = self._state.resources_in_subcategory(node.id)
        if in_use:
            raise ConflictError(
                f"cannot remove subcategory {node.name!r}: {len(in_use)} resource(s) "
                f"still reference it ({', '.join(r.id for r in in_use)}). "
                "Reassign or remove them first."
            )
        self._store.append(EventType.TAXONOMY_REMOVED, {"node_id": node.id}, actor=actor)
        return self._state.taxonomy[node.id]

    def resolve_category(self, reference: str) -> TaxonomyNode:
        return self._resolve(reference, TaxonomyType.CATEGORY, parent_id=None)

    def resolve_subcategory(
        self, reference: str, category: str | None = None
    ) -> TaxonomyNode:
        parent_id = self.resolve_category(category).id if category else None
        return self._resolve(reference, TaxonomyType.SUBCATEGORY, parent_id=parent_id)

    def _resolve(
        self, reference: str, node_type: TaxonomyType, parent_id: str | None
    ) -> TaxonomyNode:
        text = normalise_name(reference, f"{node_type.value} reference")

        node = self._state.taxonomy.get(text)
        if node is not None and node.type is node_type:
            return node

        lowered = text.lower()
        candidates = [
            candidate
            for candidate in self._state.taxonomy.values()
            if candidate.type is node_type and candidate.name.lower() == lowered
        ]
        if parent_id is not None:
            candidates = [c for c in candidates if c.parent_id == parent_id]

        if not candidates:
            available = ", ".join(
                sorted(
                    candidate.name
                    for candidate in self._state.taxonomy.values()
                    if candidate.type is node_type
                )
            )
            raise NotFoundError(
                f"no {node_type.value} matching {reference!r}. "
                f"Known: {available or '(none)'}"
            )
        if len(candidates) > 1:
            parents = ", ".join(sorted(str(c.parent_id) for c in candidates))
            raise ConflictError(
                f"{node_type.value} name {reference!r} is ambiguous "
                f"(matches {len(candidates)}: {parents}). Use the ID instead."
            )
        return candidates[0]

    def display_name(self, node_id: str | None) -> str:
        if not node_id:
            return "—"
        node = self._state.taxonomy.get(node_id)
        return node.name if node else f"({node_id})"

    def _require_unique_name(
        self, name: str, *, parent_id: str | None, excluding: str | None = None
    ) -> None:
        lowered = name.lower()
        for node in self._state.taxonomy.values():
            if node.id == excluding or not node.is_active:
                continue
            if parent_id is None:
                same_scope = node.is_category
            else:
                same_scope = node.is_subcategory and node.parent_id == parent_id
            if same_scope and node.name.lower() == lowered:
                raise ConflictError(
                    f"a {'category' if parent_id is None else 'subcategory'} "
                    f"named {name!r} already exists ({node.id})"
                )

    @staticmethod
    def _unique_id(base: str, existing: dict[str, object]) -> str:
        if base not in existing:
            return base
        suffix = 2
        while f"{base}-{suffix}" in existing:
            suffix += 1
        return f"{base}-{suffix}"
