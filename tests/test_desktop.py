import tempfile
import unittest
from pathlib import Path

from winux.core.desktop import DesktopManager


class DesktopManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.prefix = self.root / "prefix"
        self.prefix.mkdir()
        self.other_prefix = self.root / "prefix-other"
        self.other_prefix.mkdir()
        self.applications = self.root / "applications"
        self.applications.mkdir()
        self.desktop = self.root / "Desktop"
        self.desktop.mkdir()

        self.manager = object.__new__(DesktopManager)
        self.manager.applications_dir = self.applications
        self.manager.desktop_dir = self.desktop

    def tearDown(self):
        self.temp_dir.cleanup()

    def _entry(self, prefix):
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Example\n"
            f'Exec=env WINEPREFIX="{prefix}" wine "C:\\Example\\app.exe"\n'
        )

    def test_launcher_prefix_reads_wineprefix_from_exec(self):
        self.assertEqual(
            DesktopManager._launcher_prefix(self._entry(self.prefix)),
            str(self.prefix),
        )

    def test_launcher_prefix_rejects_missing_or_malformed_exec(self):
        self.assertIsNone(
            DesktopManager._launcher_prefix(
                "[Desktop Entry]\nName=Example\n"
            )
        )
        self.assertIsNone(
            DesktopManager._launcher_prefix(
                "[Desktop Entry]\nExec=env WINEPREFIX=\"unterminated\n"
            )
        )

    def test_discovery_matches_exact_prefix_not_substring(self):
        (self.applications / "match.desktop").write_text(
            self._entry(self.prefix), encoding="utf-8"
        )
        (self.applications / "near-match.desktop").write_text(
            self._entry(self.other_prefix), encoding="utf-8"
        )

        result = self.manager.discover_prefix_launchers(self.prefix)

        self.assertEqual(
            [item["name"] for item in result["launchers"]],
            ["match"],
        )
        self.assertEqual(result["errors"], [])

    def test_discovery_ignores_symlinked_desktop_files(self):
        target = self.root / "outside.desktop"
        target.write_text(self._entry(self.prefix), encoding="utf-8")
        (self.applications / "linked.desktop").symlink_to(target)

        result = self.manager.discover_prefix_launchers(self.prefix)

        self.assertEqual(result["launchers"], [])

    def test_integration_refuses_to_overwrite_existing_desktop_file(self):
        source = self.applications / "example.desktop"
        source.write_text(self._entry(self.prefix), encoding="utf-8")
        destination = self.desktop / source.name
        destination.write_text("user-owned desktop entry", encoding="utf-8")

        result = self.manager.integrate_prefix(self.prefix)

        self.assertEqual(result["integrated"], [])
        self.assertTrue(
            any("refusing to overwrite" in error for error in result["errors"])
        )
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            "user-owned desktop entry",
        )


if __name__ == "__main__":
    unittest.main()
