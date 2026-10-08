from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lender.cli.app import build_parser, main
from lender.domain.errors import StorageError
from lender.domain.events import EventType
from lender.storage.locking import store_lock
from lender.storage.paths import DataPaths
from lender.storage.store import Store

PROJECT_ROOT = Path(__file__).resolve().parents[1]

HOLDER_SCRIPT = (
    "import sys, time\n"
    "from lender.storage.locking import store_lock\n"
    "from lender.storage.paths import DataPaths\n"
    "paths = DataPaths.at(sys.argv[1])\n"
    "with store_lock(paths):\n"
    "    print('held', flush=True)\n"
    "    time.sleep(float(sys.argv[2]))\n"
)

READ_ONLY_COMMANDS = frozenset(
    {
        "menu",
        "list-categories",
        "list-subcategories",
        "list-resources",
        "find-resource",
        "find-by-category",
        "list-borrowers",
        "find-borrower",
        "list-groups",
        "history",
        "overdue",
        "report-borrower-history",
        "report-store-status",
        "report-inventory",
        "report-low-stock",
        "report-most-borrowed",
        "export",
    }
)

SAMPLE_ARGV = {
    "menu": [],
    "seed": [],
    "export": ["--out", "out.json"],
    "import": ["payload.json"],
    "add-category": ["Lab Gear"],
    "update-category": ["electronics", "--name", "Gear"],
    "remove-category": ["electronics"],
    "add-subcategory": ["electronics", "Laptops"],
    "update-subcategory": ["laptops", "--name", "Laptops"],
    "remove-subcategory": ["laptops"],
    "list-categories": [],
    "list-subcategories": [],
    "add-resource": [
        "--name",
        "Thing",
        "--category",
        "electronics",
        "--subcategory",
        "laptops",
        "--total",
        "1",
    ],
    "update-resource": ["R001"],
    "remove-resource": ["R001"],
    "restore-resource": ["R001"],
    "list-resources": [],
    "find-resource": ["Laptop"],
    "find-by-category": ["electronics"],
    "mark-condition": ["R001", "faulty", "1"],
    "add-fellow": ["Ada", "--cohort", "july-cohort"],
    "add-piscine": ["Alan", "--trial", "january-2026-trial"],
    "list-borrowers": [],
    "find-borrower": ["Ada"],
    "add-cohort": ["cluster-5-mar"],
    "add-trial": ["november-2026-trial"],
    "list-groups": [],
    "checkout": ["R001", "F001", "1"],
    "return": ["T000001"],
    "history": [],
    "overdue": [],
    "report-borrower-history": ["F001"],
    "report-store-status": [],
    "report-inventory": [],
    "report-low-stock": [],
    "report-most-borrowed": [],
}

RACE_ITERATIONS = 5
LOCK_WAIT = 0.3


class LockedStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = str(Path(self._tmp.name) / "data")
        self.paths = DataPaths.at(self.data_dir)
        self.paths.ensure()

    def run_cli(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--data-dir", self.data_dir, *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def seed(self):
        code, _, err = self.run_cli("seed")
        self.assertEqual(code, 0, err)
        return code

    def start_holder(self, seconds=10.0):
        process = subprocess.Popen(
            [sys.executable, "-c", HOLDER_SCRIPT, self.data_dir, str(seconds)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.stop, process)
        ready = process.stdout.readline().strip()
        if ready != "held":
            process.kill()
            self.fail(f"the lock holder did not start: {process.stderr.read()}")
        return process

    def stop(self, process):
        process.kill()
        process.wait(timeout=30)
        process.stdout.close()
        process.stderr.close()

    def spawn_cli(self, *argv):
        return subprocess.Popen(
            [sys.executable, "-m", "lender", "--data-dir", self.data_dir, *argv],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


class LockFileTests(LockedStoreTestCase):
    def test_the_lock_file_sits_in_the_data_directory(self):
        with store_lock(self.paths):
            self.assertTrue(self.paths.lock_file.exists())
            self.assertEqual(self.paths.lock_file.parent, self.paths.root)

    def test_the_lock_is_exclusive_across_processes(self):
        self.start_holder()
        with self.assertRaises(StorageError):
            with store_lock(self.paths, timeout=LOCK_WAIT):
                self.fail("the lock was handed out twice")

    def test_the_busy_message_names_the_data_directory(self):
        self.start_holder()
        with self.assertRaises(StorageError) as caught:
            with store_lock(self.paths, timeout=LOCK_WAIT):
                pass
        self.assertIn(str(self.paths.root), str(caught.exception))
        self.assertIn("in use by another lender process", str(caught.exception))

    def test_the_lock_error_is_a_storage_error(self):
        self.start_holder()
        with self.assertRaises(StorageError) as caught:
            with store_lock(self.paths, timeout=LOCK_WAIT):
                pass
        self.assertEqual(caught.exception.exit_code, 6)

    def test_killing_the_holder_releases_the_lock(self):
        process = self.start_holder()
        process.kill()
        process.wait(timeout=10)
        with store_lock(self.paths, timeout=5.0):
            pass

    def test_the_lock_is_released_after_normal_use(self):
        with store_lock(self.paths, timeout=1.0):
            pass
        with store_lock(self.paths, timeout=1.0):
            pass


class CommandClassificationTests(unittest.TestCase):
    def test_every_command_is_classified(self):
        parser = build_parser()
        found = set()
        for name, extra in SAMPLE_ARGV.items():
            with self.subTest(command=name):
                args = parser.parse_args([name, *extra])
                found.add(name)
                self.assertEqual(
                    bool(args.writes),
                    name not in READ_ONLY_COMMANDS,
                    f"{name} is marked the wrong way",
                )
        self.assertEqual(found, set(SAMPLE_ARGV))
        self.assertEqual(len(SAMPLE_ARGV), 36)

    def test_the_read_only_set_is_the_expected_one(self):
        self.assertEqual(len(READ_ONLY_COMMANDS), 17)
        self.assertNotIn("checkout", READ_ONLY_COMMANDS)
        self.assertNotIn("return", READ_ONLY_COMMANDS)
        self.assertNotIn("seed", READ_ONLY_COMMANDS)
        self.assertNotIn("import", READ_ONLY_COMMANDS)


class BusyStoreCommandTests(LockedStoreTestCase):
    def test_a_busy_store_exits_with_the_storage_code(self):
        self.seed()
        self.start_holder()
        with mock.patch("lender.storage.locking.LOCK_TIMEOUT", LOCK_WAIT):
            code, _, err = self.run_cli("checkout", "R002", "F001", "4")
        self.assertEqual(code, 6, err)
        self.assertIn("in use by another lender process", err)

    def test_a_busy_store_is_not_modified(self):
        self.seed()
        before = Store.open(self.data_dir).state.resources["R002"].to_dict()
        self.start_holder()
        with mock.patch("lender.storage.locking.LOCK_TIMEOUT", LOCK_WAIT):
            self.run_cli("checkout", "R002", "F001", "4")
        after = Store.open(self.data_dir).state.resources["R002"].to_dict()
        self.assertEqual(before, after)

    def test_read_only_commands_still_work_while_the_store_is_locked(self):
        self.seed()
        self.start_holder()
        with mock.patch("lender.storage.locking.LOCK_TIMEOUT", LOCK_WAIT):
            code, out, err = self.run_cli("list-resources")
        self.assertEqual(code, 0, err)
        self.assertIn("R001", out)

    def test_the_lock_is_not_leaked_between_commands(self):
        self.seed()
        with mock.patch("lender.storage.locking.LOCK_TIMEOUT", LOCK_WAIT):
            first, _, err = self.run_cli("checkout", "R002", "F001", "1")
            self.assertEqual(first, 0, err)
            second, _, err = self.run_cli("checkout", "R002", "F002", "1")
            self.assertEqual(second, 0, err)
        state = Store.open(self.data_dir).state
        self.assertEqual(state.resources["R002"].available_quantity, 3)


class ConcurrentCheckoutTests(LockedStoreTestCase):
    def test_two_simultaneous_checkouts_cannot_both_win(self):
        for attempt in range(RACE_ITERATIONS):
            with self.subTest(attempt=attempt):
                self._one_race()

    def _one_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.data_dir = str(Path(tmp) / "data")
            self.paths = DataPaths.at(self.data_dir)
            self.paths.ensure()
            self.seed()

            first = self.spawn_cli("checkout", "R002", "F001", "4")
            second = self.spawn_cli("checkout", "R002", "F002", "4")
            first.communicate(timeout=60)
            second.communicate(timeout=60)
            codes = sorted([first.returncode, second.returncode])

            self.assertEqual(codes[0], 0, f"nobody won: {codes}")
            self.assertIn(codes[1], (4, 6), f"the loser was not refused: {codes}")

            store = Store.open(self.data_dir)
            keyboard = store.state.resources["R002"]
            self.assertEqual(keyboard.available_quantity, 1)
            self.assertEqual(keyboard.issued_quantity, 4)
            keyboard.check_invariant()

            loans = [loan for loan in store.state.loans.values() if loan.resource_id == "R002"]
            self.assertEqual(len(loans), 1)
            self.assertEqual(loans[0].quantity, 4)

            events = store.log.read_all()
            event_ids = [event.event_id for event in events]
            self.assertEqual(len(event_ids), len(set(event_ids)))

            checked_out = [
                event.payload["transaction_id"]
                for event in events
                if event.event_type is EventType.LOAN_CHECKED_OUT
                and event.payload["resource_id"] == "R002"
            ]
            self.assertEqual(len(checked_out), 1)
            self.assertEqual(len(checked_out), len(set(checked_out)))


if __name__ == "__main__":
    unittest.main()
