import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from winux.core.services import ServiceManager
from winux.core.service_contracts import ServiceBackend
from winux.platform.service_backend import SystemdUserBackend
from winux.platform.service_backends import ServiceBackendManager


SERVICE_ID = "a" * 32


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.installed = {}
        self.failures = {}
        self.current_status = {
            "active_state": "inactive",
            "sub_state": "dead",
            "unit_file_state": "enabled",
        }

    def _fail(self, action):
        error = self.failures.get(action)
        if error:
            raise error

    def install(self, service_id, command, description, restart):
        self.calls.append(("install", service_id))
        self._fail("install")
        self.installed[service_id] = {
            "command": command,
            "description": description,
            "restart": restart,
        }
        self.current_status["load_state"] = "loaded"

    def unit_exists(self, service_id):
        return service_id in self.installed

    def reload(self):
        self.calls.append(("reload", None))
        self._fail("reload")
        self.current_status["load_state"] = (
            "loaded" if self.installed else "not-found"
        )

    def start(self, service_id):
        self.calls.append(("start", service_id))
        self._fail("start")
        self.current_status["active_state"] = "active"

    def stop(self, service_id):
        self.calls.append(("stop", service_id))
        self._fail("stop")
        self.current_status["active_state"] = "inactive"

    def restart(self, service_id):
        self.calls.append(("restart", service_id))

    def enable(self, service_id):
        self.calls.append(("enable", service_id))
        self._fail("enable")
        self.current_status["unit_file_state"] = "enabled"

    def disable(self, service_id):
        self.calls.append(("disable", service_id))
        self._fail("disable")
        self.current_status["unit_file_state"] = "disabled"

    def status(self, service_id):
        return {
            "unit": f"winux-{service_id}.service",
            "load_state": self.current_status.get("load_state", "loaded"),
            **self.current_status,
            "unit_file_state": self.current_status.get(
                "unit_file_state", "unknown"
            ),
        }

    def remove(self, service_id):
        self.calls.append(("remove", service_id))
        self._fail("remove")
        self.installed.pop(service_id, None)
        self.current_status["load_state"] = "not-found"
        self._fail("remove_after")


