from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lender.domain.equipment import Condition
from lender.domain.errors import ConflictError, NotFoundError, ValidationError
from lender.domain.events import EventType
from lender.domain.transactions import checkout_payload
from lender.services.inventory_service import InventoryService
from lender.services.taxonomy_service import TaxonomyService
from lender.storage.store import Store


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store.open(Path(self._tmp.name))
        self.taxonomy = TaxonomyService(self.store)
        self.inventory = InventoryService(self.store, self.taxonomy)

    def seed_taxonomy(self):
        self.taxonomy.create_category("Electronics")
        self.taxonomy.create_category("Accessories")
        self.taxonomy.create_subcategory("Electronics", "laptop")
        self.taxonomy.create_subcategory("Accessories", "keyboard")

    def seed_resource(self, name="Laptop", category="Electronics", subcategory="laptop", total=10):
        return self.inventory.add_resource(
            name=name, category=category, subcategory=subcategory, total_quantity=total
        )


class TaxonomyServiceTests(ServiceTestCase):
    def test_create_category_derives_a_slug_id(self):
        node = self.taxonomy.create_category("  Computer Lab  ")
        self.assertEqual(node.id, "computer-lab")
        self.assertEqual(node.name, "Computer Lab")

    def test_duplicate_category_name_is_rejected(self):
        self.taxonomy.create_category("Electronics")
        with self.assertRaises(ConflictError):
            self.taxonomy.create_category("electronics")

    def test_same_id_from_different_names_gets_a_suffix(self):
        self.taxonomy.create_category("Lab")
        node = self.taxonomy.create_category("Lab!")
        self.assertEqual(node.id, "lab-2")

    def test_rename_keeps_the_id(self):
        node = self.taxonomy.create_category("Electronics")
        renamed = self.taxonomy.rename_category("Electronics", "Hardware")
        self.assertEqual(renamed.id, node.id)
        self.assertEqual(renamed.name, "Hardware")

    def test_rename_onto_an_existing_name_is_rejected(self):
        self.taxonomy.create_category("Electronics")
        self.taxonomy.create_category("Accessories")
        with self.assertRaises(ConflictError):
            self.taxonomy.rename_category("Accessories", "Electronics")

    def test_subcategory_is_parent_prefixed(self):
        self.seed_taxonomy()
        node = self.taxonomy.resolve_subcategory("laptop", "Electronics")
        self.assertEqual(node.id, "electronics-laptop")
        self.assertEqual(node.parent_id, "electronics")

    def test_subcategory_under_unknown_category_is_rejected(self):
        with self.assertRaises(NotFoundError):
            self.taxonomy.create_subcategory("Nope", "laptop")

    def test_duplicate_subcategory_in_same_category_is_rejected(self):
        self.seed_taxonomy()
        with self.assertRaises(ConflictError):
            self.taxonomy.create_subcategory("Electronics", "Laptop")

    def test_same_subcategory_name_under_two_categories_is_allowed(self):
        self.seed_taxonomy()
        node = self.taxonomy.create_subcategory("Accessories", "laptop")
        self.assertEqual(node.id, "accessories-laptop")
        self.assertEqual(node.parent_id, "accessories")

    def test_resolve_is_case_insensitive_and_accepts_ids(self):
        self.seed_taxonomy()
        self.assertEqual(self.taxonomy.resolve_category("electronics").id, "electronics")
        self.assertEqual(self.taxonomy.resolve_category("ELECTRONICS").id, "electronics")

    def test_ambiguous_subcategory_reference_is_rejected(self):
        self.seed_taxonomy()
        self.taxonomy.create_subcategory("Accessories", "laptop")
        with self.assertRaises(ConflictError):
            self.taxonomy.resolve_subcategory("laptop")
        self.assertEqual(
            self.taxonomy.resolve_subcategory("laptop", "Accessories").id,
            "accessories-laptop",
        )

    def test_removing_a_category_with_subcategories_is_refused(self):
        self.seed_taxonomy()
        with self.assertRaises(ConflictError):
            self.taxonomy.remove_category("Electronics")

    def test_removing_a_category_with_resources_is_refused(self):
        self.seed_taxonomy()
        self.seed_resource()
        with self.assertRaises(ConflictError):
            self.taxonomy.remove_category("Electronics")

    def test_removing_an_empty_category_succeeds_but_hides_it(self):
        node = self.taxonomy.create_category("Spare")
        self.taxonomy.remove_category(node.id)
        self.assertEqual(self.taxonomy.list_categories(), [])
        self.assertEqual(len(self.taxonomy.list_categories(include_removed=True)), 1)

    def test_removing_a_subcategory_in_use_is_refused(self):
        self.seed_taxonomy()
        self.seed_resource()
        with self.assertRaises(ConflictError):
            self.taxonomy.remove_subcategory("laptop")

    def test_display_name_falls_back_for_unknown_ids(self):
        self.assertEqual(self.taxonomy.display_name("ghost"), "(ghost)")
        self.assertEqual(self.taxonomy.display_name(None), "—")


class InventoryServiceTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.seed_taxonomy()

    def test_add_resource_starts_fully_available(self):
        resource = self.seed_resource(total=7)
        self.assertEqual(resource.id, "R001")
        self.assertEqual(resource.available_quantity, 7)
        self.assertEqual(resource.issued_quantity, 0)
        self.assertTrue(resource.is_active)

    def test_resource_ids_increment(self):
        self.assertEqual(self.seed_resource().id, "R001")
        self.assertEqual(self.seed_resource(name="Other").id, "R002")

    def test_explicit_id_can_be_supplied(self):
        resource = self.inventory.add_resource(
            name="Spare", category="Electronics", subcategory="laptop",
            total_quantity=2, resource_id="R999",
        )
        self.assertEqual(resource.id, "R999")

    def test_duplicate_explicit_id_is_rejected(self):
        self.seed_resource()
        with self.assertRaises(ConflictError):
            self.inventory.add_resource(
                name="Dup", category="Electronics", subcategory="laptop",
                total_quantity=1, resource_id="R001",
            )

    def test_zero_or_negative_total_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.seed_resource(total=0)

    def test_subcategory_from_the_wrong_category_is_rejected(self):
        with self.assertRaises(NotFoundError):
            self.seed_resource(category="Electronics", subcategory="keyboard")

    def test_unknown_taxonomy_is_rejected(self):
        with self.assertRaises(NotFoundError):
            self.seed_resource(category="Ghost", subcategory="laptop")

    def test_update_changes_name_and_total(self):
        self.seed_resource(total=5)
        updated = self.inventory.update_resource("R001", name="Workstation", total_quantity=9)
        self.assertEqual(updated.name, "Workstation")
        self.assertEqual(updated.total_quantity, 9)
        self.assertEqual(updated.available_quantity, 9)

    def test_update_can_move_a_resource_between_subcategories(self):
        self.seed_resource()
        updated = self.inventory.update_resource("R001", category="Accessories", subcategory="keyboard")
        self.assertEqual(updated.subcategory_id, "accessories-keyboard")

    def test_update_with_mismatched_pair_is_rejected(self):
        self.seed_resource()
        with self.assertRaises(NotFoundError):
            self.inventory.update_resource("R001", category="Accessories", subcategory="laptop")

    def test_remove_soft_deletes_and_keeps_the_record(self):
        self.seed_resource()
        removed = self.inventory.remove_resource("R001", reason="retired stock")
        self.assertFalse(removed.is_active)
        self.assertEqual(self.inventory.get_resource("R001").id, "R001")
        self.assertEqual(self.inventory.list_resources(), [])

    def test_removing_a_resource_with_units_on_loan_is_refused(self):
        self.seed_resource(total=4)
        self.store.append(
            EventType.LOAN_CHECKED_OUT,
            checkout_payload(
                transaction_id="T000001",
                resource_id="R001",
                borrower_id="F001",
                quantity=1,
                due_at="2026-02-01T09:00:00",
                condition_on_issue=Condition.GOOD,
                issued_by="admin",
            ),
        )
        self.assertEqual(self.inventory.get_resource("R001").issued_quantity, 1)
        with self.assertRaises(ConflictError):
            self.inventory.remove_resource("R001")

    def test_restore_reactivates_a_removed_resource(self):
        self.seed_resource()
        self.inventory.remove_resource("R001")
        restored = self.inventory.restore_resource("R001")
        self.assertTrue(restored.is_active)
        self.assertEqual(len(self.inventory.list_resources()), 1)

    def test_restoring_an_active_resource_is_refused(self):
        self.seed_resource()
        with self.assertRaises(ConflictError):
            self.inventory.restore_resource("R001")

    def test_mark_condition_moves_units_out_of_availability(self):
        self.seed_resource(total=10)
        updated = self.inventory.mark_condition("R001", "damaged", 3, reason="screen crack")
        self.assertEqual(updated.available_quantity, 7)
        self.assertEqual(updated.condition_counts["damaged"], 3)

    def test_restoring_to_good_requires_a_source_condition(self):
        self.seed_resource(total=10)
        self.inventory.mark_condition("R001", "faulty", 2)
        with self.assertRaises(ValidationError):
            self.inventory.mark_condition("R001", "good", 2)

    def test_restoring_from_a_named_bucket_returns_units(self):
        self.seed_resource(total=10)
        self.inventory.mark_condition("R001", "faulty", 2)
        updated = self.inventory.mark_condition("R001", "good", 2, restore_from="faulty")
        self.assertEqual(updated.available_quantity, 10)
        self.assertEqual(updated.condition_counts["faulty"], 0)

    def test_restore_from_good_is_rejected(self):
        self.seed_resource(total=10)
        with self.assertRaises(ValidationError):
            self.inventory.mark_condition("R001", "good", 1, restore_from="good")

    def test_marking_more_units_than_available_is_rejected(self):
        self.seed_resource(total=2)
        with self.assertRaises(ValidationError):
            self.inventory.mark_condition("R001", "missing", 5)

    def test_unknown_condition_is_rejected(self):
        self.seed_resource()
        with self.assertRaises(ValidationError):
            self.inventory.mark_condition("R001", "exploded", 1)

    def test_modifying_a_removed_resource_is_refused(self):
        self.seed_resource()
        self.inventory.remove_resource("R001")
        with self.assertRaises(ValidationError):
            self.inventory.mark_condition("R001", "damaged", 1)

    def test_search_matches_id_and_partial_name(self):
        self.seed_resource(name="Dell Latitude")
        self.seed_resource(name="ThinkPad")
        self.assertEqual([r.id for r in self.inventory.search_resources("R001")], ["R001"])
        self.assertEqual([r.id for r in self.inventory.search_resources("latitude")], ["R001"])
        self.assertEqual([r.id for r in self.inventory.search_resources("think")], ["R002"])

    def test_search_prefers_exact_name_matches(self):
        self.seed_resource(name="Laptop Stand")
        self.seed_resource(name="Laptop")
        self.assertEqual(self.inventory.search_resources("laptop")[0].name, "Laptop")

    def test_search_hides_removed_resources_by_default(self):
        self.seed_resource(name="Ghost")
        self.inventory.remove_resource("R001")
        self.assertEqual(self.inventory.search_resources("ghost"), [])
        self.assertEqual(len(self.inventory.search_resources("ghost", include_removed=True)), 1)

    def test_find_by_category_and_subcategory(self):
        self.seed_resource(name="Dell")
        self.seed_resource(name="Keyboard", category="Accessories", subcategory="keyboard")
        self.assertEqual(len(self.inventory.find_by_category("Electronics")), 1)
        self.assertEqual(len(self.inventory.find_by_category("electronics")), 1)
        self.assertEqual(
            [r.name for r in self.inventory.find_by_subcategory("keyboard")], ["Keyboard"]
        )

    def test_missing_resource_lookup_raises(self):
        with self.assertRaises(NotFoundError):
            self.inventory.get_resource("R404")

    def test_invalid_reference_is_a_validation_error(self):
        with self.assertRaises(ValidationError):
            self.inventory.get_resource("not an id")

    def test_low_stock_flag_tracks_availability(self):
        self.seed_resource(total=5)
        self.assertFalse(self.inventory.get_resource("R001").is_low_stock)
        self.inventory.mark_condition("R001", "missing", 3)
        self.assertTrue(self.inventory.get_resource("R001").is_low_stock)


if __name__ == "__main__":
    unittest.main()
