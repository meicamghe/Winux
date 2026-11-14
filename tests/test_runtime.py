import unittest
from unittest.mock import Mock, patch

from winux.runtime.base import Runtime
from winux.runtime.manager import RuntimeManager
from winux.runtime.wine import WineRuntime


class RuntimeTests(unittest.TestCase):
    def test_wine_runtime_implements_interface(self):
        runtime = WineRuntime()
        self.assertIsInstance(runtime, Runtime)

    def test_manager_selects_wine_by_default(self):
        manager = RuntimeManager()
        self.assertEqual(manager.get_default_name(), "wine")
        self.assertIsInstance(manager.get(), WineRuntime)

    def test_manager_lists_registered_runtimes(self):
        manager = RuntimeManager()
        result = manager.list()

        self.assertIn("wine", result)
        self.assertTrue(result["wine"]["default"])

    def test_manager_rejects_unknown_runtime(self):
        manager = RuntimeManager()

        with self.assertRaises(ValueError):
            manager.get("unknown")

    def test_manager_rejects_duplicate_runtime(self):
        manager = RuntimeManager()

        with self.assertRaises(ValueError):
            manager.register(WineRuntime())

    def test_manager_can_register_another_runtime(self):
        manager = RuntimeManager()
        runtime = Mock(spec=Runtime)
        runtime.name = "test-runtime"
        runtime.is_available.return_value = True

        manager.register(runtime)

        self.assertIs(manager.get("test-runtime"), runtime)

    def test_manager_can_change_default_runtime(self):
        manager = RuntimeManager()
        runtime = Mock(spec=Runtime)
        runtime.name = "test-runtime"
        runtime.is_available.return_value = True

        manager.register(runtime)
        manager.set_default("test-runtime")

        self.assertEqual(manager.get_default_name(), "test-runtime")
        self.assertIs(manager.get(), runtime)

    def test_manager_discovers_external_runtime_plugins(self):
        runtime = Mock(spec=Runtime)
        runtime.name = "external-runtime"
        runtime.is_available.return_value = True

        plugin = Mock()
        plugin.load.return_value = lambda: runtime

        with patch("winux.runtime.manager.entry_points", return_value=[plugin]):
            manager = RuntimeManager()

        self.assertIs(manager.get("external-runtime"), runtime)

    def test_manager_ignores_broken_runtime_plugins(self):
        broken_plugin = Mock()
        broken_plugin.load.side_effect = RuntimeError("plugin failed")

        with patch("winux.runtime.manager.entry_points", return_value=[broken_plugin]):
            manager = RuntimeManager()

        self.assertIn("wine", manager.list())
        self.assertEqual(len(manager.list()), 1)

    def test_manager_rejects_unavailable_default_runtime(self):
        manager = RuntimeManager()
        runtime = Mock(spec=Runtime)
        runtime.name = "unavailable-runtime"
        runtime.is_available.return_value = False

        manager.register(runtime)

        with self.assertRaises(RuntimeError):
            manager.set_default("unavailable-runtime")


if __name__ == "__main__":
    unittest.main()
