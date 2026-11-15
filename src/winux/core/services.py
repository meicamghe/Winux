import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from winux.core.applications import ApplicationManager
from winux.core.prefix import PrefixManager
from winux.platform.service_backend import SystemdUserBackend


class ServiceManager:
    """Manage background Windows applications as Winux services."""

    def __init__(
        self,
        backend=None,
        state_file=None,
        prefix_manager=None,
        application_manager=None,
    ):
        self.backend = backend or SystemdUserBackend()
        self.state_file = Path(
            state_file
            or Path.home() / ".local/share/winux/services.json"
        )
        self.prefix_manager = prefix_manager or PrefixManager()
        self.application_manager = (
            application_manager or ApplicationManager()
        )

    def _read(self):
        # Check symlinks before exists(): dangling symlinks report exists=False.
        if self.state_file.is_symlink():
            raise ValueError("Service state file must not be a symlink")

        if not self.state_file.exists():
            return []

        try:
            records = json.loads(
                self.state_file.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("Unable to read service definitions") from error

        if not isinstance(records, list):
            raise ValueError("Invalid service definitions")

        required_fields = {
            "id", "name", "prefix", "application_id", "application",
            "runtime", "executable", "restart",
        }
        seen_ids = set()
        seen_names = set()

        for record in records:
            if (
                not isinstance(record, dict)
                or not required_fields.issubset(record)
            ):
                raise ValueError("Invalid service record")

            service_id = record["id"]
            if (
                not isinstance(service_id, str)
                or not SystemdUserBackend.SERVICE_ID_PATTERN.fullmatch(
                    service_id
                )
                or service_id in seen_ids
            ):
                raise ValueError(
                    "Invalid or duplicate service ID in state file"
                )

            for field in (
                "name", "prefix", "application_id", "application",
                "runtime", "executable",
            ):
                value = record[field]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Invalid service field: {field}")

            if (
                not isinstance(record["restart"], str)
                or record["restart"] not in SystemdUserBackend.RESTART_POLICIES
            ):
                raise ValueError(
                    "Invalid service restart policy in state file"
                )

            normalized_name = record["name"].casefold()
            if normalized_name in seen_names:
                raise ValueError("Duplicate service name in state file")

            seen_ids.add(service_id)
            seen_names.add(normalized_name)

        return records

    def _write(self, records):
        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if self.state_file.is_symlink():
            raise ValueError("Service state file must not be a symlink")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".services-",
            suffix=".tmp",
            dir=self.state_file.parent,
        )
        temporary = Path(temporary_name)

        try:
            os.fchmod(descriptor, 0o600)

            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(records, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            temporary.replace(self.state_file)
        finally:
            if temporary.exists():
                temporary.unlink()

    def get_definition(self, service_id):
        """Return a stored service definition without backend status data."""
        if (
            not isinstance(service_id, str)
            or not SystemdUserBackend.SERVICE_ID_PATTERN.fullmatch(service_id)
        ):
            raise KeyError(f"Unknown service: {service_id}")

        for record in self._read():
            if record["id"] == service_id:
                return record.copy()

        raise KeyError(f"Unknown service: {service_id}")

    def _find(self, service_id):
        # Backward-compatible internal alias.
        return self.get_definition(service_id)

    def create(
        self,
        name,
        prefix_name,
        application_id,
        restart="on-failure",
    ):
        if os.geteuid() == 0:
            raise PermissionError(
                "Winux services must be created by a regular user, not root"
            )

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Service name must not be empty")

        name = name.strip()

        if "\n" in name or "\r" in name:
            raise ValueError("Service name must be a single line")

        if (
            not isinstance(restart, str)
            or restart not in SystemdUserBackend.RESTART_POLICIES
        ):
            raise ValueError("Invalid restart policy")

        self.prefix_manager.validate_name(prefix_name)

        prefix_path = self.prefix_manager.get_path(prefix_name)
        runtime = self.prefix_manager.get_runtime(prefix_name)

        if not runtime.is_available():
            raise RuntimeError(
                f"Runtime is not available: {runtime.name}"
            )

        application = self.application_manager.info(
            prefix_name,
            application_id,
        )

        executable_value = application.get("executable_path")
        if not executable_value:
            raise FileNotFoundError(
                "Application executable path was not found"
            )

        drive_c = (prefix_path / "drive_c").resolve(strict=True)
        executable = Path(executable_value).resolve(strict=True)

        if not executable.is_file():
            raise FileNotFoundError(
                f"Application executable not found: {executable}"
            )

        try:
            executable.relative_to(drive_c)
        except ValueError:
            raise ValueError(
                "Application executable is outside the runtime prefix"
            ) from None

        records = self._read()

        if any(record.get("name", "").casefold() == name.casefold()
               for record in records):
            raise FileExistsError(f"Service name already exists: {name}")

        service_id = uuid.uuid4().hex
        application_name = (
            application.get("DisplayName") or application_id
        )

        record = {
            "id": service_id,
            "name": name,
            "prefix": prefix_name,
            "application_id": application_id,
            "application": application_name,
            "runtime": runtime.name,
            "executable": str(executable),
            "restart": restart,
        }

        service_runner = (
            Path(__file__).resolve().parents[1] / "service_runner.py"
        )

        command = [
            sys.executable,
            str(service_runner),
            service_id,
        ]

        self.backend.install(
            service_id,
            command,
            f"Winux service: {name}",
            restart=restart,
        )

        try:
            records.append(record)
            self._write(records)
        except Exception as original_error:
            try:
                self.backend.remove(service_id)
            except Exception as rollback_error:
                raise RuntimeError(
                    "Service creation failed and rollback was incomplete. "
                    f"Original error: {original_error}. "
                    f"Rollback error: {rollback_error}. "
                    f"Service ID: {service_id}"
                ) from original_error
            raise

        return record.copy()

    def list(self):
        records = self._read()
        result = []

        for record in records:
            item = record.copy()
            item["status"] = self.backend.status(record["id"])
            result.append(item)

        return result

    def get(self, service_id):
        record = self._find(service_id)
        result = record.copy()
        result["status"] = self.backend.status(service_id)
        return result

    def start(self, service_id):
        self._find(service_id)
        self.backend.start(service_id)
        return self.get(service_id)

    def stop(self, service_id):
        self._find(service_id)
        self.backend.stop(service_id)
        return self.get(service_id)

    def restart(self, service_id):
        self._find(service_id)
        self.backend.restart(service_id)
        return self.get(service_id)

    def enable(self, service_id):
        self._find(service_id)
        self.backend.enable(service_id)
        return self.get(service_id)

    def disable(self, service_id):
        self._find(service_id)
        self.backend.disable(service_id)
        return self.get(service_id)

    @staticmethod
    def _is_active(status):
        return status.get("active_state") in {
            "active", "activating", "reloading", "deactivating"
        }

    @staticmethod
    def _is_enabled(status):
        return status.get("unit_file_state") in {
            "enabled", "enabled-runtime", "linked", "linked-runtime"
        }

    def _restore_deleted_service(self, record, original_status):
        service_id = record["id"]

        # Inspect the unit file first. systemd may temporarily be unavailable
        # after a failed daemon-reload, but the on-disk unit is still usable.
        if not self.backend.unit_exists(service_id):
            service_runner = (
                Path(__file__).resolve().parents[1] / "service_runner.py"
            )
            command = [
                sys.executable,
                str(service_runner),
                service_id,
            ]
            self.backend.install(
                service_id,
                command,
                f"Winux service: {record['name']}",
                restart=record["restart"],
            )
        else:
            current = self.backend.status(service_id)
            if current.get("load_state") != "loaded":
                self.backend.reload()

        current = self.backend.status(service_id)
        if current.get("load_state") != "loaded":
            raise RuntimeError(
                "Service unit exists but systemd did not load it"
            )

        originally_enabled = self._is_enabled(original_status)
        currently_enabled = self._is_enabled(current)

        if originally_enabled and not currently_enabled:
            self.backend.enable(service_id)
        elif not originally_enabled and currently_enabled:
            self.backend.disable(service_id)

        current = self.backend.status(service_id)
        originally_active = self._is_active(original_status)
        currently_active = self._is_active(current)

        if originally_active and not currently_active:
            self.backend.start(service_id)
        elif not originally_active and currently_active:
            self.backend.stop(service_id)

    def delete(self, service_id):
        records = self._read()
        record = next(
            (item for item in records if item.get("id") == service_id),
            None,
        )

        if record is None:
            raise KeyError(f"Unknown service: {service_id}")

        original_status = self.backend.status(service_id)

        try:
            if self._is_active(original_status):
                self.backend.stop(service_id)

            if self._is_enabled(original_status):
                self.backend.disable(service_id)

            self.backend.remove(service_id)

            remaining = [
                item for item in records
                if item.get("id") != service_id
            ]
            self._write(remaining)

        except Exception as original_error:
            try:
                self._restore_deleted_service(record, original_status)
            except Exception as rollback_error:
                raise RuntimeError(
                    "Service deletion failed and rollback was incomplete. "
                    f"Original error: {original_error}. "
                    f"Rollback error: {rollback_error}. "
                    f"Service ID: {service_id}"
                ) from original_error

            raise

        return record.copy()
