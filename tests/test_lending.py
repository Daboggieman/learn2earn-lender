from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from lender.domain.equipment import Condition
from lender.domain.errors import ConflictError, NotFoundError, ValidationError
from lender.domain.events import EventType
from lender.domain.transactions import checkout_payload
from lender.services.inventory_service import InventoryService
from lender.services.lending_service import DEFAULT_LOAN_DAYS, LendingService
from lender.services.people_service import PeopleService
from lender.services.taxonomy_service import TaxonomyService
from lender.storage.store import Store
from lender.validators.dates import now


class LendingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store.open(Path(self._tmp.name))

        taxonomy = TaxonomyService(self.store)
        taxonomy.create_category("Electronics")
        taxonomy.create_subcategory("Electronics", "laptop")
        self.inventory = InventoryService(self.store, taxonomy)
        self.people = PeopleService(self.store)
        self.lending = LendingService(self.store)

        self.people.add_cohort("cluster-1-feb")
        self.people.add_trial("trial-period-1")
        self.people.add_fellow("Ada Lovelace", "cluster-1-feb")
        self.people.add_piscine("Grace Hopper", "trial-period-1")
        self.inventory.add_resource(
            name="Laptop",
            category="Electronics",
            subcategory="laptop",
            total_quantity=10,
        )

    def backdated_loan(self, transaction_id, quantity, due_at, borrower_id="F001"):
        self.store.append(
            EventType.LOAN_CHECKED_OUT,
            checkout_payload(
                transaction_id=transaction_id,
                resource_id="R001",
                borrower_id=borrower_id,
                quantity=quantity,
                due_at=due_at,
                condition_on_issue=Condition.GOOD,
                issued_by="admin",
            ),
            occurred_at=(now() - timedelta(days=60)).isoformat(),
        )


class CheckoutTests(LendingTestCase):
    def test_checkout_creates_a_loan_and_issues_units(self):
        loan = self.lending.check_out("R001", "F001", 3)
        self.assertEqual(loan.transaction_id, "T000001")
        self.assertEqual(loan.quantity, 3)
        self.assertEqual(loan.outstanding_quantity, 3)
        self.assertFalse(loan.is_returned)
        self.assertEqual(self.store.state.resources["R001"].issued_quantity, 3)
        self.assertEqual(self.store.state.resources["R001"].available_quantity, 7)

    def test_transaction_ids_increment(self):
        self.assertEqual(self.lending.check_out("R001", "F001", 1).transaction_id, "T000001")
        self.assertEqual(self.lending.check_out("R001", "P001", 1).transaction_id, "T000002")

    def test_borrower_can_hold_several_loans_at_once(self):
        first = self.lending.check_out("R001", "F001", 2)
        second = self.lending.check_out("R001", "F001", 1)
        self.assertNotEqual(first.transaction_id, second.transaction_id)
        self.assertEqual(self.store.state.resources["R001"].issued_quantity, 3)

    def test_unknown_resource_is_reported(self):
        with self.assertRaises(NotFoundError):
            self.lending.check_out("R999", "F001", 1)

    def test_unknown_borrower_is_reported(self):
        with self.assertRaises(NotFoundError):
            self.lending.check_out("R001", "F999", 1)

    def test_cannot_check_out_more_than_available(self):
        with self.assertRaises(ConflictError):
            self.lending.check_out("R001", "F001", 11)
        self.assertEqual(self.store.state.resources["R001"].available_quantity, 10)

    def test_cannot_check_out_a_fractional_quantity(self):
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 0)

    def test_removed_resource_cannot_be_lent(self):
        self.inventory.remove_resource("R001")
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 1)

    def test_inactive_borrower_cannot_borrow(self):
        self.people.update_person("F001", status="inactive")
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 1)

    def test_two_borrowers_cannot_oversubscribe_stock(self):
        self.lending.check_out("R001", "F001", 6)
        with self.assertRaises(ConflictError):
            self.lending.check_out("R001", "P001", 5)


