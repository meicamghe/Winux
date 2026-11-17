import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winux.core.prefix_backup import MAGIC
from winux.core.prefix_restore import PrefixRestoreError, restore_prefix


def make_backup(path, *, corrupt_digest=False):
    payload_buffer = io.BytesIO()
    with tarfile.open(fileobj=payload_buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in ("dosdevices", "drive_c"):
            item = tarfile.TarInfo(name + "/")
            item.type = tarfile.DIRTYPE
            item.mode = 0o755
            archive.addfile(item)
        for name, data in (
            ("system.reg", b"WINE REGISTRY\n"),
            ("drive_c/marker.txt", b"restore-test"),
        ):
            item = tarfile.TarInfo(name)
            item.mode = 0o755 if name.endswith(".txt") else 0o644
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    payload = payload_buffer.getvalue()

    entries = [
        {"path": "dosdevices", "type": "directory", "mode": 0o755, "size": 0},
        {"path": "drive_c", "type": "directory", "mode": 0o755, "size": 0},
        {"path": "system.reg", "type": "file", "mode": 0o644, "size": 14},
        {"path": "drive_c/marker.txt", "type": "file", "mode": 0o755, "size": 12},
    ]
    digest = hashlib.sha256(payload).hexdigest()
    if corrupt_digest:
        digest = "0" * 64
    manifest = {
        "format": "winux-prefix-backup",
        "format_version": 1,
        "architecture": "win64",
        "runtime": "runtime-from-archive-must-not-be-trusted",
        "files": 2,
        "directories": 2,
        "total_bytes": 26,
        "drive_mappings": {"c": "drive_c", "z": "/", "serial": "wine-default"},
        "payload": {"name": "payload.tar", "size": len(payload), "sha256": digest},
        "entries": entries,
    }
    encoded = json.dumps(manifest, separators=(",", ":")).encode()
    Path(path).write_bytes(
        MAGIC + len(payload).to_bytes(8, "big") + payload
        + len(encoded).to_bytes(8, "big") + encoded
    )


class _Runtime:
    name = "local-wine"

    def is_available(self):
        return True

    def validate_prefix(self, path):,        path = Path(path),        return (,            path.is_dir(),            and not path.is_symlink(),            and (path / "drive_c").is_dir(),            and (path / "system.reg").is_file(),        ),,
class _RuntimeManager:
    def __init__(self):
        self.runtime = _Runtime()

    def get_default_name(self):
        return "local-wine"

    def get(self, name=None):
        if name not in (None, "local-wine"):
            raise ValueError("unknown runtime")
        return self.runtime


class _PrefixManager:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir.chmod(0o700)
        self.runtime_manager = _RuntimeManager()

    def validate_name(self, name):
        if not isinstance(name, str) or not name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Invalid prefix name")

    def _ensure_base_dir(self):
        if self.base_dir.is_symlink() or not self.base_dir.is_dir():
            raise ValueError("Unsafe prefix base")

    def get_path(self, name):
        path = self.base_dir / name
        if not self.runtime_manager.get().validate_prefix(path):
            raise ValueError("Invalid restored prefix")
        metadata = json.loads((path / ".winux-prefix.json").read_text())
        if metadata["name"] != name:
            raise ValueError("Metadata name mismatch")
        return path


class PrefixRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.home_patcher = patch.object(Path, "home", return_value=self.home)
        self.home_patcher.start()
        self.addCleanup(self.home_patcher.stop)
        self.base = self.home / ".local/share/winux/prefixes"
        self.base.mkdir(parents=True)
        self.manager = _PrefixManager(self.base)
        self.archive = Path(self.tmp.name) / "prefix.wux"
        make_backup(self.archive)

    def test_restore_creates_private_prefix_and_fresh_metadata(self):
        result = restore_prefix(self.archive, "restored", prefix_manager=self.manager)
        path = Path(result["path"])
        metadata = json.loads((path / ".winux-prefix.json").read_text())
        self.assertEqual(metadata["runtime"], "local-wine")
        self.assertEqual(metadata["architecture"], "win64")
        self.assertEqual((path / "drive_c/marker.txt").read_bytes(), b"restore-test")
        self.assertEqual(os.readlink(path / "dosdevices/c:"), "../drive_c")
        self.assertFalse((path / "dosdevices/z:").exists())
        self.assertEqual((path / "dosdevices").stat().st_mode & 0o777, 0o700)
        self.assertEqual((path / ".winux-prefix.json").stat().st_mode & 0o777, 0o600)

    def test_existing_destination_is_never_overwritten(self):
        existing = self.base / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            restore_prefix(self.archive, "existing", prefix_manager=self.manager)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["existing"])

    def test_digest_failure_publishes_nothing(self):
        make_backup(self.archive, corrupt_digest=True)
        with self.assertRaises(ValueError):
            restore_prefix(self.archive, "bad-digest", prefix_manager=self.manager)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_symlink_archive_is_rejected(self):
        link = Path(self.tmp.name) / "link.wux"
        link.symlink_to(self.archive)
        with self.assertRaises(OSError):
            restore_prefix(link, "linked", prefix_manager=self.manager)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_unavailable_local_runtime_is_rejected(self):
        self.manager.runtime_manager.runtime.is_available = lambda: False
        with self.assertRaises(PrefixRestoreError):
            restore_prefix(self.archive, "no-runtime", prefix_manager=self.manager)
        self.assertEqual(list(self.base.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
