import csv
import json
import math
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath

from winux.core.prefix import PrefixManager
from winux.core.desktop import DesktopManager
from winux.runtime.manager import RuntimeManager


class ApplicationManager:
    UNINSTALL_KEYS = (
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    )

    APP_PATHS_KEYS = (
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths",
        r"HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths",
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

    def _parse_app_paths(self, output, prefix_path):
        """Return only App Paths registrations with safe, existing EXE targets."""
        candidates = []
        current_key = None
        default_value = None

        def add_candidate():
            if not current_key or not default_value:
                return
            executable = self._windows_path_to_linux(
                prefix_path, default_value
            )
            if (
                executable is None
                or executable.suffix.casefold() != ".exe"
                or not executable.is_file()
            ):
                return
            registry_id = current_key.rstrip("\\").rsplit("\\", 1)[-1]
            candidates.append({
                "registry_key": current_key,
                "registry_id": registry_id,
                "DisplayName": Path(registry_id).stem,
                "DisplayIcon": default_value,
                "executable_path": str(executable),
                "executable_status": "ready",
                "install_path": str(executable.parent),
                "discovery_source": "app_paths",
            })

        for line in output.splitlines():
            line = line.rstrip()
            if line.startswith("HKEY_"):
                add_candidate()
                current_key = line.strip()
                default_value = None
                continue
            if current_key is None:
                continue
            match = re.match(
                r"^\s+\(Default\)\s+REG_\w+\s*(.*)$",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                default_value = match.group(1).strip()

        add_candidate()
        return candidates

    def _msi_product_code(self, record):
        """Return an MSI ProductCode only for a registered msiexec command."""
        import shlex

        for field in ("QuietUninstallString", "UninstallString"):
            command = record.get(field)
            if not isinstance(command, str) or not command.strip():
                continue
            try:
                args = shlex.split(command, posix=False)
            except ValueError:
                continue
            if not args:
                continue
            executable = args[0].strip('"')
            if PureWindowsPath(executable).name.casefold() not in (
                "msiexec", "msiexec.exe"
            ):
                continue
            match = re.search(
                r"\\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                r"[0-9a-f]{4}-[0-9a-f]{12}\\}",
                command,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(0).upper()
        return None

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

                identity = record.get("registry_key", "").lower()
                found[identity] = record

        # MSI product registrations can appear in both native and WOW6432Node
        # uninstall views. Collapse only records sharing the same ProductCode;
        # similarly named non-MSI applications remain independent entries.
        grouped = {}
        for record in found.values():
            product_code = self._msi_product_code(record)
            identity = (
                ("msi", product_code) if product_code
                else ("registry", record.get("registry_key", "").casefold())
            )
            if identity not in grouped:
                primary = dict(record)
                primary["registry_ids"] = [record.get("registry_id")]
                primary["registry_keys"] = [record.get("registry_key")]
                primary["uninstall_commands"] = [
                    {
                        "registry_id": record.get("registry_id"),
                        "quiet": record.get("QuietUninstallString"),
                        "normal": record.get("UninstallString"),
                    }
                ]
                grouped[identity] = primary
                continue

            primary = grouped[identity]
            registry_id = record.get("registry_id")
            registry_key = record.get("registry_key")
            if registry_id and registry_id not in primary["registry_ids"]:
                primary["registry_ids"].append(registry_id)
            if registry_key and registry_key not in primary["registry_keys"]:
                primary["registry_keys"].append(registry_key)
            primary["uninstall_commands"].append({
                "registry_id": registry_id,
                "quiet": record.get("QuietUninstallString"),
                "normal": record.get("UninstallString"),
            })
            # Fill metadata missing from the first registry view without
            # overwriting values already selected for the displayed product.
            for field in self.FIELDS:
                if not primary.get(field) and record.get(field):
                    primary[field] = record[field]

        applications = list(grouped.values())

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
            executable_is_valid = bool(
                icon_path
                and icon_path.suffix.casefold() == ".exe"
                and icon_path.is_file()
            )
            record["executable_path"] = (
                str(icon_path) if executable_is_valid else None
            )
            if executable_is_valid:
                record["executable_status"] = "ready"
            elif not record.get("DisplayIcon"):
                record["executable_status"] = "not_registered"
            elif icon_path is None:
                record["executable_status"] = "invalid_registry_path"
            elif icon_path.suffix.casefold() != ".exe":
                record["executable_status"] = "resource_not_executable"
            else:
                record["executable_status"] = "executable_missing"

            record["install_path"] = (
                str(install_path) if install_path and install_path.exists()
                else None
            )

            applications.append(record)

        known_executables = {
            str(Path(item["executable_path"]).resolve())
            for item in applications
            if item.get("executable_path")
        }
        for key in self.APP_PATHS_KEYS:
            result = runtime.query_registry(
                prefix_path,
                key,
                capture_output=True,
                text=True,
                timeout=60,
            )
            # App Paths stores its executable in the default registry value,
            # so it needs a parser distinct from uninstall inventory records.
            raw_output = result.stdout if result.returncode == 0 else ""
            for candidate in self._parse_app_paths(raw_output, prefix_path):
                executable = candidate["executable_path"]
                if executable in known_executables:
                    continue
                known_executables.add(executable)
                applications.append(candidate)

        # Windows Start Menu shortcuts provide another explicit launch-target
        # source. Revalidate containment here before exposing candidates.
        try:
            shortcut_result = DesktopManager.discover_start_menu_shortcuts(
                prefix_path
            )
        except (OSError, ValueError):
            shortcut_result = {"shortcuts": []}

        drive_c = (Path(prefix_path) / "drive_c").resolve(strict=True)
        for shortcut in shortcut_result.get("shortcuts", []):
            try:
                executable = Path(shortcut["executable_path"]).resolve(strict=True)
                executable.relative_to(drive_c)
            except (KeyError, OSError, ValueError):
                continue
            if (
                executable.suffix.casefold() != ".exe"
                or not executable.is_file()
            ):
                continue
            executable_key = str(executable)
            if executable_key in known_executables:
                continue
            try:
                shortcut_path = Path(shortcut["shortcut"]).resolve(strict=True)
                if shortcut_path.suffix.casefold() != ".lnk" or not shortcut_path.is_file():
                    continue
                relative_shortcut = shortcut_path.relative_to(
                    drive_c
                ).as_posix()
            except (OSError, ValueError):
                # A shortcut can disappear between discovery and inventory.
                continue
            registry_id = f"start-menu:{relative_shortcut}"
            known_executables.add(executable_key)
            applications.append({
                "registry_key": f"StartMenu\\{relative_shortcut}",
                "registry_id": registry_id,
                "DisplayName": shortcut.get("name") or executable.stem,
                "DisplayVersion": None,
                "Publisher": None,
                "InstallLocation": str(executable.parent),
                "install_path": str(executable.parent),
                "DisplayIcon": str(executable),
                "executable_path": str(executable),
                "executable_status": "ready",
                "discovery_source": "start_menu",
            })

        return sorted(
            applications,
            key=lambda item: item.get("DisplayName", "").lower(),
        )

    def audit(self, prefix_name):
        """Summarize application inventory and identify missing executable targets."""
        applications = self.list(prefix_name)
        stale = [
            application
            for application in applications
            if application.get("executable_status") == "executable_missing"
        ]
        counts = {}
        for application in applications:
            status = application.get("executable_status", "unknown")
            counts[status] = counts.get(status, 0) + 1

        return {
            "prefix": prefix_name,
            "total": len(applications),
            "stale_count": len(stale),
            "status_counts": counts,
            "stale": stale,
        }

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
            "executable_status",
            "registry_id",
            "registry_key",
            "discovery_source",
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
            registry_ids = application.get(
                "registry_ids", [application.get("registry_id")]
            )
            if any(
                isinstance(registry_id, str)
                and registry_id.casefold() == application_id.casefold()
                for registry_id in registry_ids
            ):
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

        uninstall_commands = application.get("uninstall_commands", [])
        command = next(
            (
                entry.get("quiet")
                for entry in uninstall_commands
                if entry.get("quiet")
            ),
            None,
        ) or next(
            (
                entry.get("normal")
                for entry in uninstall_commands
                if entry.get("normal")
            ),
            None,
        ) or (
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

        # Windows Installer registry entries may incorrectly retain /I
        # (install/repair) in UninstallString. Convert it to /X only when
        # the executable is msiexec and the following target is a product
        # code, never for arbitrary executables or MSI package paths.
        if PureWindowsPath(args[0]).name.casefold() in ("msiexec", "msiexec.exe"):
            product_code = re.compile(
                r"\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                r"[0-9a-f]{4}-[0-9a-f]{12}\}$",
                re.IGNORECASE,
            )
            for index, argument in enumerate(args[1:], start=1):
                if argument.casefold().startswith("/i") and product_code.fullmatch(
                    argument[2:]
                ):
                    args[index] = "/X" + argument[2:]
                    break
                if (
                    argument.casefold() == "/i"
                    and index + 1 < len(args)
                    and product_code.fullmatch(args[index + 1])
                ):
                    args[index] = "/X"
                    break

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
