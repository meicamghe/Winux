import os
import re
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

from winux.core.prefix import PrefixManager


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

    def __init__(self):
        self.prefix_manager = PrefixManager()

    def _query_registry(self, prefix_path, key):
        wine = shutil.which("wine")
        if not wine:
            raise RuntimeError("Wine executable not found")

        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)

        result = subprocess.run(
            [wine, "reg", "query", key, "/s"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
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

        if windows_path.drive.upper() != "C:":
            return None

        path = prefix_path / "drive_c"

        for part in windows_path.parts[1:]:
            path = path / part

        return path

    def list(self, prefix_name):
        prefix_path = self.prefix_manager.get_path(prefix_name)

        found = {}

        for key in self.UNINSTALL_KEYS:
            records = self._query_registry(prefix_path, key)

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

            record["executable_path"] = (
                str(icon_path) if icon_path and icon_path.is_file()
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

    def info(self, prefix_name, application_id):
        applications = self.list(prefix_name)

        for application in applications:
            if application["registry_id"].lower() == application_id.lower():
                return application

        raise LookupError(
            f"Application not found in prefix '{prefix_name}': {application_id}"
        )
