from __future__ import annotations

import unittest
from datetime import datetime

from lender.domain.equipment import (
    LOW_STOCK_THRESHOLD,
    Condition,
    Resource,
    ResourceStatus,
)
from lender.domain.errors import InvariantViolation, ValidationError
from lender.domain.taxonomy import TaxonomyNode, TaxonomyType
from lender.domain.transactions import Transaction, checkout_payload, return_payload
from lender.validators import dates, ids, quantities, strings


def make_resource(total: int = 10, **overrides) -> Resource:
    fields = {
        "id": "R001",
        "name": "Laptop",
        "category_id": "electronics",
        "subcategory_id": "electronics-laptop",
        "total_quantity": total,
        "available_quantity": total,
        "issued_quantity": 0,
    }
    fields.update(overrides)
    return Resource(**fields)


class ResourceInvariantTests(unittest.TestCase):
    def test_balance_sheet_holds_after_mixed_activity(self):
        resource = make_resource(10)
        resource.transfer_condition(Condition.GOOD, Condition.FAULTY, 2)
        resource.issue_units(3)
        resource.release_units(1, Condition.DAMAGED)
        resource.check_invariant()
        self.assertEqual(resource.available_quantity, 5)
        self.assertEqual(resource.issued_quantity, 2)
        self.assertEqual(resource.condition_counts["faulty"], 2)
        self.assertEqual(resource.condition_counts["damaged"], 1)
        self.assertEqual(resource.good_quantity, 7)

    def test_unbalanced_resource_is_rejected(self):
        broken = make_resource(10, available_quantity=99)
        with self.assertRaises(InvariantViolation):
            broken.check_invariant()

    def test_negative_bucket_is_rejected(self):
        broken = make_resource(10, available_quantity=-1)
        with self.assertRaises(InvariantViolation):
            broken.check_invariant()

    def test_good_quantity_is_derived_not_stored(self):
        resource = make_resource(4)
        resource.issue_units(4)
        self.assertEqual(resource.good_quantity, 4)
        self.assertEqual(resource.available_quantity, 0)


class LendingRuleTests(unittest.TestCase):
    def test_cannot_issue_more_than_available(self):
        resource = make_resource(3)
        with self.assertRaises(ValidationError):
            resource.issue_units(4)

    def test_cannot_over_return(self):
        resource = make_resource(5)
        resource.issue_units(2)
        with self.assertRaises(ValidationError):
            resource.release_units(3, Condition.GOOD)

    def test_return_in_damaged_condition_leaves_circulation(self):
        resource = make_resource(4)
        resource.issue_units(2)
        resource.release_units(2, Condition.DAMAGED)
        self.assertEqual(resource.available_quantity, 2)
        self.assertEqual(resource.issued_quantity, 0)
        self.assertEqual(resource.condition_counts["damaged"], 2)

    def test_transfer_between_condition_buckets(self):
        resource = make_resource(5)
        resource.transfer_condition(Condition.GOOD, Condition.MISSING, 2)
        resource.transfer_condition(Condition.MISSING, Condition.GOOD, 1)
        self.assertEqual(resource.condition_counts["missing"], 1)
        self.assertEqual(resource.available_quantity, 4)

    def test_transfer_more_than_bucket_holds_is_rejected(self):
        resource = make_resource(5)
        with self.assertRaises(ValidationError):
            resource.transfer_condition(Condition.GOOD, Condition.FAULTY, 6)

    def test_same_source_and_destination_is_rejected(self):
        resource = make_resource(5)
        with self.assertRaises(ValidationError):
            resource.transfer_condition(Condition.GOOD, Condition.GOOD, 1)

    def test_shrinking_total_below_available_is_rejected(self):
        resource = make_resource(5)
        resource.issue_units(4)
        with self.assertRaises(ValidationError):
            resource.set_total_quantity(2)

    def test_growing_total_adds_available_units(self):
        resource = make_resource(5)
        resource.set_total_quantity(8)
        self.assertEqual(resource.available_quantity, 8)
        self.assertEqual(resource.total_quantity, 8)

    def test_removed_resource_cannot_be_modified(self):
        resource = make_resource(5, status=ResourceStatus.REMOVED)
        with self.assertRaises(ValidationError):
            resource.require_active("modify")

    def test_low_stock_threshold(self):
        self.assertTrue(make_resource(LOW_STOCK_THRESHOLD - 1).is_low_stock)
        self.assertFalse(make_resource(LOW_STOCK_THRESHOLD).is_low_stock)


class ResourceSerialisationTests(unittest.TestCase):
    def test_round_trip_preserves_every_field(self):
        resource = make_resource(6, needed_quantity=3, notes="lab")
        resource.transfer_condition(Condition.GOOD, Condition.RETIRED, 1)
        self.assertEqual(Resource.from_dict(resource.to_dict()).to_dict(), resource.to_dict())

    def test_missing_required_field_is_reported(self):
        with self.assertRaises(ValidationError):
            Resource.from_dict({"id": "R001", "name": "Laptop"})

    def test_available_is_derived_when_omitted(self):
        restored = Resource.from_dict(
            {
                "id": "R900",
                "name": "Spare",
                "category_id": "c",
                "subcategory_id": "s",
                "total_quantity": 10,
                "issued_quantity": 4,
                "condition_counts": {"faulty": 1},
            }
        )
        self.assertEqual(restored.available_quantity, 5)

    def test_unknown_condition_is_rejected(self):
        with self.assertRaises(ValidationError):
            Condition.parse("exploded")


