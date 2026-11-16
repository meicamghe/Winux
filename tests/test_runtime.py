import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from winux.runtime.base import Runtime
from winux.runtime.manager import RuntimeManager
from winux.runtime.wine import WineRuntime


class RuntimeTests(unittest.TestCase):
    def test_wine_environment_uses_absolute_prefix_path(self):
        runtime = WineRuntime()
        with patch.dict(os.environ, {"WINEPREFIX": "/inherited/prefix"}):
            env = runtime._env("relative/prefix")
        self.assertTrue(os.path.isabs(env["WINEPREFIX"]))
        self.assertEqual(env["WINEPREFIX"], os.path.abspath("relative/prefix"))

    def test_wine_environment_overrides_inherited_prefix(self):
        runtime = WineRuntime()
        with patch.dict(os.environ, {"WINEPREFIX": "/inherited/prefix"}):
            env = runtime._env("/selected/prefix")
        self.assertEqual(env["WINEPREFIX"], "/selected/prefix")

    def test_wine_environment_does_not_inherit_prefix_architecture(self):
        runtime = WineRuntime()
        with patch.dict(os.environ, {"WINEARCH": "win32"}):
            env = runtime._env("/selected/prefix")
        self.assertNotIn("WINEARCH", env)

    def test_wine_prefix_creation_sets_requested_architecture(self):
        runtime = WineRuntime()
        with patch.object(runtime, "_find", return_value="/usr/bin/wineboot"), patch(
            "winux.runtime.wine.subprocess.run"
        ) as run:
            runtime.create_prefix(Path("/selected/prefix"), "win64")

        self.assertEqual(run.call_args.kwargs["env"]["WINEPREFIX"], "/selected/prefix")
        self.assertEqual(run.call_args.kwargs["env"]["WINEARCH"], "win64")

    def test_wine_run_preserves_argument_boundaries(self):
        runtime = WineRuntime()
        executable = Path("/prefix/drive_c/Program Files/app.exe")
        with patch.object(runtime, "_find", return_value="/usr/bin/wine"), patch(
            "winux.runtime.wine.subprocess.Popen"
        ) as popen:
            runtime.run(
                Path("/prefix"),
                executable,
                args=["--profile", "two words"],
            )

        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/wine", str(executable), "--profile", "two words"],
        )
        self.assertEqual(
            popen.call_args.kwargs["env"]["WINEPREFIX"],
            "/prefix",
        )

    def test_wine_run_rejects_string_argument_collection(self):
        runtime = WineRuntime()
        with patch.object(runtime, "_find", return_value="/usr/bin/wine"), patch(
            "winux.runtime.wine.subprocess.Popen"
        ) as popen:
            with self.assertRaisesRegex(TypeError, "list or tuple"):
                runtime.run(Path("/prefix"), Path("/app.exe"), args="--flag")
        popen.assert_not_called()

    def test_wine_run_rejects_non_string_arguments(self):
        runtime = WineRuntime()
        with patch.object(runtime, "_find", return_value="/usr/bin/wine"), patch(
            "winux.runtime.wine.subprocess.Popen"
        ) as popen:
            with self.assertRaisesRegex(TypeError, "only strings"):
                runtime.run(Path("/prefix"), Path("/app.exe"), args=["--flag", 3])
        popen.assert_not_called()

    def test_wine_run_rejects_nul_characters_in_arguments(self):
        runtime = WineRuntime()
        with patch.object(runtime, "_find", return_value="/usr/bin/wine"), patch(
            "winux.runtime.wine.subprocess.Popen"
        ) as popen:
            with self.assertRaisesRegex(ValueError, "NUL"):
                runtime.run(Path("/prefix"), Path("/app.exe"), args=["bad\x00arg"])
        popen.assert_not_called()

    def test_wine_runtime_implements_interface(self):
        runtime = WineRuntime()
        self.assertIsInstance(runtime, Runtime)

    def test_manager_rejects_invalid_default_runtime_names(self):
        for name in ([], {}, 1, False, ""):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "Invalid default runtime"):
                    RuntimeManager(default_runtime=name, discover=False)

    def test_manager_selects_wine_by_default(self):
        manager = RuntimeManager()
        self.assertEqual(manager.get_default_name(), "wine")
        self.assertIsInstance(manager.get(), WineRuntime)

    def test_manager_lists_registered_runtimes(self):
        manager = RuntimeManager()
        result = manager.list()

        self.assertIn("wine", result)
        self.assertTrue(result["wine"]["default"])

    def test_manager_rejects_non_string_runtime_names(self):
        manager = RuntimeManager(discover=False)
        for name in ([], {}, 1, False):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "Invalid runtime name"):
                    manager.get(name)

    def test_manager_rejects_empty_runtime_name(self):
        manager = RuntimeManager()

        with self.assertRaisesRegex(ValueError, "Invalid runtime name"):
            manager.get("")

        with self.assertRaisesRegex(ValueError, "Invalid runtime name"):
            manager.set_default("")

        self.assertEqual(manager.get_default_name(), "wine")

    def test_manager_rejects_unknown_runtime(self):
        manager = RuntimeManager()

        with self.assertRaises(ValueError):
            manager.get("unknown")

    def test_manager_rejects_duplicate_runtime(self):
        manager = RuntimeManager()

        with self.assertRaises(ValueError):
            manager.register(WineRuntime())

    def test_manager_rejects_runtime_missing_required_methods(self):
        manager = RuntimeManager()

        class IncompleteRuntime:
            name = "incomplete"

            def is_available(self):
                return True

        with self.assertRaisesRegex(TypeError, "missing required methods"):
            manager.register(IncompleteRuntime())

    def test_manager_rejects_runtime_name_with_whitespace(self):
        manager = RuntimeManager()
        runtime = Mock(spec=Runtime)
        runtime.name = " invalid "

        with self.assertRaisesRegex(ValueError, "surrounding whitespace"):
            manager.register(runtime)

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

    def test_manager_does_not_call_callable_runtime_instance(self):
        class CallableRuntime:
            name = "callable-runtime"

            def __call__(self):
                raise AssertionError("runtime instance must not be called")

            def is_available(self): return True
            def version(self): return "test"
            def validate_prefix(self, prefix_path): return True
            def create_prefix(self, prefix_path, architecture): pass
            def run(self, prefix_path, executable, args=None, **kwargs): pass
            def install(self, prefix_path, installer, **kwargs): pass
            def query_registry(self, prefix_path, key, **kwargs): pass
            def uninstall(self, prefix_path, command, **kwargs): pass

        runtime = CallableRuntime()
        plugin = Mock()
        plugin.name = "callable-runtime"
        plugin.load.return_value = runtime

        with patch("winux.runtime.manager.entry_points", return_value=[plugin]):
            manager = RuntimeManager()

        self.assertIs(manager.get("callable-runtime"), runtime)

    def test_manager_discovers_external_runtime_plugins(self):
        runtime = Mock(spec=Runtime)
        runtime.name = "external-runtime"
        runtime.is_available.return_value = True

        plugin = Mock()
        plugin.load.return_value = lambda: runtime

        with patch("winux.runtime.manager.entry_points", return_value=[plugin]):
            manager = RuntimeManager()

        self.assertIs(manager.get("external-runtime"), runtime)

    def test_manager_records_plugin_load_errors(self):
        broken_plugin = Mock()
        broken_plugin.name = "broken-runtime"
        broken_plugin.load.side_effect = RuntimeError("plugin failed")

        with patch("winux.runtime.manager.entry_points", return_value=[broken_plugin]):
            manager = RuntimeManager()

        self.assertIn("wine", manager.list())
        self.assertEqual(len(manager.list()), 1)

        errors = manager.plugin_errors()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["plugin"], "broken-runtime")
        self.assertEqual(errors[0]["stage"], "load")
        self.assertIn("plugin failed", errors[0]["error"])

    def test_manager_records_plugin_registration_errors(self):
        plugin = Mock()
        plugin.name = "invalid-runtime"
        plugin.load.return_value = lambda: object()

        with patch("winux.runtime.manager.entry_points", return_value=[plugin]):
            manager = RuntimeManager()

        errors = manager.plugin_errors()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["plugin"], "invalid-runtime")
        self.assertEqual(errors[0]["stage"], "registration")
        self.assertIn("valid name", errors[0]["error"])

    def test_manager_records_discovery_errors(self):
        with patch(
            "winux.runtime.manager.entry_points",
            side_effect=RuntimeError("discovery failed"),
        ):
            manager = RuntimeManager()

        errors = manager.plugin_errors()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["stage"], "discovery")
        self.assertIn("discovery failed", errors[0]["error"])

    def test_plugin_errors_returns_independent_snapshot(self):
        plugin = Mock()
        plugin.name = "broken-runtime"
        plugin.load.side_effect = RuntimeError("plugin failed")

        with patch("winux.runtime.manager.entry_points", return_value=[plugin]):
            manager = RuntimeManager()

        errors = manager.plugin_errors()
        errors[0]["plugin"] = "modified"
        errors.append({"plugin": "injected"})

        stored_errors = manager.plugin_errors()
        self.assertEqual(len(stored_errors), 1)
        self.assertEqual(stored_errors[0]["plugin"], "broken-runtime")

    def test_manager_rejects_unavailable_default_runtime(self):
        manager = RuntimeManager()
        runtime = Mock(spec=Runtime)
        runtime.name = "unavailable-runtime"
        runtime.is_available.return_value = False

        manager.register(runtime)

        with self.assertRaises(RuntimeError):
            manager.set_default("unavailable-runtime")



    def test_wine_install_forwards_arguments_for_exe_and_msi(self):
        runtime = WineRuntime()
        for installer, tool, expected in (
            (
                Path("/tmp/setup.exe"),
                "wine",
                ["/usr/bin/wine", "/tmp/setup.exe", "/S", "/D=C:\\Apps\\Example"],
            ),
            (
                Path("/tmp/setup.msi"),
                "msiexec",
                ["/usr/bin/msiexec", "/i", "/tmp/setup.msi", "/qn", "/norestart"],
            ),
        ):
            with self.subTest(installer=installer.suffix):
                with (
                    patch.object(runtime, "_find", return_value=f"/usr/bin/{tool}"),
                    patch("winux.runtime.wine.subprocess.run") as run,
                ):
                    runtime.install(
                        Path("/prefix"),
                        installer,
                        args=(
                            ["/S", "/D=C:\\Apps\\Example"]
                            if installer.suffix == ".exe"
                            else ["/qn", "/norestart"]
                        ),
                        timeout=60,
                    )

                self.assertEqual(run.call_args.args[0], expected)
                self.assertEqual(run.call_args.kwargs["env"]["WINEPREFIX"], "/prefix")
                self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_wine_install_rejects_invalid_argument_collections(self):
        runtime = WineRuntime()
        for arguments in ("not-a-list", ["/S", 3], ["bad\x00argument"]):
            with self.subTest(arguments=arguments):
                with patch("winux.runtime.wine.subprocess.run") as run:
                    with self.assertRaises((TypeError, ValueError)):
                        runtime.install(
                            Path("/prefix"),
                            Path("/tmp/setup.exe"),
                            args=arguments,
                        )
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
