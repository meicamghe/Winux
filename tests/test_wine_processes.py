import os
import tempfile
import unittest
from pathlib import Path

from winux.core.wine_processes import inspect_prefix_processes


class WineProcessInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.proc = Path(self.temp.name) / "proc"
        self.proc.mkdir()
        self.prefix = Path(self.temp.name) / "prefix"
        self.prefix.mkdir()

    def add_process(self, pid, *, environ=b"", exe="/usr/bin/sleep", comm="sleep"):
        process = self.proc / str(pid)
        process.mkdir()
        (process / "environ").write_bytes(environ)
        (process / "comm").write_text(comm, encoding="utf-8")
        (process / "exe").symlink_to(exe)
        return process

    def test_matching_prefix_environment_is_busy(self):
        self.add_process(
            123,
            environ=f"WINEPREFIX={self.prefix}".encode() + b"\0",
            exe="/usr/lib/wine/wine64",
        )
        result = inspect_prefix_processes(
            self.prefix, proc_root=self.proc, uid=os.getuid()
        )
        self.assertEqual(result["state"], "busy")
        self.assertEqual(result["pids"], ["123"])

    def test_other_prefix_is_not_a_blocker(self):
        other = Path(self.temp.name) / "other"
        self.add_process(
            123,
            environ=f"WINEPREFIX={other}".encode() + b"\0",
            exe="/usr/lib/wine/wine64",
        )
        result = inspect_prefix_processes(
            self.prefix, proc_root=self.proc, uid=os.getuid()
        )
        self.assertEqual(result, {"state": "clear", "pids": [], "reasons": []})

    def test_wine_process_without_prefix_is_unknown(self):
        self.add_process(123, exe="/usr/lib/wine/wine64", comm="wine64")
        result = inspect_prefix_processes(
            self.prefix, proc_root=self.proc, uid=os.getuid()
        )
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["pids"], ["123"])

    def test_implicit_default_prefix_is_busy(self):
        default_prefix = Path.home() / ".wine"
        self.add_process(123, exe="/usr/lib/wine/wineserver", comm="wineserver")
        result = inspect_prefix_processes(
            default_prefix, proc_root=self.proc, uid=os.getuid()
        )
        self.assertEqual(result["state"], "busy")

    def test_unreadable_wine_environment_is_unknown(self):
        self.add_process(123, exe="/usr/lib/wine/wine64", comm="wine64")
        process_environment = self.proc / "123" / "environ"
        process_environment.unlink()
        process_environment.mkdir()
        result = inspect_prefix_processes(
            self.prefix, proc_root=self.proc, uid=os.getuid()
        )
        self.assertEqual(result["state"], "unknown")

    def test_matching_environment_wins_over_unrecognizable_executable(self):
        self.add_process(
            123,
            environ=f"WINEPREFIX={self.prefix}".encode() + b"\0",
            exe="/usr/bin/python",
            comm="python",
        )
        result = inspect_prefix_processes(
            self.prefix, proc_root=self.proc, uid=os.getuid()
        )
        self.assertEqual(result["state"], "busy")

    def test_unreadable_process_table_is_unknown(self):
        result = inspect_prefix_processes(
            self.prefix, proc_root=Path(self.temp.name) / "missing",
            uid=os.getuid(),
        )
        self.assertEqual(result["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
