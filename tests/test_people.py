from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lender.domain.errors import ConflictError, NotFoundError, ValidationError
from lender.domain.people import PersonStatus
from lender.services.people_service import PeopleService
from lender.storage.store import Store


class PeopleTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store.open(Path(self._tmp.name))
        self.people = PeopleService(self.store)


class GroupTests(PeopleTestCase):
    def test_add_cohort_and_trial_get_sequential_ids(self):
        self.assertEqual(self.people.add_cohort("cluster-1-feb").id, "G001")
        self.assertEqual(self.people.add_trial("trial-period-1").id, "G002")

    def test_group_keeps_its_declared_type(self):
        cohort = self.people.add_cohort("cluster-1-feb")
        trial = self.people.add_trial("trial-period-1")
        self.assertTrue(cohort.is_cohort)
        self.assertTrue(trial.is_trial)

    def test_duplicate_group_name_is_rejected(self):
        self.people.add_cohort("cluster-1-feb")
        with self.assertRaises(ConflictError):
            self.people.add_trial("Cluster-1-Feb")

    def test_blank_group_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.people.add_cohort("   ")

    def test_unknown_group_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.people.create_group("x", "semester")

    def test_list_groups_filters_by_type(self):
        self.people.add_cohort("cluster-1-feb")
        self.people.add_cohort("cluster-2-feb")
        self.people.add_trial("trial-period-1")
        self.assertEqual(len(self.people.list_groups()), 3)
        self.assertEqual(len(self.people.list_groups("cohort")), 2)
        self.assertEqual(len(self.people.list_groups("trial")), 1)

    def test_resolve_group_by_name_is_case_insensitive(self):
        group = self.people.add_cohort("cluster-1-feb")
        self.assertEqual(self.people.resolve_group("CLUSTER-1-FEB").id, group.id)
        self.assertEqual(self.people.resolve_group(group.id).id, group.id)

    def test_resolve_group_reports_unknown_names(self):
        self.people.add_cohort("cluster-1-feb")
        with self.assertRaises(NotFoundError) as caught:
            self.people.resolve_group("ghost")
        self.assertIn("cluster-1-feb", str(caught.exception))

    def test_resolve_group_enforces_the_expected_type(self):
        self.people.add_cohort("cluster-1-feb")
        with self.assertRaises(NotFoundError):
            self.people.resolve_group("cluster-1-feb", "trial")

    def test_rename_group_keeps_the_id(self):
        group = self.people.add_cohort("cluster-1-feb")
        renamed = self.people.rename_group("cluster-1-feb", "cluster-1-march")
        self.assertEqual(renamed.id, group.id)
        self.assertEqual(renamed.name, "cluster-1-march")

    def test_rename_onto_an_existing_name_is_rejected(self):
        self.people.add_cohort("cluster-1-feb")
        self.people.add_cohort("cluster-2-feb")
        with self.assertRaises(ConflictError):
            self.people.rename_group("cluster-2-feb", "cluster-1-feb")

    def test_archiving_an_empty_group_works(self):
        self.people.add_cohort("cluster-1-feb")
        archived = self.people.archive_group("cluster-1-feb")
        self.assertFalse(archived.is_active)
        self.assertEqual(self.people.list_groups(), [])
        self.assertEqual(len(self.people.list_groups(include_removed=True)), 1)

    def test_archiving_a_group_with_members_is_refused(self):
        self.people.add_cohort("cluster-1-feb")
        self.people.add_fellow("Ada", "cluster-1-feb")
        with self.assertRaises(ConflictError):
            self.people.archive_group("cluster-1-feb")


class PersonCreationTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.cohort = self.people.add_cohort("cluster-1-feb")
        self.trial = self.people.add_trial("trial-period-1")

    def test_fellows_get_f_prefixed_ids(self):
        self.assertEqual(self.people.add_fellow("Ada", "cluster-1-feb").id, "F001")
        self.assertEqual(self.people.add_fellow("John", "cluster-1-feb").id, "F002")

    def test_piscine_candidates_get_p_prefixed_ids(self):
        self.assertEqual(self.people.add_piscine("Ada", "trial-period-1").id, "P001")
        self.assertEqual(self.people.add_piscine("John", "trial-period-1").id, "P002")

    def test_fellow_and_piscine_id_sequences_are_independent(self):
        self.people.add_fellow("Ada", "cluster-1-feb")
        self.assertEqual(self.people.add_piscine("John", "trial-period-1").id, "P001")

    def test_new_person_starts_active_and_can_borrow(self):
        person = self.people.add_fellow("Ada", "cluster-1-feb")
        self.assertTrue(person.can_borrow)
        self.assertTrue(person.is_fellow)

    def test_fellow_is_linked_to_the_resolved_cohort(self):
        person = self.people.add_fellow("Ada", "CLUSTER-1-FEB")
        self.assertEqual(person.group_id, self.cohort.id)

    def test_fellow_cannot_be_placed_in_a_trial_group(self):
        with self.assertRaises(NotFoundError):
            self.people.add_fellow("Ada", "trial-period-1")

    def test_piscine_cannot_be_placed_in_a_cohort(self):
        with self.assertRaises(NotFoundError):
            self.people.add_piscine("Ada", "cluster-1-feb")

    def test_duplicate_borrower_name_is_rejected(self):
        self.people.add_fellow("Ada Lovelace", "cluster-1-feb")
        with self.assertRaises(ConflictError):
            self.people.add_fellow("ada lovelace", "cluster-1-feb")

    def test_same_name_in_a_different_group_is_still_duplicate(self):
        self.people.add_cohort("cluster-2-feb")
        self.people.add_fellow("Ada Lovelace", "cluster-1-feb")
        with self.assertRaises(ConflictError):
            self.people.add_fellow("Ada Lovelace", "cluster-2-feb")

    def test_explicit_id_is_accepted_when_the_prefix_matches(self):
        person = self.people.add_fellow("Ada", "cluster-1-feb", person_id="F900")
        self.assertEqual(person.id, "F900")
        self.assertEqual(self.people.add_fellow("John", "cluster-1-feb").id, "F901")

    def test_explicit_id_with_the_wrong_prefix_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.people.add_fellow("Ada", "cluster-1-feb", person_id="P900")

    def test_duplicate_explicit_id_is_rejected(self):
        self.people.add_fellow("Ada", "cluster-1-feb", person_id="F900")
        with self.assertRaises(ConflictError):
            self.people.add_fellow("John", "cluster-1-feb", person_id="F900")

    def test_unknown_group_is_reported(self):
        with self.assertRaises(NotFoundError):
            self.people.add_fellow("Ada", "ghost-cohort")

    def test_unknown_person_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.people.add_person("Ada", "visitor", "cluster-1-feb")


class PersonQueryTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.people.add_cohort("cluster-1-feb")
        self.people.add_cohort("cluster-2-feb")
        self.people.add_trial("trial-period-1")
        self.ada = self.people.add_fellow("Ada Lovelace", "cluster-1-feb")
        self.john = self.people.add_fellow("John Mensah", "cluster-2-feb")
        self.grace = self.people.add_piscine("Grace Hopper", "trial-period-1")

    def test_list_borrowers_returns_everyone_by_id_order(self):
        self.assertEqual(
            [p.id for p in self.people.list_borrowers()],
            [self.ada.id, self.john.id, self.grace.id],
        )

    def test_list_borrowers_filters_by_group(self):
        people = self.people.list_borrowers(group="cluster-1-feb")
        self.assertEqual([p.id for p in people], [self.ada.id])

    def test_list_borrowers_filters_by_type(self):
        self.assertEqual(
            [p.id for p in self.people.list_borrowers(person_type="piscine")],
            [self.grace.id],
        )

    def test_list_borrowers_combines_both_filters(self):
        self.assertEqual(
            self.people.list_borrowers(group="cluster-1-feb", person_type="piscine"),
            [],
        )

    def test_search_matches_id_and_partial_name(self):
        self.assertEqual([p.id for p in self.people.search_borrowers("F001")], [self.ada.id])
        self.assertEqual([p.id for p in self.people.search_borrowers("lovelace")], [self.ada.id])
        self.assertEqual(len(self.people.search_borrowers("a")), 3)

    def test_search_prefers_exact_name_matches(self):
        self.people.add_fellow("Ada", "cluster-1-feb")
        self.assertEqual(self.people.search_borrowers("ada")[0].name, "Ada")

    def test_find_borrower_resolves_an_exact_name(self):
        self.assertEqual(
            self.people.find_borrower("John Mensah").id, self.john.id
        )

    def test_find_borrower_rejects_an_ambiguous_term(self):
        with self.assertRaises(ConflictError):
            self.people.find_borrower("a")

    def test_find_borrower_reports_misses(self):
        with self.assertRaises(NotFoundError):
            self.people.find_borrower("nobody")

    def test_get_person_reports_unknown_ids(self):
        with self.assertRaises(NotFoundError):
            self.people.get_person("F404")

    def test_group_name_falls_back_for_unknown_ids(self):
        self.assertEqual(self.people.group_name(self.ada.group_id), "cluster-1-feb")
        self.assertEqual(self.people.group_name("ghost"), "(ghost)")
        self.assertEqual(self.people.group_name(None), "—")


class PersonUpdateTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.people.add_cohort("cluster-1-feb")
        self.people.add_cohort("cluster-2-feb")
        self.people.add_trial("trial-period-1")
        self.ada = self.people.add_fellow("Ada Lovelace", "cluster-1-feb")

    def test_rename_updates_the_record(self):
        updated = self.people.update_person("F001", name="Ada King")
        self.assertEqual(updated.name, "Ada King")

    def test_rename_onto_another_borrower_is_rejected(self):
        self.people.add_fellow("John Mensah", "cluster-1-feb")
        with self.assertRaises(ConflictError):
            self.people.update_person("F001", name="John Mensah")

    def test_moving_a_fellow_to_another_cohort(self):
        target = self.people.resolve_group("cluster-2-feb")
        updated = self.people.update_person("F001", group="cluster-2-feb")
        self.assertEqual(updated.group_id, target.id)

    def test_moving_a_fellow_to_a_trial_group_is_rejected(self):
        with self.assertRaises(NotFoundError):
            self.people.update_person("F001", group="trial-period-1")

    def test_status_can_be_deactivated(self):
        updated = self.people.update_person("F001", status="inactive")
        self.assertFalse(updated.can_borrow)
        with self.assertRaises(ValidationError):
            updated.require_can_borrow()

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.people.update_person("F001", status="graduated")

    def test_removed_borrowers_drop_out_of_listings(self):
        self.people.update_person("F001", status="removed")
        self.assertEqual(self.people.list_borrowers(), [])
        self.assertEqual(len(self.people.list_borrowers(include_removed=True)), 1)

    def test_an_update_with_no_changes_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.people.update_person("F001")

    def test_updating_an_unknown_borrower_is_reported(self):
        with self.assertRaises(NotFoundError):
            self.people.update_person("F404", name="Nobody")


class GroupMemberCountTests(PeopleTestCase):
    def test_members_are_counted_per_group(self):
        self.people.add_cohort("cluster-1-feb")
        self.people.add_cohort("cluster-2-feb")
        self.people.add_fellow("Ada", "cluster-1-feb")
        self.people.add_fellow("John", "cluster-1-feb")
        self.people.add_fellow("Grace", "cluster-2-feb")
        counts = {
            group.id: len(self.store.state.people_in_group(group.id))
            for group in self.people.list_groups()
        }
        self.assertEqual(list(counts.values()), [2, 1])

    def test_archived_groups_are_excluded_from_the_default_listing(self):
        self.people.add_cohort("cluster-1-feb")
        self.people.archive_group("cluster-1-feb")
        self.assertEqual(self.people.list_groups(), [])
        self.assertEqual(self.people.list_groups("cohort"), [])
        self.assertEqual(len(self.people.list_groups("cohort", include_removed=True)), 1)


if __name__ == "__main__":
    unittest.main()
