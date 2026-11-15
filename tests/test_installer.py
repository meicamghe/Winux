import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from winux.core.installer import Installer
from winux.core.verification import VerificationManager


class InstallerArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.home_patcher = patch.object(Path, "home", return_value=self.home)
        self.home_patcher.start()
        self.installer = Installer()

    def tearDown(self):
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    def make_pe(self, path, architecture):
        machine, magic = {
            "x86": (0x14C, 0x10B),
            "x64": (0x8664, 0x20B),
        }[architecture]
        header = bytearray(0x100)
        header[:2] = b"MZ"
        header[60:64] = (0x80).to_bytes(4, "little")
        header[0x80:0x84] = b"PE\x00\x00"
        header[0x84:0x86] = machine.to_bytes(2, "little")
        header[0x98:0x9A] = magic.to_bytes(2, "little")
        path.write_bytes(header)
        return path

    def test_get_exe_architecture_detects_x86(self):
        source = self.make_pe(self.home / "x86.exe", "x86")
        self.assertEqual(self.installer._get_exe_architecture(source), "x86")

    def test_get_exe_architecture_detects_x64(self):
        source = self.make_pe(self.home / "x64.exe", "x64")
        self.assertEqual(self.installer._get_exe_architecture(source), "x64")

    def test_get_exe_architecture_rejects_invalid_dos_signature(self):
        source = self.home / "invalid.exe"
        source.write_bytes(b"NO" + bytes(100))
        with self.assertRaisesRegex(ValueError, "Invalid EXE signature"):
            self.installer._get_exe_architecture(source)

    def test_get_exe_architecture_rejects_invalid_pe_signature(self):
        source = self.home / "invalid-pe.exe"
        data = bytearray(0x100)
        data[:2] = b"MZ"
        data[60:64] = (0x80).to_bytes(4, "little")
        source.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Invalid Windows PE"):
            self.installer._get_exe_architecture(source)

    def test_get_msi_architecture_detects_x86_and_x64(self):
        for template, expected in (("Intel;1033", "x86"), ("x64;1033", "x64")):
            with self.subTest(template=template):
                with patch("winux.core.installer.shutil.which", return_value="/usr/bin/msiinfo"), patch(
                    "winux.core.installer.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout=f"Template: {template}\n", stderr=""),
                ):
                    self.assertEqual(
                        self.installer._get_msi_architecture(self.home / "app.msi"),
                        expected,
                    )

    def test_get_msi_architecture_rejects_unknown_template(self):
        with patch("winux.core.installer.shutil.which", return_value="/usr/bin/msiinfo"), patch(
            "winux.core.installer.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="Template: ARM64;1033\n", stderr=""),
        ):
            with self.assertRaisesRegex(ValueError, "Unsupported MSI architecture"):
                self.installer._get_msi_architecture(self.home / "app.msi")

    def test_get_msi_architecture_reports_tool_launch_failure(self):
        with (
            patch("winux.core.installer.shutil.which", return_value="/usr/bin/msiinfo"),
            patch(
                "winux.core.installer.subprocess.run",
                side_effect=FileNotFoundError("msiinfo disappeared"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Unable to execute msiinfo"):
                self.installer._get_msi_architecture(self.home / "app.msi")

    def test_nsis_inspection_reports_tool_launch_failure(self):
        with (
            patch("winux.core.installer.shutil.which", return_value="/usr/bin/7z"),
            patch(
                "winux.core.installer.subprocess.run",
                side_effect=FileNotFoundError("7z disappeared"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Unable to execute 7z"):
                self.installer._inspect_nsis_application_architecture(
                    self.home / "setup.exe"
                )

    def test_nsis_extraction_reports_tool_launch_failure(self):
        listing = SimpleNamespace(
            returncode=0,
            stdout=(
                "Type = Nsis\\n"
                "Path = /tmp/setup.exe\\n"
                "Path = app.exe\\n"
            ),
            stderr="",
        )
        with (
            patch("winux.core.installer.shutil.which", return_value="/usr/bin/7z"),
            patch(
                "winux.core.installer.subprocess.run",
                side_effect=[listing, FileNotFoundError("7z disappeared")],
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Unable to execute 7z for extraction",
            ):
                self.installer._inspect_nsis_application_architecture(
                    self.home / "setup.exe"
                )

    def test_validate_msi_checks_ole_signature_before_inspection(self):
        source = self.home / "bad.msi"
        source.write_bytes(bytes(128))
        with self.assertRaisesRegex(ValueError, "Invalid MSI/OLE"):
            self.installer._validate_installer_file(source, ".msi")

    def test_validate_installer_rejects_unsupported_extension(self):
        source = self.home / "app.bin"
        source.write_bytes(bytes(128))
        with self.assertRaisesRegex(ValueError, "Unsupported installer format"):
            self.installer._validate_installer_file(source, ".bin")

    def test_validate_installer_rejects_too_small_file(self):
        source = self.home / "tiny.exe"
        source.write_bytes(b"MZ")
        with self.assertRaisesRegex(ValueError, "too small"):
            self.installer._validate_installer_file(source, ".exe")



class InstallerExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.home_patcher = patch.object(Path, "home", return_value=self.home)
        self.home_patcher.start()
        self.runtime = Mock()
        self.runtime.name = "test-runtime"
        self.runtime.is_available.return_value = True
        self.runtime.install.return_value = SimpleNamespace(returncode=0)

        self.runtime_manager = Mock()
        self.runtime_manager.get.return_value = self.runtime
        self.runtime_manager.get_default_name.return_value = "test-runtime"

        self.installer = Installer(runtime_manager=self.runtime_manager)
        self.prefix_path = self.home / ".local/share/winux/prefixes/test-prefix"
        self.prefix_path.mkdir(parents=True)

        self.source = self.home / "setup.exe"
        data = bytearray(0x100)
        data[:2] = b"MZ"
        data[60:64] = (0x80).to_bytes(4, "little")
        data[0x80:0x84] = b"PE\x00\x00"
        data[0x84:0x86] = (0x8664).to_bytes(2, "little")
        data[0x98:0x9A] = (0x20B).to_bytes(2, "little")
        self.source.write_bytes(data)

    def tearDown(self):
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    def prepare_install(self, returncode=0):
        patches = [
            patch.object(self.installer, "_inspect_nsis_application_architecture",
                         side_effect=ValueError("Not an NSIS installer")),
            patch.object(self.installer.prefix_manager, "get_path",
                         return_value=self.prefix_path),
            patch.object(self.installer.prefix_manager, "get_architecture",
                         return_value="win64"),
            patch.object(
                self.runtime,
                "install",
                return_value=SimpleNamespace(returncode=returncode),
            ),
        ]
        started = []
        for item in patches:
            started.append(item.start())
            self.addCleanup(item.stop)
        return started[-1]

    def test_install_uses_runtime_with_selected_prefix_and_logs_success(self):
        run_patch = self.prepare_install()
        result = self.installer.install(self.source, "test-prefix")

        self.assertTrue(result["success"])
        self.assertEqual(result["process_status"], "SUCCESS")
        self.assertEqual(result["verification_status"], "PENDING")
        self.assertEqual(result["installer_architecture"], "x64")
        self.assertEqual(result["prefix"], "test-prefix")
        self.assertEqual(
            run_patch.call_args.args,
            (self.prefix_path, self.source),
        )
        self.assertEqual(run_patch.call_args.kwargs["timeout"], 3600)
        log = Path(result["log"]).read_text(encoding="utf-8")
        self.assertIn("Status: SUCCESS", log)
        self.assertIn("Process Status: SUCCESS", log)
        self.assertIn("Verification Status: PENDING", log)
        self.assertIn("Application Architecture: unknown", log)

    def test_install_records_failure_when_runtime_returns_nonzero(self):
        self.prepare_install(returncode=7)
        with self.assertRaisesRegex(RuntimeError, "exited with code 7"):
            self.installer.install(self.source, "test-prefix")

        logs = list(self.installer.log_dir.glob("*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("Status: FAILED", logs[0].read_text(encoding="utf-8"))

    def test_install_rejects_symbolic_link(self):
        link = self.home / "linked.exe"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "Symbolic links"):
            self.installer.install(link, "test-prefix")

    def test_install_rejects_invalid_timeout_values(self):
        invalid_timeouts = (
            True,
            False,
            "30",
            float("nan"),
            float("inf"),
            float("-inf"),
            0,
            -1,
            10 ** 1000,
        )
        for timeout in invalid_timeouts:
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(
                    ValueError,
                    "finite positive number",
                ):
                    self.installer.install(
                        self.source,
                        "test-prefix",
                        timeout=timeout,
                    )

    def test_install_rejects_non_positive_timeout(self):
        with patch.object(self.installer, "_validate_installer_file",
                          return_value="x64"):
            with self.assertRaisesRegex(ValueError, "finite positive number"):
                self.installer.install(self.source, "test-prefix", timeout=0)

    def test_install_verifies_application_when_profile_is_configured(self):
        self.prepare_install()
        profile = {"checks": [{"type": "file", "path": "Program Files/App/app.exe"}]}

        with patch.object(
            self.installer.verification_manager,
            "verify",
            return_value={
                "status": "VERIFIED",
                "details": "file: application executable found",
                "checks": [
                    {
                        "type": "file",
                        "passed": True,
                        "details": "application executable found",
                    }
                ],
            },
        ) as verify:
            result = self.installer.install(
                self.source, "test-prefix",
                verification_profile=profile,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["process_status"], "SUCCESS")
        self.assertEqual(result["verification_status"], "VERIFIED")
        self.assertEqual(
            result["verification_details"],
            "file: application executable found",
        )
        verify.assert_called_once_with(
            profile, self.prefix_path, runtime=self.runtime
        )

        log = Path(result["log"]).read_text(encoding="utf-8")
        self.assertIn("Verification Status: VERIFIED", log)
        self.assertIn(
            "Verification Check: file | PASS | application executable found",
            log,
        )

    def test_verification_failure_does_not_fail_successful_installation(self):
        self.prepare_install()
        profile = {"checks": [{"type": "file", "path": "App/missing.exe"}]}

        with patch.object(
            self.installer.verification_manager,
            "verify",
            return_value={
                "status": "FAILED",
                "details": "file: App/missing.exe not found",
                "checks": [
                    {
                        "type": "file",
                        "passed": False,
                        "details": "App/missing.exe not found",
                    }
                ],
            },
        ):
            result = self.installer.install(
                self.source, "test-prefix",
                verification_profile=profile,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["process_status"], "SUCCESS")
        self.assertEqual(result["verification_status"], "FAILED")
        self.assertIn("not found", result["verification_details"])

        log = Path(result["log"]).read_text(encoding="utf-8")
        self.assertIn("Status: SUCCESS", log)
        self.assertIn("Process Status: SUCCESS", log)
        self.assertIn("Verification Status: FAILED", log)
        self.assertIn("Verification Check: file | FAIL", log)

    def test_install_without_profile_does_not_call_verification(self):
        self.prepare_install()

        with patch.object(
            self.installer.verification_manager, "verify"
        ) as verify:
            result = self.installer.install(self.source, "test-prefix")

        self.assertTrue(result["success"])
        self.assertEqual(result["process_status"], "SUCCESS")
        self.assertEqual(result["verification_status"], "PENDING")
        verify.assert_not_called()

    def test_verification_exception_does_not_fail_successful_installation(self):
        self.prepare_install()
        profile = {"checks": [{"type": "registry", "key": "Software\\Example"}]}

        with patch.object(
            self.installer.verification_manager,
            "verify",
            side_effect=RuntimeError("registry query failed"),
        ):
            result = self.installer.install(
                self.source, "test-prefix",
                verification_profile=profile,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["process_status"], "SUCCESS")
        self.assertEqual(result["verification_status"], "FAILED")
        self.assertIn(
            "Verification error: registry query failed",
            result["verification_details"],
        )

        log = Path(result["log"]).read_text(encoding="utf-8")
        self.assertIn("Status: SUCCESS", log)
        self.assertIn("Verification Status: FAILED", log)
        self.assertIn(
            "Verification Details: Verification error: registry query failed",
            log,
        )

    def test_history_and_stats_report_install_results(self):
        self.prepare_install()
        self.installer.install(self.source, "test-prefix")

        history = self.installer.history()
        stats = self.installer.stats()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "SUCCESS")
        self.assertEqual(history[0]["process_status"], "SUCCESS")
        self.assertEqual(history[0]["verification_status"], "PENDING")
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["verified"], 0)
        self.assertEqual(stats["verification_pending"], 1)
        self.assertEqual(stats["success_rate"], 100.0)


class InstallerBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.installer = Installer.__new__(Installer)
        self.installer.verification_manager = VerificationManager()

        self.file1 = self.root / "app1.exe"
        self.file2 = self.root / "app2.msi"
        self.file3 = self.root / "app3.exe"

        for file in (self.file1, self.file2, self.file3):
            file.write_bytes(b"test")

        self.manifest = self.root / "manifest.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_manifest(self, applications):
        self.manifest.write_text(
            json.dumps({"applications": applications}),
            encoding="utf-8"
        )

    def test_batch_continues_after_failed_install(self):
        self.write_manifest([
            {"file": str(self.file1)},
            {"file": str(self.file2), "timeout": 120},
            {"file": str(self.file3)}
        ])

        with patch.object(
            self.installer,
            "install",
            side_effect=[
                {"success": True, "install_id": "one"},
                RuntimeError("Installation failed"),
                {"success": True, "install_id": "three"}
            ]
        ) as mock_install:
            result = self.installer.install_batch(
                self.manifest, "test-prefix"
            )

        self.assertEqual(mock_install.call_count, 3)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["successful"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertFalse(result["success"])
        self.assertTrue(result["results"][0]["success"])
        self.assertFalse(result["results"][1]["success"])
        self.assertTrue(result["results"][2]["success"])

    def test_batch_validates_all_files_before_installing(self):
        self.write_manifest([
            {"file": str(self.file1)},
            {"file": str(self.root / "missing.exe")}
        ])

        with patch.object(self.installer, "install") as mock_install:
            with self.assertRaisesRegex(
                ValueError, "missing or invalid"
            ):
                self.installer.install_batch(
                    self.manifest, "test-prefix"
                )

        mock_install.assert_not_called()

    def test_batch_rejects_invalid_profile_before_any_install(self):
        self.write_manifest([
            {"file": str(self.file1)},
            {
                "file": str(self.file2),
                "verification_profile": {
                    "checks": [{"type": "unsupported"}]
                },
            },
        ])

        with patch.object(self.installer, "install") as mock_install:
            with self.assertRaisesRegex(
                ValueError, "invalid verification_profile"
            ):
                self.installer.install_batch(
                    self.manifest, "test-prefix"
                )

        mock_install.assert_not_called()

    def test_batch_passes_valid_profiles_to_install(self):
        profile = {
            "checks": [{
                "type": "file",
                "path": r"Program Files\\Example\\app.exe",
            }]
        }
        self.write_manifest([
            {
                "file": str(self.file1),
                "verification_profile": profile,
            },
            {"file": str(self.file2)},
        ])

        with patch.object(
            self.installer,
            "install",
            return_value={"success": True, "install_id": "test"},
        ) as mock_install:
            result = self.installer.install_batch(
                self.manifest, "test-prefix"
            )

        self.assertTrue(result["success"])
        self.assertEqual(mock_install.call_count, 2)
        self.assertEqual(
            mock_install.call_args_list[0].kwargs["verification_profile"],
            profile,
        )
        self.assertIsNone(
            mock_install.call_args_list[1].kwargs["verification_profile"]
        )

    def test_batch_rejects_invalid_timeout(self):
        self.write_manifest([
            {"file": str(self.file1), "timeout": 0}
        ])

        with patch.object(self.installer, "install") as mock_install:
            with self.assertRaisesRegex(ValueError, "invalid timeout"):
                self.installer.install_batch(
                    self.manifest, "test-prefix"
                )

        mock_install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
