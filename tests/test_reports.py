from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lender.domain.equipment import Condition
from lender.domain.events import EventType
from lender.domain.transactions import checkout_payload, return_payload
from lender.services.inventory_service import InventoryService
from lender.services.reporting_service import ReportingService
from lender.services.taxonomy_service import TaxonomyService
from lender.storage.store import Store


class ReportingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store.open(Path(self._tmp.name))
        self.taxonomy = TaxonomyService(self.store)
        self.inventory = InventoryService(self.store, self.taxonomy)
        self.reports = ReportingService(self.store, self.taxonomy)
        self.taxonomy.create_category("Electronics")
        self.taxonomy.create_category("Accessories")
        self.taxonomy.create_subcategory("Electronics", "laptop")
        self.taxonomy.create_subcategory("Accessories", "keyboard")

    def add(self, name, category, subcategory, total):
        return self.inventory.add_resource(
            name=name, category=category, subcategory=subcategory, total_quantity=total
        )

    def checkout(self, transaction_id, resource_id, borrower_id, quantity, due_at="2026-03-01T09:00:00"):
        self.store.append(
            EventType.LOAN_CHECKED_OUT,
            checkout_payload(
                transaction_id=transaction_id,
                resource_id=resource_id,
                borrower_id=borrower_id,
                quantity=quantity,
                due_at=due_at,
                condition_on_issue=Condition.GOOD,
                issued_by="admin",
            ),
            occurred_at="2026-02-01T09:00:00",
        )

    def return_units(self, transaction_id, checkout_id, resource_id, borrower_id, quantity, condition=Condition.GOOD):
        self.store.append(
            EventType.LOAN_RETURNED,
            return_payload(
                transaction_id=transaction_id,
                checkout_transaction_id=checkout_id,
                resource_id=resource_id,
                borrower_id=borrower_id,
                quantity=quantity,
                condition_on_return=condition,
                returned_by="admin",
            ),
            occurred_at="2026-02-10T09:00:00",
        )