class DueDateTests(LendingTestCase):
    def test_default_loan_period(self):
        loan = self.lending.check_out("R001", "F001", 1)
        expected = loan.issued_datetime + timedelta(days=DEFAULT_LOAN_DAYS)
        self.assertEqual(loan.due_datetime, expected)

    def test_days_option_overrides_the_default(self):
        loan = self.lending.check_out("R001", "F001", 1, days=3)
        expected = loan.issued_datetime + timedelta(days=3)
        self.assertEqual(loan.due_datetime, expected)

    def test_explicit_date_is_due_at_the_end_of_that_day(self):
        target = (now() + timedelta(days=30)).date()
        loan = self.lending.check_out("R001", "F001", 1, due_at=target.isoformat())
        self.assertEqual(loan.due_datetime.date(), target)
        self.assertEqual((loan.due_datetime.hour, loan.due_datetime.minute), (23, 59))

    def test_explicit_timestamp_is_used_verbatim(self):
        moment = (now() + timedelta(days=10)).replace(hour=9, minute=30, second=0)
        loan = self.lending.check_out("R001", "F001", 1, due_at=moment.isoformat())
        self.assertEqual(loan.due_datetime, moment)

    def test_due_and_days_together_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 1, days=5, due_at="2026-12-01")

    def test_a_due_date_in_the_past_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 1, due_at="2020-01-01")

    def test_a_zero_day_period_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 1, days=0)

    def test_a_malformed_due_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.lending.check_out("R001", "F001", 1, due_at="next friday")

    def test_a_fresh_loan_is_not_overdue(self):
        loan = self.lending.check_out("R001", "F001", 1)
        self.assertFalse(loan.is_overdue())
        self.assertEqual(loan.days_overdue(), 0)


class ReturnTests(LendingTestCase):
    def test_full_return_closes_the_loan_and_restores_stock(self):
        self.lending.check_out("R001", "F001", 3)
        loan = self.lending.return_units("T000001")
        self.assertTrue(loan.is_returned)
        self.assertEqual(loan.outstanding_quantity, 0)
        self.assertEqual(self.store.state.resources["R001"].available_quantity, 10)
        self.assertEqual(self.store.state.resources["R001"].issued_quantity, 0)

    def test_return_without_a_quantity_returns_everything_outstanding(self):
        self.lending.check_out("R001", "F001", 4)
        self.lending.return_units("T000001", 1)
        loan = self.lending.return_units("T000001")
        self.assertTrue(loan.is_returned)
        self.assertEqual(loan.returned_quantity, 4)

    def test_partial_return_keeps_the_loan_open(self):
        self.lending.check_out("R001", "F001", 5)
        loan = self.lending.return_units("T000001", 2)
        self.assertFalse(loan.is_returned)
        self.assertEqual(loan.outstanding_quantity, 3)
        self.assertEqual(self.store.state.resources["R001"].available_quantity, 7)

    def test_returning_damaged_units_keeps_them_out_of_circulation(self):
        self.lending.check_out("R001", "F001", 2)
        self.lending.return_units("T000001", 2, condition="damaged")
        resource = self.store.state.resources["R001"]
        self.assertEqual(resource.available_quantity, 8)
        self.assertEqual(resource.condition_counts["damaged"], 2)
        resource.check_invariant()

    def test_returning_faulty_units_keeps_them_out_of_circulation(self):
        self.lending.check_out("R001", "F001", 2)
        self.lending.return_units("T000001", condition="faulty")
        self.assertEqual(self.store.state.resources["R001"].condition_counts["faulty"], 2)
        self.assertEqual(self.store.state.resources["R001"].available_quantity, 8)

    def test_over_returning_is_rejected(self):
        self.lending.check_out("R001", "F001", 2)
        with self.assertRaises(ValidationError):
            self.lending.return_units("T000001", 3)
        self.assertEqual(self.store.state.loans["T000001"].returned_quantity, 0)

    def test_returning_a_closed_loan_is_rejected(self):
        self.lending.check_out("R001", "F001", 1)
        self.lending.return_units("T000001")
        with self.assertRaises(ConflictError):
            self.lending.return_units("T000001")

    def test_returning_an_unknown_loan_is_reported(self):
        with self.assertRaises(NotFoundError):
            self.lending.return_units("T999999")

    def test_a_malformed_condition_is_rejected(self):
        self.lending.check_out("R001", "F001", 1)
        with self.assertRaises(ValidationError):
            self.lending.return_units("T000001", condition="exploded")

    def test_returns_do_not_affect_other_loans(self):
        self.lending.check_out("R001", "F001", 2)
        self.lending.check_out("R001", "P001", 2)
        self.lending.return_units("T000001")
        self.assertFalse(self.store.state.loans["T000002"].is_returned)
        self.assertEqual(self.store.state.resources["R001"].issued_quantity, 2)


