import json
import concurrent.futures
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winux.core.processes import ProcessManager


class ProcessManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_file = Path(self.temp_dir.name) / "processes.json"
        self.manager = ProcessManager(state_file=self.state_file)

    def start_process(self):
        process = subprocess.Popen(["sleep", "60"])
        self.addCleanup(self.cleanup_process, process)
        return process

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
        process.wait()

    def register_process(self, process):
        return self.manager.register(
            pid=process.pid,
            application="Test Application",
            prefix="test-prefix",
            runtime="test-runtime",
            executable="/test/app.exe",
            log="/tmp/test.log",
        )

    def test_register_persists_process_metadata(self):
        process = self.start_process()

        record = self.register_process(process)

        self.assertEqual(record["pid"], process.pid)
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["application"], "Test Application")
        self.assertEqual(record["prefix"], "test-prefix")
        self.assertTrue(self.state_file.is_file())

        stored = json.loads(self.state_file.read_text())
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], record["id"])
        self.assertEqual(
            self.state_file.stat().st_mode & 0o777,
            0o600,
        )

    def test_concurrent_registrations_preserve_all_process_records(self):
        processes = [self.start_process() for _ in range(6)]
        managers = [
            ProcessManager(state_file=self.state_file)
            for _ in processes
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(
                lambda pair: pair[0].register(
                    pid=pair[1].pid,
                    application="Concurrent App",
                    prefix="test-prefix",
                    runtime="test-runtime",
                    executable="/test/app.exe",
                ),
                zip(managers, processes),
            ))

        stored = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 6)
        self.assertEqual(len(stored), 6)
        self.assertEqual(
            {item["id"] for item in stored},
            {item["id"] for item in records},
        )
        self.assertEqual(
            self.manager.lock_file.stat().st_mode & 0o777,
            0o600,
        )

    def test_state_lock_rejects_symbolic_link(self):
        target = Path(self.temp_dir.name) / "outside.lock"
        target.write_text("", encoding="utf-8")
        self.manager.lock_file.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "must not be a symbolic link"):
            with self.manager._state_lock():
                pass

    def test_state_write_fsyncs_file_and_parent_directory(self):
        with patch("winux.core.processes.os.fsync") as fsync:
            self.manager._write_records([])

        self.assertEqual(fsync.call_count, 2)

    def test_list_reports_running_process(self):
        process = self.start_process()

        record = self.register_process(process)

        records = self.manager.list()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], record["id"])
        self.assertEqual(records[0]["status"], "running")

    def test_stop_terminates_registered_process(self):
        process = self.start_process()
        record = self.register_process(process)

        result = self.manager.stop(
            record["id"],
            timeout=2,
        )

        process.wait(timeout=3)

        self.assertTrue(result["stopped"])
        self.assertEqual(result["status"], "exited")

    def test_stop_force_kills_process_ignoring_sigterm(self):
        process = subprocess.Popen([
            "python",
            "-c",
            (
                "import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(60)"
            ),
        ])
        self.addCleanup(self.cleanup_process, process)
        record = self.register_process(process)

        result = self.manager.stop(
            record["id"],
            timeout=0,
            force=True,
        )

        process.wait(timeout=3)

        self.assertTrue(result["stopped"])
        self.assertTrue(result["forced"])
        self.assertEqual(result["status"], "exited")

    def test_cleanup_removes_exited_process_records(self):
        process = self.start_process()
        self.register_process(process)

        process.terminate()
        process.wait(timeout=3)

        result = self.manager.cleanup()

        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(self.manager.list(), [])

    def test_stop_rejects_invalid_timeouts(self):
        process = self.start_process()
        record = self.register_process(process)

        for timeout in (float("nan"), float("inf"), float("-inf"), -1, True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    self.manager.stop(record["id"], timeout=timeout)

        self.assertIsNone(process.poll())

    def test_pid_reuse_is_detected_as_stale(self):
        process = self.start_process()

        record = self.register_process(process)

        with patch.object(
            self.manager,
            "_process_start_time",
            return_value="different-start-time",
        ):
            self.assertEqual(
                self.manager.get(record["id"])["status"],
                "stale",
            )

            result = self.manager.stop(record["id"], timeout=0)
            self.assertEqual(result["status"], "stale")
            self.assertFalse(result["stopped"])

        self.assertIsNone(process.poll())

    def test_cleanup_removes_stale_records(self):
        process = self.start_process()

        self.register_process(process)

        with patch.object(
            self.manager,
            "_process_start_time",
            return_value="different-start-time",
        ):
            result = self.manager.cleanup()

        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(self.manager.list(), [])

    def test_register_rejects_nonexistent_process(self):
        with self.assertRaises(ProcessLookupError):
            self.manager.register(
                pid=999999999,
                application="Missing",
                prefix="test",
                runtime="test",
                executable="/missing.exe",
            )

    def test_get_rejects_unknown_process_id(self):
        with self.assertRaises(KeyError):
            self.manager.get("unknown")

    def test_state_file_rejects_invalid_process_identity(self):
        process = self.start_process()
        record = self.register_process(process)
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        data[0]["pid"] = True
        self.state_file.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "process identity"):
            self.manager.list()

    def test_state_file_rejects_malformed_process_start_time(self):
        process = self.start_process()
        self.register_process(process)
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        data[0]["process_start_time"] = "../unexpected"
        self.state_file.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "start time"):
            self.manager.list()

    def test_state_file_rejects_malformed_record_id(self):
        process = self.start_process()
        self.register_process(process)
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        data[0]["id"] = "not-an-id"
        self.state_file.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "record ID"):
            self.manager.list()

    def test_state_file_rejects_symlink_parent_on_read(self):
        real_parent = Path(self.temp_dir.name) / "real-parent"
        real_parent.mkdir()
        target = real_parent / "processes.json"
        target.write_text("[]", encoding="utf-8")
        link = Path(self.temp_dir.name) / "linked-parent"
        link.symlink_to(real_parent, target_is_directory=True)

        manager = ProcessManager(state_file=self.state_file)
        manager.state_file = link / "processes.json"
        with self.assertRaisesRegex(ValueError, "symlinks"):
            manager.list()

    def test_state_file_rejects_symlink_parent_on_write(self):
        real_parent = Path(self.temp_dir.name) / "real-parent"
        real_parent.mkdir()
        link = Path(self.temp_dir.name) / "linked-parent"
        link.symlink_to(real_parent, target_is_directory=True)

        manager = ProcessManager(state_file=self.state_file)
        manager.state_file = link / "processes.json"
        with self.assertRaisesRegex(ValueError, "symlinks"):
            manager._write_records([])

    def test_state_file_rejects_dangling_symlink(self):
        target = Path(self.temp_dir.name) / "missing-target.json"
        self.state_file.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.manager.list()

    def test_state_path_rejects_directory_instead_of_file(self):
        self.state_file.mkdir()

        with self.assertRaisesRegex(ValueError, "regular file"):
            self.manager.list()

    def test_state_file_must_not_be_a_symlink(self):
        target = Path(self.temp_dir.name) / "target.json"
        target.write_text("[]", encoding="utf-8")

        self.state_file.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.manager.list()


if __name__ == "__main__":
    unittest.main()