class StoreStatusTests(ReportingTestCase):
    def test_empty_store_status_is_zeroed(self):
        status = self.reports.store_status()
        self.assertEqual(status.rows, [])
        self.assertEqual(status.totals["resources"], 0)
        self.assertEqual(status.totals["total"], 0)

    def test_totals_aggregate_across_resources(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.add("Keyboard", "Accessories", "keyboard", 5)
        status = self.reports.store_status()
        self.assertEqual(status.totals["resources"], 2)
        self.assertEqual(status.totals["total"], 15)
        self.assertEqual(status.totals["available"], 15)
        self.assertEqual(status.totals["issued"], 0)

    def test_condition_buckets_are_reported_and_leave_availability(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.inventory.mark_condition("R001", "damaged", 4)
        self.inventory.mark_condition("R001", "missing", 1)
        row = self.reports.store_status().rows[0]
        self.assertEqual(row.damaged, 4)
        self.assertEqual(row.missing, 1)
        self.assertEqual(row.available, 5)
        self.assertEqual(row.total, 10)

    def test_rows_carry_display_names_not_ids(self):
        self.add("Dell", "Electronics", "laptop", 3)
        row = self.reports.store_status().rows[0]
        self.assertEqual(row.category, "Electronics")
        self.assertEqual(row.subcategory, "laptop")

    def test_removed_resources_are_excluded_unless_requested(self):
        self.add("Dell", "Electronics", "laptop", 3)
        self.inventory.remove_resource("R001")
        self.assertEqual(self.reports.store_status().rows, [])
        self.assertEqual(len(self.reports.store_status(include_removed=True).rows), 1)


class LowStockTests(ReportingTestCase):
    def test_low_stock_lists_only_resources_below_threshold(self):
        self.add("Plenty", "Electronics", "laptop", 10)
        self.add("Scarce", "Accessories", "keyboard", 2)
        rows = self.reports.low_stock()
        self.assertEqual([row.name for row in rows], ["Scarce"])

    def test_stock_drops_into_low_stock_after_issue(self):
        self.add("Dell", "Electronics", "laptop", 5)
        self.assertEqual(self.reports.low_stock(), [])
        self.checkout("T000001", "R001", "F001", 3)
        self.assertEqual([row.name for row in self.reports.low_stock()], ["Dell"])

    def test_store_status_and_low_stock_agree(self):
        self.add("Scarce", "Accessories", "keyboard", 1)
        status = self.reports.store_status()
        self.assertEqual(status.low_stock, self.reports.low_stock())


class InventoryReportTests(ReportingTestCase):
    def test_category_rollup_sums_members(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.add("Lenovo", "Electronics", "laptop", 5)
        self.add("Keyboard", "Accessories", "keyboard", 4)
        report = self.reports.inventory_report()
        by_name = {row.category: row for row in report.categories}
        self.assertEqual(by_name["Electronics"].resources, 2)
        self.assertEqual(by_name["Electronics"].total, 15)
        self.assertEqual(by_name["Accessories"].total, 4)

    def test_category_rollup_counts_unavailable_separately(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.inventory.mark_condition("R001", "faulty", 3)
        row = {r.category: r for r in self.reports.inventory_report().categories}["Electronics"]
        self.assertEqual(row.available, 7)
        self.assertEqual(row.unavailable, 3)

    def test_category_rollup_counts_low_stock_members(self):
        self.add("Dell", "Electronics", "laptop", 2)
        self.add("Lenovo", "Electronics", "laptop", 20)
        row = {r.category: r for r in self.reports.inventory_report().categories}["Electronics"]
        self.assertEqual(row.low_stock, 1)

    def test_report_can_be_filtered_to_one_category(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.add("Keyboard", "Accessories", "keyboard", 4)
        report = self.reports.inventory_report(category="Electronics")
        self.assertEqual([row.category for row in report.categories], ["Electronics"])
        self.assertEqual(report.totals["total"], 10)


class MostBorrowedTests(ReportingTestCase):
    def test_no_loans_returns_nothing(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.assertEqual(self.reports.most_borrowed(), [])

    def test_leader_is_the_resource_with_most_units_out(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.add("Keyboard", "Accessories", "keyboard", 10)
        self.checkout("T000001", "R001", "F001", 4)
        self.checkout("T000002", "R002", "F002", 2)
        leaders = self.reports.most_borrowed()
        self.assertEqual(len(leaders), 1)
        self.assertEqual(leaders[0]["resource_id"], "R001")
        self.assertEqual(leaders[0]["borrowed"], 4)

    def test_returned_units_do_not_count(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.add("Keyboard", "Accessories", "keyboard", 10)
        self.checkout("T000001", "R001", "F001", 4)
        self.checkout("T000002", "R002", "F002", 3)
        self.return_units("T000003", "T000001", "R001", "F001", 4)
        leaders = self.reports.most_borrowed()
        self.assertEqual(leaders[0]["resource_id"], "R002")

    def test_partial_returns_reduce_the_count(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.checkout("T000001", "R001", "F001", 5)
        self.return_units("T000002", "T000001", "R001", "F001", 2)
        self.assertEqual(self.reports.most_borrowed()[0]["borrowed"], 3)

    def test_all_tied_leaders_are_returned(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.add("Keyboard", "Accessories", "keyboard", 10)
        self.checkout("T000001", "R001", "F001", 3)
        self.checkout("T000002", "R002", "F002", 3)
        leaders = self.reports.most_borrowed()
        self.assertEqual([row["resource_id"] for row in leaders], ["R001", "R002"])
        self.assertTrue(all(row["borrowed"] == 3 for row in leaders))

    def test_loans_across_borrowers_accumulate_per_resource(self):
        self.add("Dell", "Electronics", "laptop", 10)
        self.checkout("T000001", "R001", "F001", 2)
        self.checkout("T000002", "R001", "F002", 3)
        self.assertEqual(self.reports.most_borrowed()[0]["borrowed"], 5)


if __name__ == "__main__":
    unittest.main()
