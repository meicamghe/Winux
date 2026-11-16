import csv
import json
import math
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath

from winux.core.prefix import PrefixManager
from winux.runtime.manager import RuntimeManager


class ApplicationManager:
    UNINSTALL_KEYS = (
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    )

    FIELDS = {
        "DisplayName",
        "DisplayVersion",
        "Publisher",
        "InstallLocation",
        "DisplayIcon",
        "UninstallString",
        "QuietUninstallString",
        "URLInfoAbout",
    }

    def __init__(self, runtime_manager=None):
        self.runtime_manager = (
            runtime_manager if runtime_manager is not None else RuntimeManager()
        )
        self.prefix_manager = PrefixManager(
            runtime_manager=self.runtime_manager
        )

    def _query_registry(self, prefix_path, key, runtime=None):
        runtime = runtime if runtime is not None else self.runtime_manager.get()

        if not runtime.is_available():
            raise RuntimeError("Selected runtime is not available")

        result = runtime.query_registry(
            prefix_path,
            key,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0 and not result.stdout.strip():
            return []

        return self._parse_registry(result.stdout)

    def _parse_registry(self, output):
        applications = []
        current = None

        for line in output.splitlines():
            line = line.rstrip()

            if line.startswith("HKEY_"):
                if current and current.get("DisplayName"):
                    applications.append(current)

                current = {
                    "registry_key": line.strip(),
                    "registry_id": line.strip().rsplit("\\", 1)[-1],
                }
                continue

            if current is None:
                continue

            match = re.match(
                r"^\s+(\S+)\s+REG_\w+\s*(.*)$",
                line,
            )

            if not match:
                continue

            name, value = match.groups()

            if name in self.FIELDS:
                current[name] = value.strip()

        if current and current.get("DisplayName"):
            applications.append(current)

        return applications

    def _windows_path_to_linux(self, prefix_path, value):
        if not value:
            return None

        value = value.strip()

        if value.startswith('"'):
            match = re.fullmatch(r'"([^"]+)"(?:,\s*-?\d+)?', value)
            if not match:
                return None
            value = match.group(1)
        else:
            value = re.sub(r",\s*-?\d+$", "", value).strip()

        windows_path = PureWindowsPath(value)

        if (
            windows_path.drive.upper() != "C:"
            or not windows_path.is_absolute()
        ):
            return None

        drive_c = Path(prefix_path) / "drive_c"
        if drive_c.is_symlink() or not drive_c.is_dir():
            return None

        path = drive_c
        for part in windows_path.parts[1:]:
            path = path / part

        try:
            root = drive_c.resolve(strict=True)
            resolved = path.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None

        return resolved

    def list(self, prefix_name):
        prefix_path = self.prefix_manager.get_path(prefix_name)
        runtime = self.prefix_manager.get_runtime(prefix_name)

        found = {}

        for key in self.UNINSTALL_KEYS:
            records = self._query_registry(prefix_path, key, runtime=runtime)

            for record in records:
                name = record.get("DisplayName")
                if not name:
                    continue

                identity = (
                    record.get("registry_key", "").lower()
                )

                found[identity] = record

        applications = []

        for record in found.values():
            icon_path = self._windows_path_to_linux(
                prefix_path,
                record.get("DisplayIcon"),
            )

            install_path = self._windows_path_to_linux(
                prefix_path,
                record.get("InstallLocation"),
            )

            # DisplayIcon may point to an .ico, .dll, or another resource.
            # Never expose those files as launch targets: only an existing
            # Windows executable can be selected from this registry value.
            record["executable_path"] = (
                str(icon_path)
                if (
                    icon_path
                    and icon_path.suffix.casefold() == ".exe"
                    and icon_path.is_file()
                )
                else None
            )

            record["install_path"] = (
                str(install_path) if install_path and install_path.exists()
                else None
            )

            applications.append(record)

        return sorted(
            applications,
            key=lambda item: item.get("DisplayName", "").lower(),
        )

    def search(self, prefix_name, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be empty")

        query = query.strip().casefold()

        applications = self.list(prefix_name)

        return [
            application
            for application in applications
            if any(
                query in str(application.get(field) or "").casefold()
                for field in ("DisplayName", "Publisher", "DisplayVersion")
            )
        ]

    def export(self, prefix_name, output_path, format="json"):
        if format not in ("json", "csv"):
            raise ValueError("Export format must be 'json' or 'csv'")

        output_path = Path(output_path).expanduser()

        if output_path.exists() and output_path.is_dir():
            raise ValueError("Output path must be a file, not a directory")

        applications = self.list(prefix_name)

        fields = [
            "DisplayName",
            "DisplayVersion",
            "Publisher",
            "InstallLocation",
            "install_path",
            "executable_path",
            "registry_id",
            "registry_key",
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
        )

        try:
            os.fchmod(descriptor, 0o600)
            file_handle = os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="" if format == "csv" else None,
            )
            descriptor = -1
            with file_handle as file:
                if format == "json":
                    json.dump(
                        [
                            {field: app.get(field) for field in fields}
                            for app in applications
                        ],
                        file,
                        ensure_ascii=False,
                        indent=2,
                    )
                    file.write("\n")
                else:
                    writer = csv.DictWriter(file, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(
                        {field: app.get(field) for field in fields}
                        for app in applications
                    )
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_name, output_path)
            directory_fd = os.open(
                output_path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

        return {
            "success": True,
            "prefix": prefix_name,
            "format": format,
            "path": str(output_path),
            "count": len(applications),
        }

    def info(self, prefix_name, application_id):
        applications = self.list(prefix_name)

        for application in applications:
            if application["registry_id"].lower() == application_id.lower():
                return application

        raise LookupError(
            f"Application not found in prefix '{prefix_name}': {application_id}"
        )

    def uninstall(self, prefix_name, application_id, timeout=300):
        try:
            finite_timeout = math.isfinite(timeout)
        except (OverflowError, TypeError):
            finite_timeout = False

        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not finite_timeout
            or timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number")

        application = self.info(prefix_name, application_id)

        command = (
            application.get("QuietUninstallString")
            or application.get("UninstallString")
        )

        if not command:
            raise ValueError(
                f"No uninstall command registered for: "
                f"{application.get('DisplayName', application_id)}"
            )
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Invalid uninstall command")

        import shlex

        try:
            args = shlex.split(command, posix=False)
            args = [
                arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] == '"'
                else arg
                for arg in args
            ]
        except ValueError as exc:
            raise ValueError("Invalid uninstall command") from exc

        if not args:
            raise ValueError("Invalid uninstall command")

        prefix_path = self.prefix_manager.get_path(prefix_name)
        runtime = self.prefix_manager.get_runtime(prefix_name)

        if not runtime.is_available():
            raise RuntimeError(f"Runtime is not available: {runtime.name}")

        result = runtime.uninstall(
            prefix_path,
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Uninstaller exited with code {result.returncode}"
            )

        return {
            "success": True,
            "application": application.get("DisplayName", application_id),
            "prefix": prefix_name,
            "returncode": result.returncode,
        }
