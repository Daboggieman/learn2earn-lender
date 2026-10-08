from __future__ import annotations

from ..domain.errors import ConflictError, NotFoundError, ValidationError
from ..domain.events import SYSTEM_ACTOR, EventType
from ..domain.groups import Group, GroupStatus, GroupType, make_group_id
from ..domain.people import Person, PersonStatus, PersonType, make_person_id
from ..storage.projections import State
from ..storage.store import Store
from ..validators.dates import now_iso
from ..validators.ids import validate_id
from ..validators.strings import normalise_name

REQUIRED_GROUP_TYPE = {
    PersonType.FELLOW: GroupType.COHORT,
    PersonType.PISCINE: GroupType.TRIAL,
}


class PeopleService:
    def __init__(self, store: Store) -> None:
        self._store = store

    @property
    def _state(self) -> State:
        return self._store.state

    def create_group(
        self,
        name: str,
        group_type: str | GroupType,
        *,
        actor: str = SYSTEM_ACTOR,
    ) -> Group:
        kind = GroupType.parse(group_type)
        clean = normalise_name(name, "group name")
        self._require_unique_group_name(clean)

        moment = now_iso()
        group = Group(
            id=self._next_group_id(),
            name=clean,
            type=kind,
            status=GroupStatus.ACTIVE,
            created_at=moment,
            updated_at=moment,
        )
        self._store.append(
            EventType.GROUP_CREATED, {"group": group.to_dict()}, actor=actor
        )
        return self._state.groups[group.id]

    def add_cohort(self, name: str, *, actor: str = SYSTEM_ACTOR) -> Group:
        return self.create_group(name, GroupType.COHORT, actor=actor)

    def add_trial(self, name: str, *, actor: str = SYSTEM_ACTOR) -> Group:
        return self.create_group(name, GroupType.TRIAL, actor=actor)

    def list_groups(
        self,
        group_type: str | GroupType | None = None,
        *,
        include_removed: bool = False,
    ) -> list[Group]:
        kind = GroupType.parse(group_type) if group_type is not None else None
        groups = sorted(self._state.groups.values(), key=lambda group: group.id)
        if kind is not None:
            groups = [group for group in groups if group.type is kind]
        if not include_removed:
            groups = [group for group in groups if group.is_active]
        return groups

    def rename_group(
        self, reference: str, new_name: str, *, actor: str = SYSTEM_ACTOR
    ) -> Group:
        group = self.resolve_group(reference)
        clean = normalise_name(new_name, "group name")
        self._require_unique_group_name(clean, excluding=group.id)
        self._store.append(
            EventType.GROUP_UPDATED,
            {"group_id": group.id, "changes": {"name": clean}},
            actor=actor,
        )
        return self._state.groups[group.id]

    def archive_group(self, reference: str, *, actor: str = SYSTEM_ACTOR) -> Group:
        group = self.resolve_group(reference)
        if not group.is_active:
            raise ConflictError(f"group {group.id} is already {group.status.value}")
        members = self._state.people_in_group(group.id)
        if members:
            raise ConflictError(
                f"cannot archive group {group.name!r}: "
                f"{len(members)} borrower(s) still belong to it. "
                "Move them to another group first."
            )
        self._store.append(
            EventType.GROUP_UPDATED,
            {"group_id": group.id, "changes": {"status": GroupStatus.ARCHIVED.value}},
            actor=actor,
        )
        return self._state.groups[group.id]

    def add_fellow(
        self,
        name: str,
        cohort: str,
        *,
        person_id: str | None = None,
        notes: str = "",
        actor: str = SYSTEM_ACTOR,
    ) -> Person:
        return self.add_person(
            name,
            PersonType.FELLOW,
            cohort,
            person_id=person_id,
            notes=notes,
            actor=actor,
        )

    def add_piscine(
        self,
        name: str,
        trial: str,
        *,
        person_id: str | None = None,
        notes: str = "",
        actor: str = SYSTEM_ACTOR,
    ) -> Person:
        return self.add_person(
            name,
            PersonType.PISCINE,
            trial,
            person_id=person_id,
            notes=notes,
            actor=actor,
        )

    def add_person(
        self,
        name: str,
        person_type: str | PersonType,
        group: str,
        *,
        person_id: str | None = None,
        notes: str = "",
        actor: str = SYSTEM_ACTOR,
    ) -> Person:
        kind = PersonType.parse(person_type)
        clean = normalise_name(name, "borrower name")
        self._require_unique_person_name(clean)

        expected = REQUIRED_GROUP_TYPE[kind]
        parent = self.resolve_group(group, expected)

        if person_id:
            identifier = self._validate_person_id(person_id, kind)
            if identifier in self._state.people:
                raise ConflictError(f"borrower {identifier} already exists")
        else:
            identifier = make_person_id(list(self._state.people), kind)

        moment = now_iso()
        person = Person(
            id=identifier,
            name=clean,
            type=kind,
            group_id=parent.id,
            status=PersonStatus.ACTIVE,
            created_at=moment,
            updated_at=moment,
            notes=notes.strip(),
        )
        self._store.append(
            EventType.PERSON_CREATED, {"person": person.to_dict()}, actor=actor
        )
        return self._state.people[identifier]

    def update_person(
        self,
        reference: str,
        *,
        name: str | None = None,
        group: str | None = None,
        status: str | PersonStatus | None = None,
        notes: str | None = None,
        actor: str = SYSTEM_ACTOR,
    ) -> Person:
        person = self.get_person(reference)
        changes: dict[str, object] = {}

        if name is not None:
            clean = normalise_name(name, "borrower name")
            self._require_unique_person_name(clean, excluding=person.id)
            changes["name"] = clean
        if notes is not None:
            changes["notes"] = notes.strip()
        if group is not None:
            parent = self.resolve_group(group, REQUIRED_GROUP_TYPE[person.type])
            changes["group_id"] = parent.id
        if status is not None:
            changes["status"] = PersonStatus.parse(status).value

        if not changes:
            raise ValidationError("no changes supplied for borrower " + person.id)

        self._store.append(
            EventType.PERSON_UPDATED,
            {"person_id": person.id, "changes": changes},
            actor=actor,
        )
        return self._state.people[person.id]

    def get_person(self, reference: str) -> Person:
        text = normalise_name(reference, "borrower reference")
        person = self._state.people.get(text)
        if person is None:
            raise NotFoundError(f"no borrower with ID {reference!r}")
        return person

    def search_borrowers(
        self, term: str, *, include_removed: bool = False
    ) -> list[Person]:
        text = normalise_name(term, "search term").lower()
        matches = [
            person
            for person in self._state.people.values()
            if (include_removed or person.status is not PersonStatus.REMOVED)
            and (
                person.id.lower() == text
                or person.name.lower() == text
                or text in person.name.lower()
            )
        ]
        matches.sort(key=lambda person: (person.name.lower() != text, person.id))
        return matches

    def find_borrower(self, term: str, *, include_removed: bool = False) -> Person:
        matches = self.search_borrowers(term, include_removed=include_removed)
        if not matches:
            raise NotFoundError(f"no borrower matches {term!r}")
        exact = [
            person
            for person in matches
            if person.id.lower() == term.lower() or person.name.lower() == term.lower()
        ]
        if len(exact) == 1:
            return exact[0]
        if len(matches) > 1:
            raise ConflictError(
                f"borrower {term!r} is ambiguous "
                f"(matches {len(matches)}: {', '.join(p.id for p in matches[:5])}). "
                "Use the ID instead."
            )
        return matches[0]

    def list_borrowers(
        self,
        *,
        group: str | None = None,
        person_type: str | PersonType | None = None,
        include_removed: bool = False,
    ) -> list[Person]:
        people = list(self._state.people.values())
        if group is not None:
            parent = self.resolve_group(group)
            people = [person for person in people if person.group_id == parent.id]
        if person_type is not None:
            kind = PersonType.parse(person_type)
            people = [person for person in people if person.type is kind]
        if not include_removed:
            people = [person for person in people if person.status is not PersonStatus.REMOVED]
        return sorted(people, key=lambda person: person.id)

    def resolve_group(
        self, reference: str, group_type: str | GroupType | None = None
    ) -> Group:
        text = normalise_name(reference, "group reference")
        kind = GroupType.parse(group_type) if group_type is not None else None

        group = self._state.groups.get(text)
        if group is not None and (kind is None or group.type is kind):
            return group

        lowered = text.lower()
        candidates = [
            candidate
            for candidate in self._state.groups.values()
            if candidate.name.lower() == lowered
            and (kind is None or candidate.type is kind)
        ]
        if not candidates:
            known = ", ".join(
                sorted(
                    candidate.name
                    for candidate in self._state.groups.values()
                    if kind is None or candidate.type is kind
                )
            )
            label = kind.value if kind else "group"
            raise NotFoundError(
                f"no {label} matching {reference!r}. Known: {known or '(none)'}"
            )
        if len(candidates) > 1:
            raise ConflictError(
                f"group name {reference!r} is ambiguous "
                f"(matches {len(candidates)}: {', '.join(c.id for c in candidates)}). "
                "Use the ID instead."
            )
        return candidates[0]

    def group_name(self, group_id: str | None) -> str:
        if not group_id:
            return "—"
        group = self._state.groups.get(group_id)
        return group.name if group else f"({group_id})"

    def _next_group_id(self) -> str:
        return make_group_id(list(self._state.groups))

    def _require_unique_group_name(
        self, name: str, *, excluding: str | None = None
    ) -> None:
        lowered = name.lower()
        for group in self._state.groups.values():
            if group.id == excluding or not group.is_active:
                continue
            if group.name.lower() == lowered:
                raise ConflictError(
                    f"a group named {name!r} already exists ({group.id})"
                )

    def _require_unique_person_name(
        self, name: str, *, excluding: str | None = None
    ) -> None:
        lowered = name.lower()
        for person in self._state.people.values():
            if person.id == excluding or person.status is PersonStatus.REMOVED:
                continue
            if person.name.lower() == lowered:
                raise ConflictError(
                    f"a borrower named {name!r} already exists ({person.id})"
                )

    @staticmethod
    def _validate_person_id(person_id: str, person_type: PersonType) -> str:
        identifier = validate_id(person_id, "borrower id")
        prefix = "F" if person_type is PersonType.FELLOW else "P"
        if not identifier.startswith(prefix):
            raise ValidationError(
                f"borrower id {identifier!r} must start with {prefix!r} "
                f"for a {person_type.value}"
            )
        return identifier
