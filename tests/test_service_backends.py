import unittest
from unittest.mock import patch

from winux.platform.service_backends import ServiceBackendManager


class FakeBackend:
    def install(self, *args, **kwargs): pass
    def unit_exists(self, *args, **kwargs): return True
    def reload(self, *args, **kwargs): pass
    def start(self, *args, **kwargs): pass
    def stop(self, *args, **kwargs): pass
    def restart(self, *args, **kwargs): pass
    def enable(self, *args, **kwargs): pass
    def disable(self, *args, **kwargs): pass
    def status(self, *args, **kwargs): return {}
    def remove(self, *args, **kwargs): return True


class ServiceBackendManagerTests(unittest.TestCase):
    def test_manager_rejects_invalid_default_backend_names(self):
        for name in ([], {}, 1, False, ""):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "Invalid default service backend"):
                    ServiceBackendManager(default_backend=name, discover=False)

    def test_systemd_is_registered_as_default(self):
        manager = ServiceBackendManager(discover=False)
        self.assertEqual(manager.get_default_name(), "systemd")
        self.assertEqual(type(manager.get()).__name__, "SystemdUserBackend")

    def test_register_and_select_custom_backend(self):
        manager = ServiceBackendManager(discover=False)
        manager.register("fake", FakeBackend)
        self.assertIsInstance(manager.get("fake"), FakeBackend)
        manager.set_default("fake")
        self.assertIsInstance(manager.get(), FakeBackend)

    def test_rejects_duplicate_and_invalid_backends(self):
        manager = ServiceBackendManager(discover=False)
        with self.assertRaisesRegex(ValueError, "already registered"):
            manager.register("systemd", FakeBackend)
        with self.assertRaisesRegex(TypeError, "service contract"):
            manager.register("invalid", object())

    def test_discovery_records_plugin_load_errors(self):
        class BrokenEntryPoint:
            name = "broken"
            def load(self):
                raise ImportError("broken plugin")

        manager = ServiceBackendManager(discover=False)
        with patch(
            "winux.platform.service_backends.entry_points",
            return_value=[BrokenEntryPoint()],
        ):
            manager.discover()
        self.assertEqual(manager.plugin_errors()[0]["plugin"], "broken")
        self.assertEqual(manager.plugin_errors()[0]["stage"], "load")

    def test_callable_backend_instance_is_not_treated_as_factory(self):
        class CallableBackend(FakeBackend):
            def __call__(self):
                raise AssertionError("backend instance must not be called")

        backend = CallableBackend()
        manager = ServiceBackendManager(discover=False)
        manager.register("callable-backend", backend)
        self.assertIs(manager.get("callable-backend"), backend)
        self.assertEqual(
            manager.list()["callable-backend"]["backend"],
            "CallableBackend",
        )
        self.assertTrue(manager.list()["callable-backend"]["loaded"])

    def test_non_string_backend_names_are_rejected(self):
        manager = ServiceBackendManager(discover=False)
        for name in ([], {}, 1, False):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "Invalid service backend name"):
                    manager.get(name)

    def test_backend_factory_is_created_only_when_selected(self):
        calls = []

        def factory():
            calls.append("created")
            return FakeBackend()

        manager = ServiceBackendManager(discover=False)
        manager.register("lazy", factory)
        self.assertEqual(calls, [])
        self.assertFalse(manager.list()["lazy"]["loaded"])
        self.assertEqual(manager.list()["lazy"]["backend"], "factory")
        backend = manager.get("lazy")
        self.assertIsInstance(backend, FakeBackend)
        self.assertEqual(calls, ["created"])
        self.assertTrue(manager.list()["lazy"]["loaded"])
        self.assertIs(manager.get("lazy"), backend)
        self.assertEqual(calls, ["created"])

    def test_callable_factory_object_is_listed_safely(self):
        class Factory:
            def __call__(self):
                return FakeBackend()

        manager = ServiceBackendManager(discover=False)
        manager.register("callable-object", Factory())
        self.assertEqual(
            manager.list()["callable-object"]["backend"],
            "Factory",
        )
        self.assertFalse(manager.list()["callable-object"]["loaded"])

    def test_invalid_factory_result_is_rejected(self):
        manager = ServiceBackendManager(discover=False)
        manager.register("invalid-factory", lambda: object())
        with self.assertRaisesRegex(TypeError, "service contract"):
            manager.get("invalid-factory")

    def test_unknown_backend_is_rejected(self):
        manager = ServiceBackendManager(discover=False)
        with self.assertRaisesRegex(ValueError, "Unknown service backend"):
            manager.get("missing")


if __name__ == "__main__":
    unittest.main()