class FakePrefixManager:
    def __init__(self, prefix_path):
        self.prefix_path = prefix_path
        self.runtime = SimpleNamespace(
            name="wine",
            is_available=lambda: True,
        )

    def validate_name(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError("Invalid prefix name")

    def get_path(self, name):
        return self.prefix_path

    def get_runtime(self, name):
        return self.runtime


class ServiceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        root = Path(self.temp_dir.name)
        self.prefix_path = root / "prefix"
        self.drive_c = self.prefix_path / "drive_c"
        self.drive_c.mkdir(parents=True)

        self.executable = self.drive_c / "Program Files" / "Example" / "app.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"test executable")

        self.state_file = root / "services.json"
        self.backend = FakeBackend()
        self.prefix_manager = FakePrefixManager(self.prefix_path)

        self.application_manager = Mock()
        self.application_manager.info.return_value = {
            "DisplayName": "Example Application",
            "executable_path": str(self.executable),
        }

        self.manager = ServiceManager(
            backend=self.backend,
            state_file=self.state_file,
            prefix_manager=self.prefix_manager,
            application_manager=self.application_manager,
        )

    def test_fake_backend_implements_service_contract(self):
        self.assertIsInstance(self.backend, ServiceBackend)

    def test_service_manager_uses_selected_backend_registry(self):
        backends = ServiceBackendManager(discover=False)
        backends.register("fake", self.backend.__class__)
        manager = ServiceManager(
            backend_name="fake",
            backend_manager=backends,
            state_file=self.state_file,
            prefix_manager=self.prefix_manager,
            application_manager=self.application_manager,
        )
        self.assertIs(manager.backend, backends.get("fake"))

    def test_preserves_falsey_injected_managers(self):
        class FalseyMock(Mock):
            def __bool__(self):
                return False

        prefix_manager = FalseyMock()
        application_manager = FalseyMock()
        manager = ServiceManager(
            backend=self.backend,
            state_file=self.state_file,
            prefix_manager=prefix_manager,
            application_manager=application_manager,
        )

        self.assertIs(manager.prefix_manager, prefix_manager)
        self.assertIs(manager.application_manager, application_manager)

    def test_rejects_backend_class_instead_of_instance(self):
        class BackendClass:
            def install(self, *args, **kwargs): pass
            def unit_exists(self, *args, **kwargs): return True
            def reload(self, *args, **kwargs): pass
            def start(self, *args, **kwargs): pass
            def stop(self, *args, **kwargs): pass
            def restart(self, *args, **kwargs): pass
            def enable(self, *args, **kwargs): pass
            def disable(self, *args, **kwargs): pass
            def status(self, *args, **kwargs): return {}
            def remove(self, *args, **kwargs): pass

        with self.assertRaisesRegex(TypeError, "service contract"):
            ServiceManager(backend=BackendClass, state_file=self.state_file)

    def test_rejects_backend_missing_required_operations(self):
        with self.assertRaisesRegex(TypeError, "service contract"):
            ServiceManager(backend=object(), state_file=self.state_file)

    def create_service(self):
        return self.manager.create(
            name="Example Service",
            prefix_name="test-prefix",
            application_id="example-id",
        )

    def test_create_registers_service_and_persists_definition(self):
        record = self.create_service()

        self.assertEqual(record["name"], "Example Service")
        self.assertEqual(record["runtime"], "wine")
        self.assertEqual(record["executable"], str(self.executable))
        self.assertEqual(len(record["id"]), 32)

        stored = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(stored[0]["id"], record["id"])

        installation = self.backend.installed[record["id"]]
        self.assertTrue(
            any(
                item.endswith("service_runner.py")
                for item in installation["command"]
            )
        )
        self.assertEqual(installation["restart"], "on-failure")

        self.assertEqual(
            self.state_file.stat().st_mode & 0o777,
            0o600,
        )

    def test_create_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            self.manager.create("", "test-prefix", "example-id")

        self.assertEqual(self.backend.calls, [])

    def test_create_rejects_non_string_restart_policy(self):
        with self.assertRaisesRegex(ValueError, "restart policy"):
            self.manager.create(
                "Example",
                "test-prefix",
                "example-id",
                restart=[],
            )

        self.assertEqual(self.backend.calls, [])

    def test_create_rejects_invalid_restart_policy(self):
        with self.assertRaises(ValueError):
            self.manager.create(
                "Example",
                "test-prefix",
                "example-id",
                restart="unexpected",
            )

        self.assertEqual(self.backend.calls, [])

    def test_create_rejects_duplicate_name_case_insensitively(self):
        self.create_service()

        with self.assertRaises(FileExistsError):
            self.manager.create(
                "example service",
                "test-prefix",
                "example-id",
            )

    def test_create_rejects_executable_outside_prefix(self):
        outside = Path(self.temp_dir.name) / "outside.exe"
        outside.write_bytes(b"outside")
        self.application_manager.info.return_value["executable_path"] = str(
            outside
        )

        with self.assertRaisesRegex(ValueError, "outside"):
            self.create_service()

        self.assertEqual(self.backend.calls, [])

    def test_create_rejects_missing_executable(self):
        self.application_manager.info.return_value["executable_path"] = str(
            self.drive_c / "missing.exe"
        )

        with self.assertRaises(FileNotFoundError):
            self.create_service()

        self.assertEqual(self.backend.calls, [])

    def test_create_removes_unit_if_state_persistence_fails(self):
        with patch.object(
            self.manager,
            "_write",
            side_effect=OSError("storage failure"),
        ):
            with self.assertRaises(OSError):
                self.create_service()

        self.assertEqual(self.backend.calls[0][0], "install")
        self.assertEqual(self.backend.calls[1][0], "remove")

    def test_create_reports_incomplete_rollback(self):
        self.backend.failures["remove"] = RuntimeError(
            "unit removal failure"
        )

        with patch.object(
            self.manager,
            "_write",
            side_effect=OSError("storage failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "rollback was incomplete",
            ) as context:
                self.create_service()

        self.assertIn("storage failure", str(context.exception))
        self.assertIn("unit removal failure", str(context.exception))
        self.assertEqual(len(self.backend.installed), 1)

    def test_state_file_rejects_symlink_parent_on_read(self):
        root = Path(self.temp_dir.name)
        real_dir = root / "real-state"
        real_dir.mkdir()
        linked_dir = root / "linked-state"
        linked_dir.symlink_to(real_dir, target_is_directory=True)
        manager = ServiceManager(
            backend=self.backend,
            state_file=linked_dir / "services.json",
            prefix_manager=self.prefix_manager,
            application_manager=self.application_manager,
        )

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            manager.list()

    def test_state_file_rejects_symlink_parent_on_write(self):
        root = Path(self.temp_dir.name)
        real_dir = root / "real-state"
        real_dir.mkdir()
        linked_dir = root / "linked-state"
        linked_dir.symlink_to(real_dir, target_is_directory=True)
        manager = ServiceManager(
            backend=self.backend,
            state_file=linked_dir / "services.json",
            prefix_manager=self.prefix_manager,
            application_manager=self.application_manager,
        )

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            manager._write([])

    def test_state_path_rejects_directory_instead_of_file(self):
        self.state_file.mkdir()

        with self.assertRaisesRegex(ValueError, "regular file"):
            self.manager._write([])

    def test_state_file_rejects_dangling_symlink(self):
        target = self.state_file.parent / "missing-services.json"
        self.state_file.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            self.manager.list()

    def test_state_file_rejects_non_string_restart_policy(self):
        self.state_file.write_text(
            json.dumps([{
                "id": "a" * 32,
                "name": "Example",
                "prefix": "test-prefix",
                "application_id": "example-id",
                "application": "Example",
                "runtime": "wine",
                "executable": "/prefix/app.exe",
                "restart": [],
            }]),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "restart policy",
        ):
            self.manager.list()

    def test_list_returns_service_status(self):
        record = self.create_service()

        result = self.manager.list()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], record["id"])
        self.assertEqual(result[0]["status"]["active_state"], "inactive")

    def test_start_stop_restart_enable_disable(self):
        record = self.create_service()
        service_id = record["id"]

        self.manager.start(service_id)
        self.manager.stop(service_id)
        self.manager.restart(service_id)
        self.manager.enable(service_id)
        self.manager.disable(service_id)

        actions = [call[0] for call in self.backend.calls]
        self.assertEqual(
            actions,
            ["install", "start", "stop", "restart", "enable", "disable"],
        )

    def test_get_rejects_unknown_service(self):
        with self.assertRaises(KeyError):
            self.manager.get("unknown")

    def test_delete_removes_backend_unit_and_definition(self):
        record = self.create_service()

        result = self.manager.delete(record["id"])

        self.assertEqual(result["id"], record["id"])
        self.assertEqual(self.manager.list(), [])
        self.assertNotIn(record["id"], self.backend.installed)

        actions = [call[0] for call in self.backend.calls]
        # The fake backend reports inactive + enabled. Stopping is
        # unnecessary, but disabling and removing are required.
        self.assertEqual(
            actions,
            ["install", "disable", "remove"],
        )

    def test_delete_refuses_when_backend_state_is_unknown(self):
        record = self.create_service()
        self.backend.current_status["load_state"] = "unknown"
        self.backend.current_status["active_state"] = "unknown"
        self.backend.current_status["unit_file_state"] = "unknown"

        with self.assertRaisesRegex(RuntimeError, "state is unknown"):
            self.manager.delete(record["id"])

        self.assertEqual(len(self.manager.list()), 1)
        self.assertIn(record["id"], self.backend.installed)
        actions = [call[0] for call in self.backend.calls]
        self.assertEqual(actions, ["install"])

    def test_delete_does_not_stop_or_disable_inactive_disabled_service(self):
        record = self.create_service()

        self.backend.current_status["unit_file_state"] = "disabled"

        self.manager.delete(record["id"])

        actions = [call[0] for call in self.backend.calls]
        self.assertEqual(actions, ["install", "remove"])

    def test_delete_stops_active_service_before_removing(self):
        record = self.create_service()
        self.backend.current_status["active_state"] = "active"

        self.manager.delete(record["id"])

        actions = [call[0] for call in self.backend.calls]
        self.assertEqual(
            actions,
            ["install", "stop", "disable", "remove"],
        )

    def test_delete_restores_service_if_stop_fails(self):
        record = self.create_service()
        self.backend.current_status["active_state"] = "active"
        self.backend.failures["stop"] = RuntimeError("stop failure")

        with self.assertRaisesRegex(RuntimeError, "stop failure"):
            self.manager.delete(record["id"])

        self.assertEqual(len(self.manager.list()), 1)
        self.assertIn(record["id"], self.backend.installed)
        self.assertEqual(
            self.backend.current_status["active_state"],
            "active",
        )

    def test_delete_restores_enabled_state_if_disable_fails(self):
        record = self.create_service()
        self.backend.failures["disable"] = RuntimeError("disable failure")

        with self.assertRaisesRegex(RuntimeError, "disable failure"):
            self.manager.delete(record["id"])

        self.assertEqual(len(self.manager.list()), 1)
        self.assertIn(record["id"], self.backend.installed)
        self.assertEqual(
            self.backend.current_status["unit_file_state"],
            "enabled",
        )

    def test_delete_restores_unit_if_state_write_fails(self):
        record = self.create_service()

        with patch.object(
            self.manager,
            "_write",
            side_effect=OSError("storage failure"),
        ):
            with self.assertRaisesRegex(OSError, "storage failure"):
                self.manager.delete(record["id"])

        self.assertIn(record["id"], self.backend.installed)
        self.assertEqual(
            self.backend.current_status["unit_file_state"],
            "enabled",
        )
        self.assertEqual(len(self.manager.list()), 1)

    def test_delete_restores_unit_after_remove_unlinks_then_fails(self):
        record = self.create_service()
        self.backend.failures["remove_after"] = RuntimeError(
            "daemon reload failure"
        )

        with self.assertRaisesRegex(RuntimeError, "daemon reload failure"):
            self.manager.delete(record["id"])

        self.assertIn(record["id"], self.backend.installed)
        self.assertTrue(self.backend.unit_exists(record["id"]))
        self.assertEqual(
            self.backend.current_status["load_state"],
            "loaded",
        )
        self.assertEqual(
            self.backend.current_status["unit_file_state"],
            "enabled",
        )
        self.assertEqual(len(self.manager.list()), 1)

    def test_delete_reloads_existing_unit_when_load_state_unknown(self):
        record = self.create_service()
        self.backend.current_status["load_state"] = "unknown"
        self.backend.failures["remove"] = RuntimeError("remove failure")

        with self.assertRaisesRegex(RuntimeError, "remove failure"):
            self.manager.delete(record["id"])

        self.assertIn(("reload", None), self.backend.calls)
        self.assertTrue(self.backend.unit_exists(record["id"]))
        self.assertEqual(
            self.backend.current_status["load_state"],
            "loaded",
        )

    def test_delete_reports_incomplete_rollback(self):
        record = self.create_service()
        self.backend.failures["remove"] = RuntimeError("remove failure")
        self.backend.failures["enable"] = RuntimeError("restore failure")

        with self.assertRaisesRegex(RuntimeError, "rollback was incomplete"):
            self.manager.delete(record["id"])

        self.assertEqual(len(self.manager.list()), 1)
        self.assertIn(record["id"], self.backend.installed)

    def test_get_definition_returns_copy(self):
        record = self.create_service()

        result = self.manager.get_definition(record["id"])
        result["name"] = "Changed"

        self.assertEqual(
            self.manager.get_definition(record["id"])["name"],
            "Example Service",
        )

    def test_create_rejects_root_user(self):
        with patch("winux.core.services.os.geteuid", return_value=0):
            with self.assertRaisesRegex(PermissionError, "root"):
                self.create_service()

        self.assertEqual(self.backend.calls, [])

    def test_state_file_rejects_symbolic_link(self):
        target = Path(self.temp_dir.name) / "target.json"
        target.write_text("[]", encoding="utf-8")
        self.state_file.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "symlink"):
            self.manager.list()


    def test_state_file_rejects_incomplete_record(self):
        self.state_file.write_text(
            json.dumps([{"id": "a" * 32}]),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "Invalid service record"):
            self.manager.list()

    def test_state_file_rejects_invalid_service_id(self):
        self.state_file.write_text(
            json.dumps([{
                "id": "../invalid",
                "name": "Example",
                "prefix": "test-prefix",
                "application_id": "example-id",
                "application": "Example",
                "runtime": "wine",
                "executable": "/prefix/app.exe",
                "restart": "on-failure",
            }]),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "service ID"):
            self.manager.list()

    def test_state_file_rejects_duplicate_ids(self):
        record = {
            "id": "a" * 32,
            "name": "Example",
            "prefix": "test-prefix",
            "application_id": "example-id",
            "application": "Example",
            "runtime": "wine",
            "executable": "/prefix/app.exe",
            "restart": "on-failure",
        }
        duplicate = dict(record, name="Another")

        self.state_file.write_text(
            json.dumps([record, duplicate]),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "duplicate service ID"):
            self.manager.list()


