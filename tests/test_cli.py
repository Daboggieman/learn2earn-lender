from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from lender.cli.app import main
from lender.storage.store import Store


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = str(Path(self._tmp.name) / "data")

    def run_cli(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--data-dir", self.data_dir, *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def run_json(self, *argv):
        code, out, err = self.run_cli("--json", *argv)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def seed(self):
        code, out, err = self.run_cli("seed")
        self.assertEqual(code, 0, err)
        return out


class ParserTests(CliTestCase):
    def test_version_exits_cleanly(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--version"])
        self.assertEqual(caught.exception.code, 0)

    def test_no_command_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main([])
        self.assertEqual(caught.exception.code, 2)

    def test_unknown_command_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["explode"])
        self.assertEqual(caught.exception.code, 2)

    def test_help_exits_cleanly_and_lists_the_command_surface(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as caught:
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        for command in ("add-resource", "mark-condition", "report-low-stock", "seed"):
            self.assertIn(command, stdout.getvalue())


class SeedCommandTests(CliTestCase):
    def test_seed_populates_the_data_directory(self):
        out = self.seed()
        self.assertIn("Seeded", out)
        self.assertTrue((Path(self.data_dir) / "transactions").is_dir())
        self.assertTrue((Path(self.data_dir) / "current" / "inventory.json").is_file())

    def test_seed_reproduces_the_baseline_records(self):
        self.seed()
        store = Store.open(self.data_dir)
        self.assertEqual(sorted(store.state.resources), ["R001", "R002", "R003"])
        self.assertEqual(len(store.state.taxonomy), 12)
        self.assertEqual(sorted(store.state.people), ["F001", "F002", "F003"])

    def test_seed_is_idempotent_only_with_force(self):
        self.seed()
        code, out, err = self.run_cli("seed")
        self.assertEqual(code, 4)
        self.assertIn("--force", err)

    def test_force_reseed_succeeds(self):
        self.seed()
        code, out, err = self.run_cli("seed", "--force")
        self.assertEqual(code, 0, err)

    def test_seed_json_reports_counts(self):
        summary = self.run_json("seed")
        self.assertEqual(summary["resources"], 3)
        self.assertEqual(summary["taxonomy_nodes"], 12)
        self.assertEqual(summary["people"], 3)

    def test_mock_seed_generates_more_data(self):
        summary = self.run_json(
            "seed", "--mock-fellows", "20", "--mock-piscine", "5",
            "--mock-equipment", "9", "--mock-loans", "30",
        )
        self.assertGreater(summary["resources"], 3)
        self.assertGreater(summary["people"], 3)
        self.assertGreater(summary["loans"], 0)

    def test_mock_seed_is_deterministic_for_a_fixed_seed(self):
        first = self.run_json("seed", "--mock-fellows", "15", "--mock-loans", "20")
        second = self.run_json("seed", "--force", "--mock-fellows", "15", "--mock-loans", "20")
        self.assertEqual(first["events"], second["events"])

    def test_mock_seed_keeps_resource_ids_unique(self):
        self.seed()
        self.run_json("seed", "--force", "--mock-equipment", "6")
        store = Store.open(self.data_dir)
        self.assertEqual(len(store.state.resources), 9)


class TaxonomyCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_add_and_list_categories(self):
        self.assertEqual(self.run_cli("add-category", "Lab Gear")[0], 0)
        payload = self.run_json("list-categories")
        self.assertIn("Lab Gear", json.dumps(payload))

    def test_add_subcategory_under_a_category(self):
        self.run_cli("add-category", "Lab Gear")
        code, out, err = self.run_cli("add-subcategory", "Lab Gear", "Oscilloscopes")
        self.assertEqual(code, 0, err)
        payload = self.run_json("list-subcategories", "Lab Gear")
        self.assertIn("Oscilloscopes", json.dumps(payload))

    def test_duplicate_category_exits_with_conflict(self):
        code, out, err = self.run_cli("add-category", "Electronics")
        self.assertEqual(code, 4)
        self.assertIn("already", err.lower())

    def test_unknown_category_exits_with_not_found(self):
        code, out, err = self.run_cli("add-subcategory", "Ghost", "Thing")
        self.assertEqual(code, 3)

    def test_update_category_renames(self):
        code, out, err = self.run_cli("update-category", "Electronics", "--name", "Hardware")
        self.assertEqual(code, 0, err)
        self.assertIn("Hardware", self.run_cli("list-categories")[1])

    def test_removing_a_category_in_use_is_refused(self):
        code, out, err = self.run_cli("remove-category", "Electronics")
        self.assertEqual(code, 4)
        self.assertIn("cannot remove", err.lower())

    def test_removing_an_empty_category_succeeds(self):
        self.run_cli("add-category", "Spare")
        self.assertEqual(self.run_cli("remove-category", "Spare")[0], 0)


class InventoryCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_add_resource_to_a_seeded_subcategory(self):
        payload = self.run_json(
            "add-resource", "--name", "Dell Latitude",
            "--category", "Electronics", "--subcategory", "laptop", "--total", "7",
        )
        self.assertEqual(payload["id"], "R004")
        self.assertEqual(payload["available_quantity"], 7)

    def test_add_resource_rejects_an_unknown_subcategory(self):
        code, out, err = self.run_cli(
            "add-resource", "--name", "X", "--category", "Electronics",
            "--subcategory", "ghost", "--total", "1",
        )
        self.assertEqual(code, 3)

    def test_add_resource_rejects_a_non_positive_total(self):
        code, out, err = self.run_cli(
            "add-resource", "--name", "X", "--category", "Electronics",
            "--subcategory", "laptop", "--total", "0",
        )
        self.assertEqual(code, 2)

    def test_add_resource_rejects_a_non_numeric_total(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main([
                    "--data-dir", self.data_dir, "add-resource", "--name", "X",
                    "--category", "Electronics", "--subcategory", "laptop", "--total", "many",
                ])
        self.assertEqual(caught.exception.code, 2)

    def test_find_resource_by_term_returns_a_match_list(self):
        payload = self.run_json("find-resource", "laptop")
        self.assertEqual([row["id"] for row in payload], ["R001"])

    def test_find_resource_with_no_match_is_an_empty_result_not_an_error(self):
        code, out, err = self.run_cli("find-resource", "R999")
        self.assertEqual(code, 0)
        self.assertIn("No resource matches", out)

    def test_find_by_category_lists_members(self):
        payload = self.run_json("find-by-category", "Accessories")
        self.assertEqual(sorted(row["id"] for row in payload), ["R002", "R003"])

    def test_list_resources_shows_seeded_stock(self):
        code, out, err = self.run_cli("list-resources")
        self.assertEqual(code, 0, err)
        for name in ("Laptop", "Keyboard", "Headset"):
            self.assertIn(name, out)

    def test_update_resource_changes_the_total(self):
        payload = self.run_json("update-resource", "R001", "--total", "25")
        self.assertEqual(payload["total_quantity"], 25)
        self.assertEqual(payload["available_quantity"], 25)

    def test_mark_condition_moves_units(self):
        payload = self.run_json("mark-condition", "R001", "faulty", "2", "--reason", "flicker")
        self.assertEqual(payload["available_quantity"], 8)
        self.assertEqual(payload["condition_counts"]["faulty"], 2)

    def test_mark_condition_restores_from_a_bucket(self):
        self.run_cli("mark-condition", "R001", "faulty", "2")
        payload = self.run_json("mark-condition", "R001", "good", "2", "--from", "faulty")
        self.assertEqual(payload["available_quantity"], 10)
        self.assertEqual(payload["condition_counts"]["faulty"], 0)

    def test_mark_condition_requires_from_when_restoring(self):
        code, out, err = self.run_cli("mark-condition", "R001", "good", "1")
        self.assertEqual(code, 2)
        self.assertIn("--from", err)

    def test_mark_condition_rejects_over_quantity(self):
        code, out, err = self.run_cli("mark-condition", "R001", "damaged", "99")
        self.assertEqual(code, 2)

    def test_remove_and_restore_a_resource(self):
        self.assertEqual(self.run_cli("remove-resource", "R003")[0], 0)
        active = self.run_json("find-by-category", "Accessories")
        self.assertEqual([row["id"] for row in active], ["R002"])
        self.assertEqual(self.run_cli("restore-resource", "R003")[0], 0)
        restored = self.run_json("find-by-category", "Accessories")
        self.assertEqual(sorted(row["id"] for row in restored), ["R002", "R003"])


class ReportCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_store_status_totals_all_seeded_stock(self):
        payload = self.run_json("report-store-status")
        self.assertEqual(payload["totals"]["total"], 18)
        self.assertEqual(payload["totals"]["available"], 18)

    def test_low_stock_report_flags_scarce_items(self):
        self.assertEqual(self.run_json("report-low-stock"), [])
        self.run_cli("mark-condition", "R003", "damaged", "1")
        names = [row["name"] for row in self.run_json("report-low-stock")]
        self.assertEqual(names, ["Headset"])

    def test_inventory_report_rolls_up_by_category(self):
        payload = self.run_json("report-inventory")
        categories = {row["category"] for row in payload["categories"]}
        self.assertEqual(categories, {"Accessories", "Electronics"})

    def test_most_borrowed_is_empty_without_loans(self):
        self.assertEqual(self.run_json("report-most-borrowed"), [])


class JsonOutputTests(CliTestCase):
    def test_json_flag_emits_parseable_output(self):
        self.seed()
        code, out, err = self.run_cli("--json", "list-resources")
        self.assertEqual(code, 0, err)
        self.assertIsInstance(json.loads(out), list)

    def test_errors_go_to_stderr_not_stdout(self):
        self.seed()
        code, out, err = self.run_cli("mark-condition", "R001", "exploded", "1")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.strip())

    def test_actor_is_recorded_on_written_events(self):
        self.seed()
        self.run_cli("--actor", "grace", "add-category", "Lab Gear")
        store = Store.open(self.data_dir)
        self.assertEqual(store.log.read_all()[-1].actor, "grace")


if __name__ == "__main__":
    unittest.main()
