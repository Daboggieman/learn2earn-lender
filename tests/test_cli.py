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
        for command in (
            "menu",
            "add-resource",
            "mark-condition",
            "report-low-stock",
            "seed",
            "export",
            "import",
        ):
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


class PeopleCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_list_groups_shows_seeded_cohorts_and_trials(self):
        code, out, err = self.run_cli("list-groups")
        self.assertEqual(code, 0, err)
        self.assertIn("cluster-1-feb", out)
        self.assertIn("trial-period-1", out)

    def test_list_groups_filters_by_type(self):
        payload = self.run_json("list-groups", "--type", "trial")
        self.assertTrue(all(group["type"] == "trial" for group in payload))
        self.assertEqual(len(payload), 6)

    def test_add_cohort_creates_a_group(self):
        payload = self.run_json("add-cohort", "cluster-5-mar")
        self.assertEqual(payload["name"], "cluster-5-mar")
        self.assertEqual(payload["type"], "cohort")

    def test_add_trial_creates_a_group(self):
        payload = self.run_json("add-trial", "trial-period-7")
        self.assertEqual(payload["type"], "trial")

    def test_duplicate_group_name_conflicts(self):
        code, out, err = self.run_cli("add-cohort", "cluster-1-feb")
        self.assertEqual(code, 4)

    def test_add_fellow_lands_in_the_named_cohort(self):
        payload = self.run_json("add-fellow", "Ada Lovelace", "--cohort", "cluster-1-feb")
        self.assertEqual(payload["id"], "F004")
        self.assertEqual(payload["type"], "fellow")
        self.assertEqual(payload["group_name"], "cluster-1-feb")

    def test_add_piscine_uses_a_p_prefixed_id(self):
        payload = self.run_json("add-piscine", "Alan Turing", "--trial", "trial-period-1")
        self.assertEqual(payload["id"], "P001")
        self.assertEqual(payload["type"], "piscine")

    def test_add_fellow_to_a_trial_group_is_refused(self):
        code, out, err = self.run_cli(
            "add-fellow", "Grace Hopper", "--cohort", "trial-period-1"
        )
        self.assertEqual(code, 3)

    def test_add_fellow_to_an_unknown_cohort_is_refused(self):
        code, out, err = self.run_cli("add-fellow", "Nobody", "--cohort", "ghost")
        self.assertEqual(code, 3)

    def test_duplicate_borrower_name_conflicts(self):
        self.run_cli("add-fellow", "Ada Lovelace", "--cohort", "cluster-1-feb")
        code, out, err = self.run_cli("add-fellow", "Ada Lovelace", "--cohort", "cluster-1-feb")
        self.assertEqual(code, 4)

    def test_list_borrowers_shows_the_seeded_borrowers(self):
        code, out, err = self.run_cli("list-borrowers")
        self.assertEqual(code, 0, err)
        for name in ("Ada", "John", "Grace"):
            self.assertIn(name, out)

    def test_list_borrowers_filters_by_cohort(self):
        payload = self.run_json("list-borrowers", "--cohort", "cluster-1-feb")
        self.assertEqual([row["id"] for row in payload], ["F001"])

    def test_list_borrowers_filters_by_type(self):
        self.run_cli("add-piscine", "Alan Turing", "--trial", "trial-period-1")
        payload = self.run_json("list-borrowers", "--type", "piscine")
        self.assertEqual([row["id"] for row in payload], ["P001"])

    def test_list_borrowers_rejects_both_group_filters(self):
        code, out, err = self.run_cli(
            "list-borrowers", "--cohort", "cluster-1-feb", "--trial", "trial-period-1"
        )
        self.assertEqual(code, 2)

    def test_find_borrower_matches_a_partial_name(self):
        payload = self.run_json("find-borrower", "ada")
        self.assertEqual([row["id"] for row in payload], ["F001"])

    def test_find_borrower_with_no_match_is_an_empty_result(self):
        code, out, err = self.run_cli("find-borrower", "nobody")
        self.assertEqual(code, 0)
        self.assertIn("No borrower matches", out)

    def test_borrowers_survive_a_reseed_of_the_log(self):
        self.run_cli("add-fellow", "Ada Lovelace", "--cohort", "cluster-1-feb")
        store = Store.open(self.data_dir)
        self.assertIn("F004", store.state.people)
        self.assertEqual(store.state.people["F004"].name, "Ada Lovelace")


class LendingCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_checkout_issues_units(self):
        payload = self.run_json("checkout", "R001", "F001", "2", "--days", "7")
        self.assertEqual(payload["transaction_id"], "T000001")
        self.assertEqual(payload["quantity"], 2)
        self.assertEqual(payload["status"], "active")

    def test_checkout_reduces_availability(self):
        self.run_cli("checkout", "R001", "F001", "3")
        payload = self.run_json("find-resource", "R001")
        self.assertEqual(payload[0]["available_quantity"], 7)
        self.assertEqual(payload[0]["issued_quantity"], 3)

    def test_checkout_beyond_availability_is_refused(self):
        code, out, err = self.run_cli("checkout", "R001", "F001", "99")
        self.assertEqual(code, 4)

    def test_checkout_for_an_unknown_borrower_is_refused(self):
        code, out, err = self.run_cli("checkout", "R001", "F999", "1")
        self.assertEqual(code, 3)
        self.assertNotIn("event log", err)

    def test_checkout_for_an_unknown_resource_is_refused(self):
        code, out, err = self.run_cli("checkout", "R999", "F001", "1")
        self.assertEqual(code, 3)

    def test_checkout_rejects_both_due_and_days(self):
        code, out, err = self.run_cli(
            "checkout", "R001", "F001", "1", "--due", "2027-01-01", "--days", "7"
        )
        self.assertEqual(code, 2)

    def test_checkout_with_a_past_due_date_is_refused(self):
        code, out, err = self.run_cli("checkout", "R001", "F001", "1", "--due", "2020-01-01")
        self.assertEqual(code, 2)

    def test_full_return_closes_the_loan(self):
        self.run_cli("checkout", "R001", "F001", "2")
        payload = self.run_json("return", "T000001")
        self.assertEqual(payload["status"], "returned")
        self.assertEqual(payload["outstanding_quantity"], 0)

    def test_partial_then_final_return(self):
        self.run_cli("checkout", "R001", "F001", "3")
        partial = self.run_json("return", "T000001", "1")
        self.assertEqual(partial["outstanding_quantity"], 2)
        self.assertEqual(partial["status"], "active")
        final = self.run_json("return", "T000001")
        self.assertEqual(final["status"], "returned")

    def test_returning_damaged_units_keeps_them_unavailable(self):
        self.run_cli("checkout", "R001", "F001", "2")
        self.run_cli("return", "T000001", "2", "--condition", "damaged")
        payload = self.run_json("find-resource", "R001")
        self.assertEqual(payload[0]["available_quantity"], 8)
        self.assertEqual(payload[0]["condition_counts"]["damaged"], 2)

    def test_over_return_is_refused(self):
        self.run_cli("checkout", "R001", "F001", "2")
        code, out, err = self.run_cli("return", "T000001", "5")
        self.assertEqual(code, 2)

    def test_returning_twice_is_refused(self):
        self.run_cli("checkout", "R001", "F001", "1")
        self.run_cli("return", "T000001")
        code, out, err = self.run_cli("return", "T000001")
        self.assertEqual(code, 4)

    def test_returning_an_unknown_loan_is_refused(self):
        code, out, err = self.run_cli("return", "T999999")
        self.assertEqual(code, 3)

    def test_history_lists_every_loan(self):
        self.run_cli("checkout", "R001", "F001", "1")
        self.run_cli("checkout", "R002", "F002", "1")
        payload = self.run_json("history")
        self.assertEqual(
            [row["transaction_id"] for row in payload], ["T000001", "T000002"]
        )

    def test_history_filters_by_borrower(self):
        self.run_cli("checkout", "R001", "F001", "1")
        self.run_cli("checkout", "R002", "F002", "1")
        payload = self.run_json("history", "--borrower", "F001")
        self.assertEqual([row["borrower_id"] for row in payload], ["F001"])

    def test_history_open_only_hides_returned_loans(self):
        self.run_cli("checkout", "R001", "F001", "1")
        self.run_cli("checkout", "R002", "F002", "1")
        self.run_cli("return", "T000001")
        payload = self.run_json("history", "--open")
        self.assertEqual([row["transaction_id"] for row in payload], ["T000002"])

    def test_history_is_empty_before_any_lending(self):
        code, out, err = self.run_cli("history")
        self.assertEqual(code, 0)
        self.assertIn("No lending transactions", out)

    def test_overdue_is_clear_when_nothing_is_late(self):
        self.run_cli("checkout", "R001", "F001", "1", "--days", "7")
        code, out, err = self.run_cli("overdue")
        self.assertEqual(code, 0)
        self.assertIn("No overdue loans", out)

    def test_borrower_history_summarises_activity(self):
        self.run_cli("checkout", "R001", "F001", "2")
        self.run_cli("checkout", "R002", "F001", "1")
        self.run_cli("return", "T000001")
        payload = self.run_json("report-borrower-history", "F001")
        self.assertEqual(payload["total_loans"], 2)
        self.assertEqual(payload["lifetime_units"], 3)
        self.assertEqual(payload["open_loan_ids"], ["T000002"])
        self.assertEqual(payload["overdue_loan_ids"], [])

    def test_borrower_history_for_an_unknown_borrower_is_refused(self):
        code, out, err = self.run_cli("report-borrower-history", "F999")
        self.assertEqual(code, 3)

    def test_lending_survives_a_log_replay(self):
        self.run_cli("checkout", "R001", "F001", "2")
        store = Store.open(self.data_dir)
        self.assertEqual(store.state.resources["R001"].issued_quantity, 2)
        self.assertEqual(len(store.state.loans), 1)


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


class TransferCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self._other_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._other_tmp.cleanup)
        self.other_dir = str(Path(self._other_tmp.name) / "data")
        self.files = Path(self._other_tmp.name) / "files"
        self.files.mkdir()

    def run_into(self, data_dir, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--data-dir", data_dir, *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def snapshot(self, data_dir):
        state = Store.open(data_dir).state
        return {
            name: {key: value.to_dict() for key, value in getattr(state, name).items()}
            for name in ("taxonomy", "groups", "resources", "people", "loans")
        }

    def export_json(self):
        path = self.files / "backup.json"
        code, out, err = self.run_cli("export", "--out", str(path))
        self.assertEqual(code, 0, err)
        return path

    def test_export_json_reports_the_event_count(self):
        payload = self.run_json("export", "--out", str(self.files / "backup.json"))
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["events"], len(Store.open(self.data_dir).log.read_all()))

    def test_export_json_writes_a_readable_file(self):
        path = self.export_json()
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["format"],
            "learn2earn-lender/1",
        )

    def test_json_round_trips_through_the_cli(self):
        path = self.export_json()
        code, out, err = self.run_into(self.other_dir, "import", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("Imported", out)
        self.assertEqual(self.snapshot(self.other_dir), self.snapshot(self.data_dir))

    def test_importing_twice_reports_what_it_skipped(self):
        path = self.export_json()
        self.run_into(self.other_dir, "import", str(path))
        payload = self.run_into(self.other_dir, "--json", "import", str(path))[1]
        self.assertEqual(json.loads(payload)["imported"], 0)

    def test_replace_mode_discards_the_destination_first(self):
        path = self.export_json()
        self.run_into(self.other_dir, "seed")
        self.run_into(self.other_dir, "add-category", "Scratch")
        code, out, err = self.run_into(
            self.other_dir, "import", str(path), "--mode", "replace"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("Replaced", out)
        self.assertEqual(self.snapshot(self.other_dir), self.snapshot(self.data_dir))

    def test_csv_dataset_is_inferred_from_the_file_name(self):
        path = self.files / "resources.csv"
        payload = self.run_json("export", "--out", str(path))
        self.assertEqual(payload["dataset"], "resources")
        self.assertNotIn("taxonomy", path.read_text(encoding="utf-8").splitlines()[0])

    def test_csv_datasets_round_trip_through_the_cli(self):
        for dataset in ("taxonomy", "groups", "resources", "people", "loans"):
            path = self.files / f"{dataset}.csv"
            code, out, err = self.run_cli("export", "--out", str(path))
            self.assertEqual(code, 0, err)
            code, out, err = self.run_into(self.other_dir, "import", str(path))
            self.assertEqual(code, 0, err)
        self.assertEqual(self.snapshot(self.other_dir), self.snapshot(self.data_dir))

    def test_an_explicit_format_overrides_the_file_name(self):
        path = self.files / "backup.txt"
        code, out, err = self.run_cli("export", "--out", str(path), "--format", "json")
        self.assertEqual(code, 0, err)
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["format"], "learn2earn-lender/1")
        self.assertTrue(document["events"])

    def test_an_unrecognisable_file_name_is_a_validation_error(self):
        code, out, err = self.run_cli("export", "--out", str(self.files / "backup.txt"))
        self.assertEqual(code, 2)
        self.assertIn("--format", err)

    def test_csv_without_an_identifiable_dataset_is_a_validation_error(self):
        code, out, err = self.run_cli("export", "--out", str(self.files / "dump.csv"))
        self.assertEqual(code, 2)
        self.assertIn("a dataset is required", err)

    def test_importing_a_missing_file_reports_a_storage_error(self):
        code, out, err = self.run_into(self.other_dir, "import", str(self.files / "nope.json"))
        self.assertEqual(code, 6)
        self.assertTrue(err.strip())

    def test_merging_a_dataset_twice_is_a_conflict(self):
        path = self.files / "taxonomy.csv"
        self.run_cli("export", "--out", str(path))
        self.run_into(self.other_dir, "import", str(path))
        code, out, err = self.run_into(self.other_dir, "import", str(path))
        self.assertEqual(code, 7)
        self.assertTrue(err.strip())


class ReportExportCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self._tmp_out = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_out.cleanup)
        self.files = Path(self._tmp_out.name)

    def test_store_status_writes_a_json_report(self):
        path = self.files / "status.json"
        summary = self.run_json("report-store-status", "--out", str(path))
        self.assertEqual(summary, {
            "path": str(path), "format": "json", "report": "store-status",
        })
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["report"], "store-status")
        self.assertEqual(document["payload"]["totals"]["total"], 18)

    def test_low_stock_writes_a_csv_report(self):
        self.run_cli("mark-condition", "R003", "damaged", "1")
        path = self.files / "low.csv"
        self.run_cli("report-low-stock", "--out", str(path))
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "id,name,category,available,total,needed")
        self.assertEqual(lines[1].split(",")[1], "Headset")

    def test_most_borrowed_csv_names_its_columns(self):
        path = self.files / "most.csv"
        code, out, err = self.run_cli("report-most-borrowed", "--out", str(path))
        self.assertEqual(code, 0, err)
        self.assertEqual(
            path.read_text(encoding="utf-8").splitlines()[0], "id,name,units_out"
        )

    def test_inventory_report_export_keeps_the_category_rollup(self):
        path = self.files / "inventory.json"
        self.run_cli("report-inventory", "--out", str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        self.assertEqual(
            {row["category"] for row in payload["categories"]},
            {"Accessories", "Electronics"},
        )

    def test_borrower_history_exports_its_loans(self):
        self.run_cli("checkout", "R001", "F001", "2")
        path = self.files / "history.csv"
        code, out, err = self.run_cli(
            "report-borrower-history", "F001", "--out", str(path)
        )
        self.assertEqual(code, 0, err)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "loan,resource,borrower,qty,out,issued,due,returned,status")
        self.assertEqual(len(lines), 2)

    def test_the_table_is_still_printed_next_to_the_file(self):
        self.run_cli("mark-condition", "R003", "damaged", "1")
        path = self.files / "low.csv"
        code, out, err = self.run_cli("report-low-stock", "--out", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("Headset", out)
        self.assertIn("Wrote 1 low-stock row(s)", out)

    def test_an_unrecognisable_file_name_is_a_validation_error(self):
        code, out, err = self.run_cli(
            "report-low-stock", "--out", str(self.files / "low.txt")
        )
        self.assertEqual(code, 2)
        self.assertIn("--format", err)

    def test_an_explicit_format_wins_over_the_file_name(self):
        path = self.files / "low.txt"
        code, out, err = self.run_cli(
            "report-low-stock", "--out", str(path), "--format", "csv"
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(path.read_text(encoding="utf-8").startswith("id,name"))

    def test_exporting_a_report_does_not_touch_the_transaction_log(self):
        self.run_cli("report-store-status", "--out", str(self.files / "status.json"))
        self.assertEqual(len(Store.open(self.data_dir).log.read_all()), 29)


if __name__ == "__main__":
    unittest.main()