class TransactionTests(unittest.TestCase):
    def _open_loan(self, quantity: int = 2, due: str = "2026-02-01T09:00:00") -> Transaction:
        return Transaction.from_checkout_event(
            checkout_payload(
                transaction_id="T000001",
                resource_id="R001",
                borrower_id="F001",
                quantity=quantity,
                due_at=due,
                condition_on_issue=Condition.GOOD,
                issued_by="admin",
            ),
            "2026-01-15T09:00:00",
        )

    def test_return_closes_the_loan(self):
        loan = self._open_loan()
        loan.apply_return(
            return_payload(
                transaction_id="T000002",
                checkout_transaction_id="T000001",
                resource_id="R001",
                borrower_id="F001",
                quantity=2,
                condition_on_return=Condition.GOOD,
                returned_by="admin",
            ),
            "2026-01-20T09:00:00",
        )
        self.assertTrue(loan.is_returned)
        self.assertEqual(loan.outstanding_quantity, 0)

    def test_partial_returns_accumulate(self):
        loan = self._open_loan(3)
        for index in range(3):
            loan.apply_return(
                return_payload(
                    transaction_id=f"T00000{index + 2}",
                    checkout_transaction_id="T000001",
                    resource_id="R001",
                    borrower_id="F001",
                    quantity=1,
                    condition_on_return=Condition.GOOD,
                    returned_by="admin",
                ),
                "2026-01-20T09:00:00",
            )
        self.assertTrue(loan.is_returned)
        self.assertEqual(loan.returned_quantity, 3)

    def test_over_return_is_rejected(self):
        loan = self._open_loan(1)
        with self.assertRaises(ValidationError):
            loan.apply_return(
                return_payload(
                    transaction_id="T000002",
                    checkout_transaction_id="T000001",
                    resource_id="R001",
                    borrower_id="F001",
                    quantity=2,
                    condition_on_return=Condition.GOOD,
                    returned_by="admin",
                ),
                "2026-01-20T09:00:00",
            )

    def test_overdue_is_derived_from_due_date(self):
        loan = self._open_loan(due="2026-01-20T09:00:00")
        self.assertTrue(loan.is_overdue(datetime(2026, 1, 25, 9, 0, 0)))
        self.assertEqual(loan.days_overdue(datetime(2026, 1, 25, 9, 0, 0)), 5)
        self.assertEqual(loan.effective_status(datetime(2026, 1, 25, 9, 0, 0)).value, "overdue")

    def test_returned_loan_is_never_overdue(self):
        loan = self._open_loan()
        loan.apply_return(
            return_payload(
                transaction_id="T000002",
                checkout_transaction_id="T000001",
                resource_id="R001",
                borrower_id="F001",
                quantity=2,
                condition_on_return=Condition.GOOD,
                returned_by="admin",
            ),
            "2026-01-16T09:00:00",
        )
        self.assertFalse(loan.is_overdue(datetime(2030, 1, 1)))


class TaxonomyEntityTests(unittest.TestCase):
    def test_category_must_not_have_a_parent(self):
        node = TaxonomyNode(id="c", name="C", type=TaxonomyType.CATEGORY, parent_id="x")
        with self.assertRaises(ValidationError):
            node.check_shape()

    def test_subcategory_requires_a_parent(self):
        node = TaxonomyNode(id="s", name="S", type=TaxonomyType.SUBCATEGORY)
        with self.assertRaises(ValidationError):
            node.check_shape()


class ValidatorTests(unittest.TestCase):
    def test_quantities_reject_booleans_and_fractions(self):
        for bad in (True, 1.5, "", "abc", None):
            with self.assertRaises(ValidationError):
                quantities.coerce_int(bad)

    def test_positive_and_non_negative(self):
        self.assertEqual(quantities.require_positive("3"), 3)
        self.assertEqual(quantities.require_non_negative(0), 0)
        with self.assertRaises(ValidationError):
            quantities.require_positive(0)
        with self.assertRaises(ValidationError):
            quantities.require_non_negative(-1)

    def test_sequential_ids_skip_taken_numbers(self):
        self.assertEqual(ids.next_sequential_id("R", ["R001", "R002"]), "R003")
        self.assertEqual(ids.next_sequential_id("R", []), "R001")
        self.assertEqual(ids.next_sequential_id("R", ["custom"]), "R001")

    def test_invalid_ids_are_rejected(self):
        with self.assertRaises(ValidationError):
            ids.validate_id(" ")
        with self.assertRaises(ValidationError):
            ids.validate_id("has space")
        self.assertEqual(ids.validate_id("R-001.x"), "R-001.x")

    def test_slugify_normalises_names(self):
        self.assertEqual(strings.slugify("Cluster 1 Feb"), "cluster-1-feb")
        self.assertEqual(strings.normalise_name("  Ada   Lovelace "), "Ada Lovelace")

    def test_dates_accept_both_forms(self):
        self.assertEqual(str(dates.parse_date("2026-02-01")), "2026-02-01")
        self.assertEqual(str(dates.parse_date("2026-02-01T09:00:00")), "2026-02-01")
        with self.assertRaises(ValidationError):
            dates.parse_date("01/02/2026")

    def test_due_before_issue_is_rejected(self):
        with self.assertRaises(ValidationError):
            dates.require_not_before(
                datetime(2026, 1, 1), datetime(2026, 2, 1)
            )


if __name__ == "__main__":
    unittest.main()
