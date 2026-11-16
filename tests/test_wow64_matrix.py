import unittest

from winux.core.installer import Installer
from winux.core.prefix import PrefixManager


class Wow64ArchitectureMatrixTests(unittest.TestCase):
    def test_x86_and_x64_installers_are_accepted_by_win64_wow64_prefix(self):
        for installer_architecture in ("x86", "x64"):
            with self.subTest(installer_architecture=installer_architecture):
                Installer._validate_architecture_compatibility(
                    installer_architecture, "win64"
                )

    def test_both_application_architectures_normalize_to_win64_prefix(self):
        for application_architecture in ("x86", "x64"):
            with self.subTest(application_architecture=application_architecture):
                self.assertEqual(
                    PrefixManager().normalize_architecture(application_architecture),
                    "win64",
                )

    def test_unknown_architectures_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported installer architecture"):
            Installer._validate_architecture_compatibility("arm64", "win64")
        with self.assertRaisesRegex(ValueError, "Unsupported Wine prefix architecture"):
            Installer._validate_architecture_compatibility("x86", "winarm64")


if __name__ == "__main__":
    unittest.main()
