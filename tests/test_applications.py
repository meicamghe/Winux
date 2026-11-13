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
        self.manager = object.__new__(ApplicationManager)
        self.manager.prefix_manager = Mock()
        self.manager.prefix_manager.get_path.return_value = self.prefix_path

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

    def test_windows_path_conversion_handles_display_icon_index(self):
        converted = self.manager._windows_path_to_linux(
            self.prefix_path, r'"C:\\Program Files\\Example\\app.exe",0'
        )

        self.assertEqual(
            converted,
            self.prefix_path / "drive_c" / "Program Files" / "Example" / "app.exe",
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

    def test_info_finds_application_by_registry_id_case_insensitively(self):
        expected = {"registry_id": "Example", "DisplayName": "Example App"}
        with patch.object(self.manager, "list", return_value=[expected]):
            self.assertIs(self.manager.info("test-prefix", "example"), expected)

    def test_info_raises_for_unknown_application(self):
        with patch.object(self.manager, "list", return_value=[]):
            with self.assertRaises(LookupError):
                self.manager.info("test-prefix", "missing")


if __name__ == "__main__":
    unittest.main()
