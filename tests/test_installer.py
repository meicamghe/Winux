import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from winux.core.installer import Installer


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


if __name__ == "__main__":
    unittest.main()