class HistoryTests(LendingTestCase):
    def setUp(self):
        super().setUp()
        self.lending.check_out("R001", "F001", 2)
        self.lending.check_out("R001", "P001", 1)
        self.lending.return_units("T000001")

    def test_history_includes_returned_and_open_loans(self):
        self.assertEqual(
            [loan.transaction_id for loan in self.lending.history()],
            ["T000001", "T000002"],
        )

    def test_history_filters_by_resource(self):
        self.assertEqual(len(self.lending.history(resource="R001")), 2)
        self.assertEqual(self.lending.history(resource="R999"), [])

    def test_history_filters_by_borrower(self):
        self.assertEqual(
            [loan.transaction_id for loan in self.lending.history(borrower="F001")],
            ["T000001"],
        )

    def test_history_can_show_only_outstanding_loans(self):
        self.assertEqual(
            [loan.transaction_id for loan in self.lending.history(outstanding_only=True)],
            ["T000002"],
        )

    def test_history_is_ordered_by_issue_time(self):
        issued = [loan.issued_at for loan in self.lending.history()]
        self.assertEqual(issued, sorted(issued))

    def test_get_loan_reports_unknown_ids(self):
        with self.assertRaises(NotFoundError):
            self.lending.get_loan("T404")

    def test_loans_survive_a_rebuild_from_the_log(self):
        reopened = Store.open(self.store.paths.root)
        self.assertEqual(sorted(reopened.state.loans), ["T000001", "T000002"])
        self.assertTrue(reopened.state.loans["T000001"].is_returned)


class OverdueTests(LendingTestCase):
    def test_a_loan_past_its_due_date_is_overdue(self):
        self.backdated_loan("T000001", 2, (now() - timedelta(days=5)).isoformat())
        overdue = self.lending.overdue()
        self.assertEqual([loan.transaction_id for loan in overdue], ["T000001"])
        self.assertEqual(overdue[0].days_overdue(), 5)

    def test_a_loan_inside_its_window_is_not_overdue(self):
        self.backdated_loan("T000001", 2, (now() + timedelta(days=5)).isoformat())
        self.assertEqual(self.lending.overdue(), [])

    def test_returned_loans_are_never_overdue(self):
        self.backdated_loan("T000001", 2, (now() - timedelta(days=5)).isoformat())
        self.lending.return_units("T000001")
        self.assertEqual(self.lending.overdue(), [])

    def test_overdue_can_be_filtered_by_borrower(self):
        self.backdated_loan("T000001", 1, (now() - timedelta(days=3)).isoformat())
        self.backdated_loan("T000002", 1, (now() - timedelta(days=3)).isoformat(), borrower_id="P001")
        self.assertEqual(
            [loan.transaction_id for loan in self.lending.overdue(borrower="F001")],
            ["T000001"],
        )

    def test_overdue_is_ordered_by_due_date(self):
        self.backdated_loan("T000001", 1, (now() - timedelta(days=2)).isoformat())
        self.backdated_loan("T000002", 1, (now() - timedelta(days=9)).isoformat())
        self.assertEqual(
            [loan.transaction_id for loan in self.lending.overdue()],
            ["T000002", "T000001"],
        )


class BorrowerHistoryTests(LendingTestCase):
    def setUp(self):
        super().setUp()
        self.lending.check_out("R001", "F001", 3)
        self.lending.check_out("R001", "F001", 1)
        self.lending.return_units("T000001")
        self.backdated_loan("T000003", 2, (now() - timedelta(days=4)).isoformat())

    def test_summary_identifies_the_borrower_and_group(self):
        summary = self.lending.borrower_history("F001")
        self.assertEqual(summary["borrower_id"], "F001")
        self.assertEqual(summary["name"], "Ada Lovelace")
        self.assertEqual(summary["type"], "fellow")
        self.assertEqual(summary["group_name"], "cluster-1-feb")
        self.assertEqual(summary["group_type"], "cohort")

    def test_summary_counts_every_loan(self):
        summary = self.lending.borrower_history("F001")
        self.assertEqual(summary["total_loans"], 3)
        self.assertEqual(summary["lifetime_units"], 6)

    def test_summary_separates_open_and_overdue_loans(self):
        summary = self.lending.borrower_history("F001")
        self.assertEqual(
            sorted(loan.transaction_id for loan in summary["open_loans"]),
            ["T000002", "T000003"],
        )
        self.assertEqual(
            [loan.transaction_id for loan in summary["overdue_loans"]],
            ["T000003"],
        )
        self.assertEqual(summary["outstanding_units"], 3)

    def test_history_lists_loans_in_issue_order(self):
        summary = self.lending.borrower_history("F001")
        issued = [loan.issued_at for loan in summary["loans"]]
        self.assertEqual(issued, sorted(issued))
        self.assertEqual(
            [loan.transaction_id for loan in summary["loans"]],
            ["T000003", "T000001", "T000002"],
        )

    def test_another_borrower_is_unaffected(self):
        summary = self.lending.borrower_history("P001")
        self.assertEqual(summary["total_loans"], 0)
        self.assertEqual(summary["lifetime_units"], 0)

    def test_unknown_borrower_is_reported(self):
        with self.assertRaises(NotFoundError):
            self.lending.borrower_history("F999")


if __name__ == "__main__":
    unittest.main()
