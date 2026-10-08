from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from lender.cli.app import build_parser, main
from lender.cli.menu import ENTRIES
from lender.storage.store import Store
from lender.validators.dates import parse_datetime


class InterruptingInput:
    def __init__(self, *lines):
        self._lines = list(lines)

    def readline(self, *args):
        if self._lines:
            return self._lines.pop(0) + "\n"
        raise KeyboardInterrupt


class MenuTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = str(Path(self._tmp.name) / "data")
        self._stdin = sys.stdin
        self.addCleanup(setattr, sys, "stdin", self._stdin)

    def menu(self, *lines, args=(), stdin=None):
        sys.stdin = stdin if stdin is not None else io.StringIO("\n".join(lines) + "\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--data-dir", self.data_dir, *args, "menu"])
        return code, stdout.getvalue(), stderr.getvalue()

    def seeded(self, *lines, **kwargs):
        return self.menu("27", *lines, **kwargs)

    def state(self):
        return Store.open(self.data_dir).state


class MenuLoopTests(MenuTestCase):
    def test_zero_leaves_the_menu(self):
        code, out, err = self.menu("0")
        self.assertEqual(code, 0, err)
        self.assertIn("Leaving the menu.", out)

    def test_the_exit_word_leaves_the_menu(self):
        for word in ("exit", "quit", "q", "bye", "EXIT"):
            with self.subTest(word=word):
                code, out, err = self.menu(word)
                self.assertEqual(code, 0, err)
                self.assertIn("Leaving the menu.", out)

    def test_running_out_of_input_leaves_the_menu(self):
        code, out, err = self.menu()
        self.assertEqual(code, 0, err)
        self.assertIn("Leaving the menu.", out)

    def test_control_c_leaves_the_menu(self):
        code, out, err = self.menu(stdin=InterruptingInput())
        self.assertEqual(code, 0, err)
        self.assertIn("Leaving the menu.", out)

    def test_the_menu_lists_every_action(self):
        code, out, err = self.menu("0")
        for index, entry in enumerate(ENTRIES, 1):
            with self.subTest(entry=entry.key):
                self.assertIn(f"{index:>2}. {entry.title}", out)

    def test_the_menu_shows_which_store_it_writes_to(self):
        code, out, err = self.menu("0")
        self.assertIn(self.data_dir, out)

    def test_the_menu_keeps_looping_until_exit(self):
        code, out, err = self.menu("27", "1", "23", "0")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("1. List every resource"), 4)
        self.assertEqual(out.count("Learn2Earn Lender — equipment inventory"), 1)

    def test_a_blank_line_redraws_the_menu_without_complaint(self):
        code, out, err = self.menu("", "", "0")
        self.assertEqual(err, "")
        self.assertEqual(out.count("1. List every resource"), 3)

    def test_an_unknown_option_is_answered_with_a_warning(self):
        code, out, err = self.menu("banana", "31", "0")
        self.assertEqual(code, 0)
        self.assertIn("'banana' is not one of the options", err)
        self.assertIn("'31' is not one of the options", err)
        self.assertIn("from 1 to 30", err)
        self.assertIn("Leaving the menu.", out)

    def test_a_question_mark_prints_the_command_list(self):
        code, out, err = self.menu("?", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("usage: lender", out)
        self.assertIn("report-low-stock", out)

    def test_an_action_key_may_be_typed_instead_of_its_number(self):
        code, out, err = self.menu("27", "report-low-stock", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("Seeded", out)
        self.assertEqual(err, "")


class MenuActionTests(MenuTestCase):
    def test_listing_resources_shows_the_seeded_stock(self):
        code, out, err = self.seeded("1", "0")
        self.assertIn("R001  Laptop", out)
        self.assertIn("R002  Keyboard", out)

    def test_adding_a_resource_asks_for_each_field(self):
        code, out, err = self.seeded(
            "4", "Dell Monitor", "Electronics", "laptop", "3", "", "", "0"
        )
        self.assertEqual(code, 0, err)
        created = [r for r in self.state().resources.values() if r.name == "Dell Monitor"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].total_quantity, 3)
        self.assertEqual(created[0].available_quantity, 3)

    def test_checkout_and_return_through_the_menu(self):
        code, out, err = self.seeded(
            "14", "R001", "F001", "2", "", "",
            "15", "T000001", "", "", "",
            "0",
        )
        self.assertEqual(code, 0, err)
        self.assertIn("Checked out 2 unit(s)", out)
        loan = self.state().loans["T000001"]
        self.assertTrue(loan.is_returned)

    def test_a_blank_loan_period_takes_the_default(self):
        code, out, err = self.seeded("14", "R001", "F001", "1", "", "", "0")
        self.assertEqual(code, 0, err)
        loan = self.state().loans["T000001"]
        self.assertEqual(
            parse_datetime(loan.due_at), parse_datetime(loan.issued_at) + timedelta(days=14)
        )

    def test_a_search_is_case_insensitive(self):
        code, out, err = self.seeded("2", "LAPTOP", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("R001  Laptop", out)

    def test_filtering_by_category_uses_the_same_rules_as_the_cli(self):
        code, out, err = self.seeded("3", "accessories", "0")
        self.assertEqual(code, 0, err)
        self.assertNotIn("R001  Laptop", out)

    def test_recording_a_condition_moves_units_out_of_availability(self):
        code, out, err = self.seeded("6", "R002", "faulty", "1", "dead keys", "0")
        self.assertEqual(code, 0, err)
        resource = self.state().resources["R002"]
        self.assertEqual(resource.condition_counts.get("faulty"), 1)
        self.assertEqual(resource.available_quantity, resource.total_quantity - 1)

    def test_the_session_actor_is_recorded_on_written_events(self):
        code, out, err = self.menu("25", "Lab Gear", "0", args=("--actor", "grace"))
        self.assertEqual(code, 0, err)
        self.assertEqual(Store.open(self.data_dir).log.read_all()[-1].actor, "grace")


class MenuInputTests(MenuTestCase):
    def test_a_bad_number_is_reasked(self):
        code, out, err = self.seeded("14", "R001", "F001", "two", "2", "", "", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("must be a whole number, got 'two'", err)
        self.assertIn("Checked out 2 unit(s)", out)

    def test_a_blank_required_field_is_reasked(self):
        code, out, err = self.seeded("14", "", "R001", "F001", "2", "", "", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("Resource ID is required.", err)
        self.assertIn("Checked out 2 unit(s)", out)

    def test_a_value_outside_the_choices_is_reasked(self):
        code, out, err = self.seeded("6", "R001", "exploded", "faulty", "1", "", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("Condition must be one of", err)
        self.assertIn("faulty", err)

    def test_a_rejected_action_does_not_end_the_session(self):
        code, out, err = self.seeded(
            "14", "R001", "F001", "999", "", "",
            "1",
            "0",
        )
        self.assertEqual(code, 0)
        self.assertIn("only", err)
        self.assertIn("available", err)
        self.assertIn("R001  Laptop", out)
        self.assertEqual(len(self.state().loans), 0)

    def test_control_c_abandons_the_action_and_returns_to_the_menu(self):
        code, out, err = self.seeded(stdin=InterruptingInput("14"))
        self.assertEqual(code, 0)
        self.assertIn("Cancelled.", out)
        self.assertEqual(len(self.state().loans), 0)

    def test_an_unknown_id_is_reported_by_the_domain(self):
        code, out, err = self.seeded("14", "R999", "F001", "1", "", "", "1", "0")
        self.assertEqual(code, 0)
        self.assertIn("no resource with ID 'R999'", err)
        self.assertIn("R001  Laptop", out)


class MenuDefinitionTests(unittest.TestCase):
    def argv_for(self, entry) -> list[str]:
        argv = list(entry.command)
        for field in entry.fields:
            if field.optional:
                continue
            value = field.choices[0] if field.choices else ("1" if field.kind is int else "x")
            argv.extend([field.flag, value] if field.flag else [value])
        return argv

    def test_every_entry_matches_the_command_it_dispatches_to(self):
        parser = build_parser()
        for entry in ENTRIES:
            with self.subTest(entry=entry.key):
                argv = self.argv_for(entry)
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        args = parser.parse_args(argv)
                except SystemExit as exc:
                    self.fail(
                        f"{entry.key} builds {argv}, which the parser rejects ({exc.code})"
                    )
                self.assertTrue(callable(args.handler))

    def test_the_keys_are_unique(self):
        keys = [entry.key for entry in ENTRIES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_entry_is_filed_under_a_section(self):
        for entry in ENTRIES:
            with self.subTest(entry=entry.key):
                self.assertTrue(entry.section)
                self.assertTrue(entry.title)


if __name__ == "__main__":
    unittest.main()
