import os
import unittest

from winux.core.installer import Installer
from winux.core.prefix import PrefixManager


class Wow64ArchitectureMatrixTests(unittest.TestCase):
    def test_selected_installer_architecture_is_accepted_by_win64_prefix(self):
        architecture = os.environ["WINUX_MATRIX_ARCHITECTURE"]
        self.assertIn(architecture, ("x86", "x64"))
        Installer._validate_architecture_compatibility(architecture, "win64")

    def test_selected_application_architecture_uses_win64_prefix(self):
        architecture = os.environ["WINUX_MATRIX_ARCHITECTURE"]
        self.assertIn(architecture, ("x86", "x64"))
        self.assertEqual(
            PrefixManager.normalize_architecture(
                object.__new__(PrefixManager), architecture
            ),
            "win64",
        )

    def test_unknown_architectures_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported installer architecture"):
            Installer._validate_architecture_compatibility("arm64", "win64")
        with self.assertRaisesRegex(ValueError, "Unsupported Wine prefix architecture"):
            Installer._validate_architecture_compatibility("x86", "winarm64")


if __name__ == "__main__":
    unittest.main()
