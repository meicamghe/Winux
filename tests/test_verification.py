import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from winux.core.verification import VerificationManager


class VerificationManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.prefix = Path(self.temp_dir.name)
        (self.prefix / "drive_c").mkdir()
        self.manager = VerificationManager()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_file_check_passes_when_file_exists(self):
        target = self.prefix / "drive_c" / "Program Files" / "Example"
        target.mkdir(parents=True)
        (target / "app.exe").write_bytes(b"test")

        result = self.manager.verify(
            {"checks": [{"type": "file", "path": "Program Files/Example/app.exe"}]},
            self.prefix,
        )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["checks"][0]["passed"])

    def test_file_check_fails_when_file_is_missing(self):
        result = self.manager.verify(
            {"checks": [{"type": "file", "path": "Example/app.exe"}]},
            self.prefix,
        )

        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["checks"][0]["passed"])

    def test_file_check_rejects_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "inside the Wine prefix"):
            self.manager.verify(
                {"checks": [{"type": "file", "path": "../../etc/passwd"}]},
                self.prefix,
            )

    def test_file_check_accepts_windows_relative_path(self):
        target = self.prefix / "drive_c" / "Program Files" / "Example"
        target.mkdir(parents=True)
        (target / "app.exe").write_bytes(b"test")

        result = self.manager.verify(
            {
                "checks": [{
                    "type": "file",
                    "path": r"Program Files\Example\app.exe",
                }]
            },
            self.prefix,
        )

        self.assertEqual(result["status"], "VERIFIED")

    def test_file_check_rejects_windows_absolute_and_drive_paths(self):
        invalid_paths = [
            r"C:\Windows\system32\cmd.exe",
            r"C:Windows\system32\cmd.exe",
            r"\\server\share\app.exe",
            r"\Windows\system32\cmd.exe",
            "/etc/passwd",
        ]

        for value in invalid_paths:
            with self.subTest(path=value):
                with self.assertRaisesRegex(ValueError, "inside the Wine prefix"):
                    self.manager.validate_profile({
                        "checks": [{"type": "file", "path": value}]
                    })

    def test_file_check_rejects_windows_backslash_traversal(self):
        with self.assertRaisesRegex(ValueError, "inside the Wine prefix"):
            self.manager.validate_profile({
                "checks": [{
                    "type": "file",
                    "path": r"Program Files\..\..\Windows\app.exe",
                }]
            })

    def test_process_check_detects_current_process(self):
        with patch("winux.core.verification.Path.iterdir") as iterdir, \
             patch("winux.core.verification.Path.read_bytes",
                   return_value=b"/usr/bin/example.exe\0"):
            iterdir.return_value = [Path("/proc/1234")]

            result = self.manager.verify(
                {"checks": [{"type": "process", "executable": "example.exe"}]},
                self.prefix,
            )

        self.assertEqual(result["status"], "VERIFIED")

    def test_process_check_detects_windows_executable_path(self):
        with patch("winux.core.verification.Path.iterdir") as iterdir:
            with patch(
                "winux.core.verification.Path.read_bytes",
                return_value=b"C:\\Program Files\\Example\\example.exe\0",
            ):
                iterdir.return_value = [Path("/proc/1234")]

                result = self.manager.verify(
                    {"checks": [{
                        "type": "process",
                        "executable": "example.exe",
                    }]},
                    self.prefix,
                )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["checks"][0]["passed"])

    def test_process_check_ignores_executable_in_arguments(self):
        with patch("winux.core.verification.Path.iterdir") as iterdir:
            with patch(
                "winux.core.verification.Path.read_bytes",
                return_value=b"/usr/bin/python\0/path/example.exe\0",
            ):
                iterdir.return_value = [Path("/proc/1234")]

                result = self.manager.verify(
                    {"checks": [{
                        "type": "process",
                        "executable": "example.exe",
                    }]},
                    self.prefix,
                )

        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["checks"][0]["passed"])

    def test_port_check_detects_open_local_port(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        self.addCleanup(server.close)

        result = self.manager.verify(
            {"checks": [{"type": "port", "port": port}]},
            self.prefix,
        )

        self.assertEqual(result["status"], "VERIFIED")

    def test_port_check_fails_for_closed_port(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.close()

        result = self.manager.verify(
            {"checks": [{"type": "port", "port": port}]},
            self.prefix,
        )

        self.assertEqual(result["status"], "FAILED")

    def test_registry_check_passes(self):
        runtime = Mock()
        runtime.query_registry.return_value = SimpleNamespace(
            returncode=0,
            stdout="HKEY_LOCAL_MACHINE\\Software\\Example\nVersion REG_SZ 1.0",
        )

        result = self.manager.verify(
            {
                "checks": [{
                    "type": "registry",
                    "key": r"HKEY_LOCAL_MACHINE\Software\Example",
                    "contains": "1.0",
                }]
            },
            self.prefix,
            runtime=runtime,
        )

        self.assertEqual(result["status"], "VERIFIED")

    def test_registry_check_fails_when_key_is_missing(self):
        runtime = Mock()
        runtime.query_registry.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
        )

        result = self.manager.verify(
            {"checks": [{
                "type": "registry",
                "key": r"HKEY_LOCAL_MACHINE\Software\Missing",
            }]},
            self.prefix,
            runtime=runtime,
        )

        self.assertEqual(result["status"], "FAILED")

    def test_unknown_check_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.manager.verify(
                {"checks": [{"type": "service"}]},
                self.prefix,
            )

    def test_empty_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must contain checks"):
            self.manager.verify({"checks": []}, self.prefix)

    def test_mixed_checks_fail_if_any_check_fails(self):
        result = self.manager.verify(
            {"checks": [
                {"type": "file", "path": "missing.exe"},
                {"type": "port", "port": 1},
            ]},
            self.prefix,
        )

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(len(result["checks"]), 2)


if __name__ == "__main__":
    unittest.main()
