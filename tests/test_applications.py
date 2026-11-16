import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from winux.core.applications import ApplicationManager


class ApplicationManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.prefix_path = Path(self.temp_dir.name) / "prefix"
        (self.prefix_path / "drive_c").mkdir(parents=True)
        self.runtime = Mock()
        self.runtime.name = "test-runtime"
        self.runtime.is_available.return_value = True
        self.runtime.query_registry.return_value = Mock(
            returncode=0, stdout="", stderr=""
        )
        self.runtime.uninstall.return_value = Mock(returncode=0)

        self.runtime_manager = Mock()
        self.runtime_manager.get.return_value = self.runtime

        self.manager = object.__new__(ApplicationManager)
        self.manager.runtime_manager = self.runtime_manager
        self.manager.prefix_manager = Mock()
        self.manager.prefix_manager.get_path.return_value = self.prefix_path
        self.manager.prefix_manager.get_runtime.return_value = self.runtime

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_registry_groups_values_by_registry_key(self):
        output = """HKEY_LOCAL_MACHINE\\Software\\App\\One
    DisplayName    REG_SZ    Example App
    DisplayVersion REG_SZ    1.2.3
    Publisher      REG_SZ    Example Publisher

HKEY_CURRENT_USER\\Software\\App\\Two
    DisplayName    REG_SZ    Another App
"""
        records = self.manager._parse_registry(output)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["DisplayName"], "Example App")
        self.assertEqual(records[0]["DisplayVersion"], "1.2.3")
        self.assertEqual(records[1]["registry_id"], "Two")

    def test_parse_registry_ignores_entries_without_display_name(self):
        output = """HKEY_LOCAL_MACHINE\\Software\\App\\NoName
    Publisher REG_SZ Example Publisher
"""
        self.assertEqual(self.manager._parse_registry(output), [])

    def test_windows_path_conversion_accepts_only_drive_c(self):
        converted = self.manager._windows_path_to_linux(
            self.prefix_path, r"C:\\Program Files\\Example\\app.exe"
        )
        rejected = self.manager._windows_path_to_linux(
            self.prefix_path, r"D:\\Apps\\app.exe"
        )

        self.assertEqual(
            converted,
            self.prefix_path / "drive_c" / "Program Files" / "Example" / "app.exe",
        )
        self.assertIsNone(rejected)

    def test_windows_path_conversion_rejects_drive_relative_paths(self):
        self.assertIsNone(
            self.manager._windows_path_to_linux(
                self.prefix_path, r"C:Program Files\\Example\\app.exe"
            )
        )

    def test_windows_path_conversion_rejects_parent_traversal(self):
        self.assertIsNone(
            self.manager._windows_path_to_linux(
                self.prefix_path, r"C:\\..\\..\\outside.exe"
            )
        )

    def test_windows_path_conversion_rejects_symlinked_drive_c(self):
        drive_c = self.prefix_path / "drive_c"
        external = Path(self.temp_dir.name) / "external"
        external.mkdir()
        drive_c.rmdir()
        drive_c.symlink_to(external, target_is_directory=True)

        self.assertIsNone(
            self.manager._windows_path_to_linux(
                self.prefix_path, r"C:\\Program Files\\Example\\app.exe"
            )
        )

    def test_windows_path_conversion_handles_display_icon_index(self):
        converted = self.manager._windows_path_to_linux(
            self.prefix_path, r'"C:\\Program Files\\Example\\app.exe",0'
        )

        self.assertEqual(
            converted,
            self.prefix_path / "drive_c" / "Program Files" / "Example" / "app.exe",
        )

    def test_parse_app_paths_accepts_existing_executable_default_value(self):
        executable = (
            self.prefix_path / "drive_c" / "Program Files" / "Example" / "example.exe"
        )
        executable.parent.mkdir(parents=True)
        executable.touch()
        output = (
            r"HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\example.exe"
            + "\n    (Default)    REG_SZ    C:\\\\Program Files\\\\Example\\\\example.exe\n"
        )
        candidates = self.manager._parse_app_paths(output, self.prefix_path)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["executable_path"], str(executable))
        self.assertEqual(candidates[0]["discovery_source"], "app_paths")

    def test_parse_app_paths_rejects_missing_or_non_executable_targets(self):
        output = (
            r"HKEY_LOCAL_MACHINE\\Software\\App Paths\\missing.exe"
            + "\n    (Default)    REG_SZ    C:\\\\Missing\\\\missing.exe\n"
            + r"HKEY_LOCAL_MACHINE\\Software\\App Paths\\resource.exe"
            + "\n    (Default)    REG_SZ    C:\\\\Windows\\\\resource.dll\n"
        )
        self.assertEqual(
            self.manager._parse_app_paths(output, self.prefix_path), []
        )

    def test_list_deduplicates_registry_records_and_resolves_paths(self):
        app_exe = (
            self.prefix_path / "drive_c" / "Program Files" / "Example" / "app.exe"
        )
        app_exe.parent.mkdir(parents=True)
        app_exe.touch()

        records = [
            {
                "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
                "registry_id": "Example",
                "DisplayName": "Example App",
                "DisplayIcon": r"C:\\Program Files\\Example\\app.exe",
                "InstallLocation": r"C:\\Program Files\\Example",
            },
            {
                "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
                "registry_id": "Example",
                "DisplayName": "Example App",
                "DisplayIcon": r"C:\\Program Files\\Example\\app.exe",
                "InstallLocation": r"C:\\Program Files\\Example",
            },
        ]

        with patch.object(self.manager, "_query_registry", return_value=records):
            applications = self.manager.list("test-prefix")

        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["executable_path"], str(app_exe))
        self.assertEqual(
            applications[0]["install_path"],
            str(app_exe.parent),
        )
        self.manager.prefix_manager.get_path.assert_called_once_with("test-prefix")

    def test_list_does_not_treat_icon_resources_as_executables(self):
        app_dir = self.prefix_path / "drive_c" / "Program Files" / "Example"
        app_dir.mkdir(parents=True)
        icon = app_dir / "app.ico"
        icon.touch()
        dll = app_dir / "app.dll"
        dll.touch()

        for display_icon in (
            r"C:\\Program Files\\Example\\app.ico",
            r"C:\\Program Files\\Example\\app.dll",
        ):
            records = [{
                "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
                "registry_id": "Example",
                "DisplayName": "Example App",
                "DisplayIcon": display_icon,
                "InstallLocation": r"C:\\Program Files\\Example",
            }]
            with self.subTest(display_icon=display_icon):
                with patch.object(self.manager, "_query_registry", return_value=records):
                    applications = self.manager.list("test-prefix")
                self.assertEqual(len(applications), 1)
                self.assertIsNone(applications[0]["executable_path"])
                self.assertEqual(applications[0]["install_path"], str(app_dir))

    def test_list_accepts_exe_display_icon_case_insensitively(self):
        app_exe = (
            self.prefix_path / "drive_c" / "Program Files" / "Example" / "APP.EXE"
        )
        app_exe.parent.mkdir(parents=True)
        app_exe.touch()
        records = [{
            "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
            "registry_id": "Example",
            "DisplayName": "Example App",
            "DisplayIcon": r"C:\\Program Files\\Example\\APP.EXE,0",
        }]
        with patch.object(self.manager, "_query_registry", return_value=records):
            applications = self.manager.list("test-prefix")
        self.assertEqual(applications[0]["executable_path"], str(app_exe))

    def test_list_reports_why_executable_is_unavailable(self):
        app_dir = self.prefix_path / "drive_c" / "Program Files" / "Example"
        app_dir.mkdir(parents=True)
        icon = app_dir / "app.ico"
        icon.touch()
        records = [{
            "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
            "registry_id": "Example",
            "DisplayName": "Example App",
            "DisplayIcon": r"C:\\Program Files\\Example\\app.ico",
        }]
        with patch.object(self.manager, "_query_registry", return_value=records):
            application = self.manager.list("test-prefix")[0]
        self.assertIsNone(application["executable_path"])
        self.assertEqual(
            application["executable_status"], "resource_not_executable"
        )

    def test_list_marks_missing_executable(self):
        records = [{
            "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
            "registry_id": "Example",
            "DisplayName": "Example App",
            "DisplayIcon": r"C:\\Program Files\\Example\\app.exe",
        }]
        with patch.object(self.manager, "_query_registry", return_value=records):
            application = self.manager.list("test-prefix")[0]
        self.assertEqual(application["executable_status"], "executable_missing")

    def test_list_marks_missing_display_icon(self):
        records = [{
            "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
            "registry_id": "Example",
            "DisplayName": "Example App",
        }]
        with patch.object(self.manager, "_query_registry", return_value=records):
            application = self.manager.list("test-prefix")[0]
        self.assertEqual(application["executable_status"], "not_registered")

    def test_info_finds_application_by_registry_id_case_insensitively(self):
        expected = {"registry_id": "Example", "DisplayName": "Example App"}
        with patch.object(self.manager, "list", return_value=[expected]):
            self.assertIs(self.manager.info("test-prefix", "example"), expected)

    def test_info_raises_for_unknown_application(self):
        with patch.object(self.manager, "list", return_value=[]):
            with self.assertRaises(LookupError):
                self.manager.info("test-prefix", "missing")

    def test_msi_product_code_requires_msiexec_and_extracts_guid(self):
        product_code = "{12345678-1234-5678-9ABC-1234567890AB}"
        record = {
            "UninstallString": (
                '"C:\\\\Windows\\\\System32\\\\msiexec.exe" '
                f'/I{product_code}'
            )
        }
        self.assertEqual(
            self.manager._msi_product_code(record), product_code
        )
        self.assertIsNone(self.manager._msi_product_code({
            "UninstallString": f'"C:\\\\Apps\\\\remove.exe" /x{product_code}'
        }))

    def test_list_deduplicates_msi_registry_views_by_product_code(self):
        product_code = "{12345678-1234-5678-9ABC-1234567890AB}"
        records = [
            {
                "registry_key": (
                    r"HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion"
                    r"\\Uninstall\\ProductNative"
                ),
                "registry_id": "ProductNative",
                "DisplayName": "Example MSI",
                "UninstallString": f'msiexec.exe /I{product_code}',
            },
            {
                "registry_key": (
                    r"HKEY_LOCAL_MACHINE\\Software\\WOW6432Node\\Microsoft"
                    r"\\Windows\\CurrentVersion\\Uninstall\\ProductWow"
                ),
                "registry_id": "ProductWow",
                "DisplayName": "Example MSI",
                "UninstallString": f'msiexec.exe /x {product_code} /qn',
            },
        ]
        with (
            patch.object(self.manager, "_query_registry", return_value=records),
            patch.object(self.runtime, "query_registry", return_value=Mock(
                returncode=0, stdout="", stderr=""
            )),
            patch(
                "winux.core.applications.DesktopManager.discover_start_menu_shortcuts",
                return_value={"shortcuts": []},
            ),
        ):
            applications = self.manager.list("test-prefix")

        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["DisplayName"], "Example MSI")
        self.assertEqual(
            set(applications[0]["registry_ids"]),
            {"ProductNative", "ProductWow"},
        )
        self.assertEqual(len(applications[0]["uninstall_commands"]), 2)

    def test_info_finds_msi_application_by_secondary_registry_id(self):
        application = {
            "registry_id": "ProductNative",
            "registry_ids": ["ProductNative", "ProductWow"],
            "DisplayName": "Example MSI",
        }
        with patch.object(self.manager, "list", return_value=[application]):
            self.assertIs(
                self.manager.info("test-prefix", "productwow"), application
            )

    def test_list_does_not_merge_non_msi_entries_with_same_display_name(self):
        records = [
            {
                "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\VendorA\\Uninstall\\A",
                "registry_id": "A",
                "DisplayName": "Shared Name",
            },
            {
                "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\VendorB\\Uninstall\\B",
                "registry_id": "B",
                "DisplayName": "Shared Name",
            },
        ]
        with (
            patch.object(self.manager, "_query_registry", return_value=records),
            patch.object(self.runtime, "query_registry", return_value=Mock(
                returncode=0, stdout="", stderr=""
            )),
            patch(
                "winux.core.applications.DesktopManager.discover_start_menu_shortcuts",
                return_value={"shortcuts": []},
            ),
        ):
            applications = self.manager.list("test-prefix")

        self.assertEqual(len(applications), 2)


    def test_uninstall_rejects_invalid_timeouts_before_lookup(self):
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
            with self.subTest(timeout=repr(timeout)):
                with patch.object(self.manager, "info") as info:
                    with self.assertRaisesRegex(
                        ValueError, "finite positive number"
                    ):
                        self.manager.uninstall(
                            "test-prefix", "Example", timeout=timeout
                        )
                info.assert_not_called()
                self.runtime.uninstall.assert_not_called()

    def test_uninstall_rejects_non_string_command(self):
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "UninstallString": ["uninstaller.exe"],
        }

        with patch.object(self.manager, "info", return_value=application):
            with self.assertRaisesRegex(ValueError, "Invalid uninstall command"):
                self.manager.uninstall("test-prefix", "Example")

        self.runtime.uninstall.assert_not_called()

    def test_uninstall_uses_quiet_uninstall_string_when_available(self):
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "QuietUninstallString": '"C:\\\\Program Files\\\\Example\\\\uninstall.exe" /quiet',
            "UninstallString": "fallback-uninstaller.exe",
        }

        with patch.object(self.manager, "info", return_value=application):
            with patch.object(self.runtime, "uninstall") as run:
                run.return_value.returncode = 0
                result = self.manager.uninstall("test-prefix", "Example")

        self.assertTrue(result["success"])
        self.assertEqual(result["application"], "Example App")
        self.assertEqual(run.call_args.args[0], self.prefix_path)
        self.assertEqual(run.call_args.args[1][0], "C:\\\\Program Files\\\\Example\\\\uninstall.exe")
        self.assertIn("/quiet", run.call_args.args[1])

    def test_uninstall_falls_back_to_uninstall_string(self):
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "UninstallString": "uninstaller.exe /remove",
        }

        with patch.object(self.manager, "info", return_value=application):
            with patch.object(self.runtime, "uninstall") as run:
                run.return_value.returncode = 0
                result = self.manager.uninstall("test-prefix", "Example")

        self.assertTrue(result["success"])
        self.assertIn("/remove", run.call_args.args[1])

    def test_uninstall_converts_msi_install_switch_to_uninstall(self):
        product_code = "{12345678-1234-1234-1234-123456789abc}"
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "UninstallString": f'MsiExec.exe /I{product_code}',
        }

        with patch.object(self.manager, "info", return_value=application):
            with patch.object(self.runtime, "uninstall") as run:
                run.return_value.returncode = 0
                self.manager.uninstall("test-prefix", "Example")

        self.assertEqual(
            run.call_args.args[1],
            ["MsiExec.exe", f"/X{product_code}"],
        )

    def test_uninstall_converts_separate_msi_install_switch(self):
        product_code = "{12345678-1234-1234-1234-123456789abc}"
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "UninstallString": f'MSIEXEC /i {product_code} /qn',
        }

        with patch.object(self.manager, "info", return_value=application):
            with patch.object(self.runtime, "uninstall") as run:
                run.return_value.returncode = 0
                self.manager.uninstall("test-prefix", "Example")

        self.assertEqual(
            run.call_args.args[1],
            ["MSIEXEC", "/X", product_code, "/qn"],
        )

    def test_uninstall_does_not_rewrite_non_msi_commands(self):
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "UninstallString": "custom-uninstaller.exe /I{12345678-1234-1234-1234-123456789abc}",
        }

        with patch.object(self.manager, "info", return_value=application):
            with patch.object(self.runtime, "uninstall") as run:
                run.return_value.returncode = 0
                self.manager.uninstall("test-prefix", "Example")

        self.assertEqual(
            run.call_args.args[1],
            ["custom-uninstaller.exe", "/I{12345678-1234-1234-1234-123456789abc}"],
        )

    def test_uninstall_rejects_application_without_uninstaller(self):
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
        }

        with patch.object(self.manager, "info", return_value=application):
            with self.assertRaisesRegex(ValueError, "uninstall command"):
                self.manager.uninstall("test-prefix", "Example")

    def test_uninstall_reports_nonzero_exit_code(self):
        application = {
            "registry_id": "Example",
            "DisplayName": "Example App",
            "UninstallString": "uninstaller.exe",
        }

        with patch.object(self.manager, "info", return_value=application):
            with patch.object(self.runtime, "uninstall") as run:
                run.return_value.returncode = 7
                with self.assertRaisesRegex(RuntimeError, "exited with code 7"):
                    self.manager.uninstall("test-prefix", "Example")


    def test_audit_reports_missing_executable_inventory(self):
        applications = [
            {"DisplayName": "Healthy", "executable_status": "ready"},
            {"DisplayName": "Stale App", "registry_id": "stale", "executable_status": "executable_missing"},
            {"DisplayName": "No launch target", "executable_status": "not_registered"},
        ]
        with patch.object(self.manager, "list", return_value=applications):
            report = self.manager.audit("test-prefix")

        self.assertEqual(report["total"], 3)
        self.assertEqual(report["stale_count"], 1)
        self.assertEqual(report["status_counts"], {
            "ready": 1,
            "executable_missing": 1,
            "not_registered": 1,
        })
        self.assertEqual(report["stale"][0]["registry_id"], "stale")

    def test_audit_returns_empty_report_for_empty_inventory(self):
        with patch.object(self.manager, "list", return_value=[]):
            report = self.manager.audit("test-prefix")

        self.assertEqual(report["total"], 0)
        self.assertEqual(report["stale_count"], 0)
        self.assertEqual(report["stale"], [])

    def test_search_matches_name_case_insensitively(self):
        applications = [
            {"DisplayName": "Mozilla Firefox", "Publisher": "Mozilla", "DisplayVersion": "128"},
            {"DisplayName": "Notepad++", "Publisher": "Notepad++ Team", "DisplayVersion": "8.7"},
        ]

        with patch.object(self.manager, "list", return_value=applications):
            result = self.manager.search("test-prefix", "FIREFOX")

        self.assertEqual([app["DisplayName"] for app in result], ["Mozilla Firefox"])

    def test_search_matches_publisher_and_version(self):
        applications = [
            {"DisplayName": "Example App", "Publisher": "Example Corporation", "DisplayVersion": "2.5.1"},
            {"DisplayName": "Another App", "Publisher": "Other", "DisplayVersion": "3.0"},
        ]

        with patch.object(self.manager, "list", return_value=applications):
            publisher_result = self.manager.search("test-prefix", "CORPORATION")
            version_result = self.manager.search("test-prefix", "2.5")

        self.assertEqual(len(publisher_result), 1)
        self.assertEqual(len(version_result), 1)
        self.assertEqual(version_result[0]["DisplayName"], "Example App")

    def test_search_rejects_empty_or_invalid_query(self):
        for query in ("", "   ", None, 123):
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    self.manager.search("test-prefix", query)

    def test_search_returns_empty_list_when_no_match(self):
        applications = [
            {"DisplayName": "Example App", "Publisher": "Example", "DisplayVersion": "1.0"},
        ]

        with patch.object(self.manager, "list", return_value=applications):
            result = self.manager.search("test-prefix", "missing")

        self.assertEqual(result, [])


    def test_export_replaces_symlink_without_modifying_its_target(self):
        target = Path(self.temp_dir.name) / "outside.json"
        target.write_text("untouched", encoding="utf-8")
        output = Path(self.temp_dir.name) / "apps.json"
        output.symlink_to(target)

        with patch.object(self.manager, "list", return_value=[]):
            self.manager.export("test-prefix", output)

        self.assertFalse(output.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "untouched")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), [])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_export_failure_preserves_existing_destination(self):
        output = Path(self.temp_dir.name) / "apps.json"
        output.write_text("original", encoding="utf-8")

        with patch.object(self.manager, "list", return_value=[]):
            with patch("winux.core.applications.json.dump", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.manager.export("test-prefix", output)

        self.assertEqual(output.read_text(encoding="utf-8"), "original")
        self.assertEqual(
            [path for path in Path(self.temp_dir.name).iterdir() if path.name.startswith(".apps.json.")],
            [],
        )

    def test_export_json_includes_all_msi_registry_views(self):
        applications = [{
            "DisplayName": "MSI Example",
            "registry_id": "native-id",
            "registry_key": r"HKLM\\Software\\Uninstall\\native-id",
            "registry_ids": ["native-id", "wow-id"],
            "registry_keys": [
                r"HKLM\\Software\\Uninstall\\native-id",
                r"HKLM\\Software\\WOW6432Node\\Uninstall\\wow-id",
            ],
            "uninstall_commands": [
                {"registry_id": "native-id", "quiet": None, "normal": "msiexec /I{ABC}"},
                {"registry_id": "wow-id", "quiet": "msiexec /x {ABC} /qn", "normal": None},
            ],
        }]
        output = Path(self.temp_dir.name) / "msi-inventory.json"

        with patch.object(self.manager, "list", return_value=applications):
            self.manager.export("test-prefix", output, "json")

        record = json.loads(output.read_text(encoding="utf-8"))[0]
        self.assertEqual(record["registry_ids"], ["native-id", "wow-id"])
        self.assertEqual(len(record["registry_keys"]), 2)
        self.assertEqual(record["uninstall_commands"][1]["quiet"], "msiexec /x {ABC} /qn")

    def test_export_csv_serializes_msi_registry_views_as_json(self):
        applications = [{
            "DisplayName": "MSI Example",
            "registry_ids": ["native-id", "wow-id"],
            "registry_keys": [r"HKLM\\Software\\Uninstall\\native-id"],
            "uninstall_commands": [
                {"registry_id": "native-id", "quiet": None, "normal": "msiexec /I{ABC}"}
            ],
        }]
        output = Path(self.temp_dir.name) / "msi-inventory.csv"

        with patch.object(self.manager, "list", return_value=applications):
            self.manager.export("test-prefix", output, "csv")

        with output.open(encoding="utf-8", newline="") as file:
            record = next(csv.DictReader(file))
        self.assertEqual(json.loads(record["registry_ids"]), ["native-id", "wow-id"])
        self.assertEqual(json.loads(record["uninstall_commands"])[0]["registry_id"], "native-id")

    def test_export_writes_json(self):
        applications = [
            {
                "DisplayName": "Example App",
                "DisplayVersion": "1.2",
                "Publisher": "Example",
                "registry_id": "Example",
                "registry_key": "HKLM\\\\Software\\\\Example",
            }
        ]
        output = Path(self.temp_dir.name) / "apps.json"

        with patch.object(self.manager, "list", return_value=applications):
            result = self.manager.export("test-prefix", output, "json")

        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["count"], 1)
        self.assertEqual(data[0]["DisplayName"], "Example App")
        self.assertEqual(data[0]["registry_id"], "Example")

    def test_export_writes_csv(self):
        applications = [
            {
                "DisplayName": "Example App",
                "DisplayVersion": "1.2",
                "Publisher": "Example",
                "registry_id": "Example",
            }
        ]
        output = Path(self.temp_dir.name) / "apps.csv"

        with patch.object(self.manager, "list", return_value=applications):
            result = self.manager.export("test-prefix", output, "csv")

        with output.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))

        self.assertEqual(result["format"], "csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["DisplayName"], "Example App")

    def test_export_creates_parent_directories(self):
        output = Path(self.temp_dir.name) / "reports" / "nested" / "apps.json"

        with patch.object(self.manager, "list", return_value=[]):
            result = self.manager.export("test-prefix", output)

        self.assertTrue(output.is_file())
        self.assertEqual(result["count"], 0)

    def test_export_rejects_invalid_format(self):
        with self.assertRaisesRegex(ValueError, "Export format"):
            self.manager.export("test-prefix", "apps.txt", "txt")

    def test_export_rejects_directory_as_output_path(self):
        with self.assertRaisesRegex(ValueError, "must be a file"):
            self.manager.export("test-prefix", self.temp_dir.name, "json")


if __name__ == "__main__":
    unittest.main()
