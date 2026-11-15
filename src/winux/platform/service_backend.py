import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from winux.core.service_contracts import (
    SERVICE_ID_PATTERN as _SERVICE_ID_PATTERN,
    SERVICE_RESTART_POLICIES,
)


class SystemdUserBackend:
    """Manage Winux services through the user's systemd instance."""

    SERVICE_ID_PATTERN = _SERVICE_ID_PATTERN
    RESTART_POLICIES = SERVICE_RESTART_POLICIES

    def __init__(self, systemctl=None, unit_dir=None):
        self.systemctl = systemctl or shutil.which("systemctl")
        self.unit_dir = Path(
            unit_dir or Path.home() / ".config/systemd/user"
        )

        if not self.systemctl:
            raise RuntimeError("systemctl executable not found")

    @classmethod
    def _unit_name(cls, service_id):
        if (
            not isinstance(service_id, str)
            or not cls.SERVICE_ID_PATTERN.fullmatch(service_id)
        ):
            raise ValueError("Invalid service ID")

        return f"winux-{service_id}.service"

    @staticmethod
    def _quote(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Command arguments must be non-empty strings")

        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Command arguments must not contain control characters")

        value = value.replace("%", "%%")
        value = value.replace("$", "$$")
        value = value.replace("\\", "\\\\")
        value = value.replace('"', '\\"')
        return f'"{value}"'

    @staticmethod
    def _description(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Service description must not be empty")

        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Service description contains control characters")

        return value.strip().replace("\\", "\\\\").replace("%", "%%")

    def _run(self, arguments, timeout=30):
        try:
            result = subprocess.run(
                [self.systemctl, "--user", *arguments],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"systemctl command timed out: {arguments[0]}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                f"Unable to execute systemctl: {error}"
            ) from error

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                message or f"systemctl command failed: {arguments[0]}"
            )

        return result

    @staticmethod
    def _reject_symlink_components(path):
        """Reject symlinks in every existing component of a path."""
        path = Path(os.path.abspath(path))

        for component in reversed((path, *path.parents)):
            if component.is_symlink():
                raise ValueError(
                    f"Path must not contain symbolic links: {component}"
                )

    def _ensure_unit_directory(self):
        self._reject_symlink_components(self.unit_dir)

        self.unit_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        self._reject_symlink_components(self.unit_dir)

        if not self.unit_dir.is_dir():
            raise ValueError("Systemd unit directory must be a real directory")

        # Do not chmod the shared standard systemd user directory.
        # Winux creates its own unit files with mode 0600.

    def install(
        self,
        service_id,
        command,
        description,
        restart="on-failure",
    ):
        unit_name = self._unit_name(service_id)

        if (
            not isinstance(restart, str)
            or restart not in self.RESTART_POLICIES
        ):
            raise ValueError("Invalid restart policy")

        if (
            not isinstance(command, (list, tuple))
            or not command
            or any(not isinstance(item, str) or not item for item in command)
        ):
            raise ValueError("A non-empty command argument list is required")

        description = self._description(description)
        executable = " ".join(self._quote(item) for item in command)

        content = (
            "[Unit]\n"
            f"Description={description}\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={executable}\n"
            f"Restart={restart}\n"
            "RestartSec=5s\n"
            "KillMode=control-group\n"
            "TimeoutStopSec=15s\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

        self._ensure_unit_directory()
        unit_path = self.unit_dir / unit_name

        if unit_path.is_symlink():
            raise ValueError("Service unit must not be a symbolic link")

        if unit_path.exists():
            raise FileExistsError(f"Service unit already exists: {unit_name}")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{unit_name}.",
            suffix=".tmp",
            dir=self.unit_dir,
        )
        temporary = Path(temporary_name)

        unit_installed = False
        reload_attempted = False

        try:
            try:
                os.fchmod(descriptor, 0o600)

                file_handle = os.fdopen(descriptor, "w", encoding="utf-8")
                descriptor = -1
                with file_handle as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())

                if unit_path.is_symlink() or unit_path.exists():
                    raise FileExistsError(
                        f"Service unit appeared during installation: {unit_name}"
                    )

                temporary.replace(unit_path)
                unit_installed = True

                directory_fd = os.open(self.unit_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)

                reload_attempted = True
                self._run(["daemon-reload"])
            except Exception as original_error:
                if unit_installed:
                    try:
                        unit_path.unlink(missing_ok=True)
                        directory_fd = os.open(self.unit_dir, os.O_RDONLY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                        if reload_attempted:
                            self._run(["daemon-reload"])
                    except Exception as rollback_error:
                        raise RuntimeError(
                            "Systemd unit installation failed and rollback "
                            f"was incomplete. Original error: {original_error}. "
                            f"Rollback error: {rollback_error}. Unit: {unit_name}"
                        ) from original_error
                raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()

        return str(unit_path)

    def start(self, service_id):
        return self._run(["start", self._unit_name(service_id)])

    def stop(self, service_id):
        return self._run(["stop", self._unit_name(service_id)])

    def restart(self, service_id):
        return self._run(["restart", self._unit_name(service_id)])

    def enable(self, service_id):
        return self._run(["enable", self._unit_name(service_id)])

    def disable(self, service_id):
        return self._run(["disable", self._unit_name(service_id)])

    def unit_exists(self, service_id):
        """Return whether the service has a real unit file on disk."""
        unit_name = self._unit_name(service_id)
        self._reject_symlink_components(self.unit_dir)

        if not self.unit_dir.is_dir():
            return False

        unit_path = self.unit_dir / unit_name

        if unit_path.is_symlink():
            raise ValueError("Service unit must not be a symbolic link")

        if not unit_path.exists():
            return False

        if not unit_path.is_file():
            raise ValueError("Service unit must be a regular file")

        return True

    def reload(self):
        """Ask the user systemd manager to reload unit definitions."""
        return self._run(["daemon-reload"])

    def status(self, service_id):
        unit_name = self._unit_name(service_id)

        try:
            result = subprocess.run(
                [
                    self.systemctl,
                    "--user",
                    "show",
                    unit_name,
                    "--property=LoadState",
                    "--property=ActiveState",
                    "--property=SubState",
                    "--property=UnitFileState",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "unit": unit_name,
                "load_state": "unknown",
                "active_state": "unknown",
                "sub_state": "unknown",
                "unit_file_state": "unknown",
                "error": "systemctl status command timed out",
            }
        except OSError as error:
            return {
                "unit": unit_name,
                "load_state": "unknown",
                "active_state": "unknown",
                "sub_state": "unknown",
                "unit_file_state": "unknown",
                "error": f"Unable to execute systemctl: {error}",
            }

        values = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value

        if result.returncode != 0 and not values:
            message = result.stderr.strip() or result.stdout.strip()
            return {
                "unit": unit_name,
                "load_state": "unknown",
                "active_state": "unknown",
                "sub_state": "unknown",
                "unit_file_state": "unknown",
                "error": message or "systemctl status failed",
            }

        return {
            "unit": unit_name,
            "load_state": values.get("LoadState", "unknown"),
            "active_state": values.get("ActiveState", "unknown"),
            "sub_state": values.get("SubState", "unknown"),
            "unit_file_state": values.get("UnitFileState", "unknown"),
        }

    def remove(self, service_id):
        unit_name = self._unit_name(service_id)

        self._reject_symlink_components(self.unit_dir)

        if not self.unit_dir.is_dir():
            raise ValueError("Systemd unit directory is not available")

        unit_path = self.unit_dir / unit_name

        if unit_path.is_symlink():
            raise ValueError("Refusing to remove a symbolic-link unit")

        if unit_path.exists():
            if not unit_path.is_file():
                raise ValueError("Refusing to remove a non-file service unit")
            unit_path.unlink()

        self._run(["daemon-reload"])
        return True
