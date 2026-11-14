import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from winux.runtime.manager import RuntimeManager


class RuntimePluginIntegrationTests(unittest.TestCase):
    def test_discovers_installed_entry_point_plugin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            (root / "test_runtime_plugin.py").write_text(
                """
from pathlib import Path

class TestRuntime:
    name = "test-runtime"

    def is_available(self):
        return True

    def version(self):
        return "1.0"

    def validate_prefix(self, prefix_path: Path) -> bool:
        return True

    def create_prefix(self, prefix_path: Path, architecture: str):
        return None

    def run(self, prefix_path: Path, executable: Path, args=None, **kwargs):
        return None

    def install(self, prefix_path: Path, installer: Path, **kwargs):
        return None

    def query_registry(self, prefix_path: Path, key: str, **kwargs):
        return None

    def uninstall(self, prefix_path: Path, command, **kwargs):
        return None
"""
            )

            dist = root / "winux_test_runtime-1.0.dist-info"
            dist.mkdir()

            (dist / "METADATA").write_text(
                "Metadata-Version: 2.1\n"
                "Name: winux-test-runtime\n"
                "Version: 1.0\n"
            )

            (dist / "entry_points.txt").write_text(
                "[winux.runtimes]\n"
                "test-runtime = test_runtime_plugin:TestRuntime\n"
            )

            sys.path.insert(0, str(root))
            importlib.invalidate_caches()

            try:
                manager = RuntimeManager()

                self.assertIn("test-runtime", manager.list())
                self.assertTrue(manager.get("test-runtime").is_available())
            finally:
                sys.path.remove(str(root))
                sys.modules.pop("test_runtime_plugin", None)
                importlib.invalidate_caches()


if __name__ == "__main__":
    unittest.main()