class SystemdUserBackendTests(unittest.TestCase):
    def test_systemd_backend_implements_service_contract(self):
        backend = SystemdUserBackend(
            systemctl="/usr/bin/systemctl",
            unit_dir=Path("/tmp/winux-test-systemd-user"),
        )
        self.assertIsInstance(backend, ServiceBackend)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.unit_dir = Path(self.temp_dir.name) / "systemd" / "user"
        self.backend = SystemdUserBackend(
            systemctl="/usr/bin/systemctl",
            unit_dir=self.unit_dir,
        )

    def test_unit_name_rejects_invalid_service_id(self):
        for value in ("", "abc", "../escape", "A" * 32, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.backend._unit_name(value)

    @patch("winux.platform.service_backend.subprocess.run")
    def test_install_writes_secure_unit_and_reloads_systemd(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        path = Path(
            self.backend.install(
                SERVICE_ID,
                ["/usr/bin/python3", "-m", "winux", "service", "_run", SERVICE_ID],
                "Example service",
                restart="on-failure",
            )
        )

        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        content = path.read_text(encoding="utf-8")
        self.assertIn("Type=simple", content)
        self.assertIn("Restart=on-failure", content)
        self.assertIn("KillMode=control-group", content)
        self.assertIn("ExecStart=", content)

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1], "daemon-reload")

    def test_install_rejects_invalid_restart_policy(self):
        with self.assertRaises(ValueError):
            self.backend.install(
                SERVICE_ID,
                ["/usr/bin/python3"],
                "Example",
                restart="invalid",
            )

    def test_install_rejects_empty_command(self):
        with self.assertRaises(ValueError):
            self.backend.install(
                SERVICE_ID,
                [],
                "Example",
            )

    def test_install_rejects_multiline_description(self):
        with self.assertRaises(ValueError):
            self.backend.install(
                SERVICE_ID,
                ["/usr/bin/python3"],
                "Example\nInjected=setting",
            )

    @patch("winux.platform.service_backend.subprocess.run")
    def test_status_parses_systemd_properties(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "LoadState=loaded\n"
                "ActiveState=active\n"
                "SubState=running\n"
                "UnitFileState=enabled\n"
            ),
            stderr="",
        )

        result = self.backend.status(SERVICE_ID)

        self.assertEqual(result["load_state"], "loaded")
        self.assertEqual(result["active_state"], "active")
        self.assertEqual(result["sub_state"], "running")
        self.assertEqual(result["unit_file_state"], "enabled")

    @patch("winux.platform.service_backend.subprocess.run")
    def test_status_handles_missing_unit(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="not found",
        )

        result = self.backend.status(SERVICE_ID)

        self.assertEqual(result["load_state"], "unknown")
        self.assertEqual(result["active_state"], "unknown")
        self.assertEqual(result["error"], "not found")

    @patch("winux.platform.service_backend.subprocess.run")
    def test_install_preserves_existing_unit_directory_permissions(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        self.unit_dir.mkdir(parents=True)
        self.unit_dir.chmod(0o755)

        self.backend.install(
            SERVICE_ID,
            ["/usr/bin/python3"],
            "Example",
        )

        self.assertEqual(self.unit_dir.stat().st_mode & 0o777, 0o755)

    def test_install_rejects_symlink_in_parent_path(self):
        target = Path(self.temp_dir.name) / "real-parent"
        target.mkdir()

        link = Path(self.temp_dir.name) / "linked-parent"
        link.symlink_to(target, target_is_directory=True)

        backend = SystemdUserBackend(
            systemctl="/usr/bin/systemctl",
            unit_dir=link / "user",
        )

        with self.assertRaisesRegex(ValueError, "symbolic links"):
            backend.install(
                SERVICE_ID,
                ["/usr/bin/python3"],
                "Example",
            )

    def test_install_rejects_existing_unit(self):
        self.unit_dir.mkdir(parents=True)
        unit = self.unit_dir / f"winux-{SERVICE_ID}.service"
        unit.write_text("Existing unit", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            self.backend.install(
                SERVICE_ID,
                ["/usr/bin/python3"],
                "Example",
            )

        self.assertEqual(
            unit.read_text(encoding="utf-8"),
            "Existing unit",
        )

    def test_install_rejects_control_characters_in_arguments(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            self.backend.install(
                SERVICE_ID,
                ["/usr/bin/python3", "bad\nargument"],
                "Example",
            )

    def test_install_rejects_control_characters_in_description(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            self.backend.install(
                SERVICE_ID,
                ["/usr/bin/python3"],
                "Example\x01Injected",
            )

    def test_install_rejects_symlink_unit_directory(self):
        target = Path(self.temp_dir.name) / "target"
        target.mkdir()
        link = Path(self.temp_dir.name) / "linked-unit-dir"
        link.symlink_to(target, target_is_directory=True)

        backend = SystemdUserBackend(
            systemctl="/usr/bin/systemctl",
            unit_dir=link,
        )

        with self.assertRaisesRegex(ValueError, "symbolic links"):
            backend.install(
                SERVICE_ID,
                ["/usr/bin/python3"],
                "Example",
            )

    def test_unit_exists_returns_false_when_directory_is_missing(self):
        self.assertFalse(self.backend.unit_exists(SERVICE_ID))

    def test_unit_exists_detects_regular_unit_file(self):
        self.unit_dir.mkdir(parents=True)
        unit = self.unit_dir / f"winux-{SERVICE_ID}.service"
        unit.write_text("[Service]\\n", encoding="utf-8")

        self.assertTrue(self.backend.unit_exists(SERVICE_ID))

    def test_unit_exists_returns_false_when_unit_file_is_missing(self):
        self.unit_dir.mkdir(parents=True)

        self.assertFalse(self.backend.unit_exists(SERVICE_ID))

    def test_unit_exists_rejects_symbolic_link_unit(self):
        self.unit_dir.mkdir(parents=True)
        target = Path(self.temp_dir.name) / "target-unit"
        target.write_text("[Service]\\n", encoding="utf-8")
        unit = self.unit_dir / f"winux-{SERVICE_ID}.service"
        unit.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.backend.unit_exists(SERVICE_ID)

    def test_unit_exists_rejects_symlinked_parent_directory(self):
        target = Path(self.temp_dir.name) / "real-systemd"
        target.mkdir()
        link = Path(self.temp_dir.name) / "linked-systemd"
        link.symlink_to(target, target_is_directory=True)

        backend = SystemdUserBackend(
            systemctl="/usr/bin/systemctl",
            unit_dir=link / "user",
        )

        with self.assertRaisesRegex(ValueError, "symbolic links"):
            backend.unit_exists(SERVICE_ID)

    @patch("winux.platform.service_backend.subprocess.run")
    def test_reload_calls_systemd_daemon_reload(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        self.backend.reload()

        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/systemctl", "--user", "daemon-reload"],
        )

    @patch("winux.platform.service_backend.subprocess.run")
    def test_reload_propagates_systemd_failure(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="daemon reload failed",
        )

        with self.assertRaisesRegex(RuntimeError, "daemon reload failed"):
            self.backend.reload()

    @patch("winux.platform.service_backend.subprocess.run")
    def test_status_reports_manager_failure_as_unknown_not_missing(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Failed to connect to user bus",
        )
        result = self.backend.status(SERVICE_ID)
        self.assertEqual(result["load_state"], "unknown")
        self.assertEqual(result["error"], "Failed to connect to user bus")

    @patch(
        "winux.platform.service_backend.subprocess.run",
        side_effect=subprocess.TimeoutExpired("systemctl", 30),
    )
    def test_status_reports_timeout_as_unknown(self, _run):
        result = self.backend.status(SERVICE_ID)
        self.assertEqual(result["load_state"], "unknown")
        self.assertIn("timed out", result["error"])

    @patch(
        "winux.platform.service_backend.subprocess.run",
        side_effect=FileNotFoundError("systemctl disappeared"),
    )
    def test_status_reports_missing_systemctl_as_unknown(self, _run):
        result = self.backend.status(SERVICE_ID)
        self.assertEqual(result["load_state"], "unknown")
        self.assertIn("Unable to execute systemctl", result["error"])

    @patch(
        "winux.platform.service_backend.subprocess.run",
        side_effect=subprocess.TimeoutExpired("systemctl", 30),
    )
    def test_command_timeout_has_actionable_error(self, _run):
        with self.assertRaisesRegex(RuntimeError, "timed out: start"):
            self.backend.start(SERVICE_ID)

    @patch(
        "winux.platform.service_backend.subprocess.run",
        side_effect=FileNotFoundError("systemctl missing"),
    )
    def test_command_launch_failure_has_actionable_error(self, _run):
        with self.assertRaisesRegex(RuntimeError, "Unable to execute systemctl"):
            self.backend.start(SERVICE_ID)

    def test_remove_rejects_symbolic_link(self):
        self.unit_dir.mkdir(parents=True)
        target = Path(self.temp_dir.name) / "target"
        target.write_text("not a unit", encoding="utf-8")

        unit = self.unit_dir / f"winux-{SERVICE_ID}.service"
        unit.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "symbolic-link"):
            self.backend.remove(SERVICE_ID)


if __name__ == "__main__":
    unittest.main()
