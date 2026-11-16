import configparser
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from winux.core.shell_link import resolve_shell_link_target


class DesktopManager:
    def __init__(self):
        self.applications_dir = (
            Path.home() / ".local/share/applications/winux/Programs"
        )
        self.desktop_dir = self._get_desktop_dir()

    def _get_desktop_dir(self):
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True,
                text=True,
                check=True,
            )
            path = Path(result.stdout.strip()).expanduser()
            if path.is_dir():
                return path
        except (OSError, subprocess.SubprocessError):
            pass

        fallback = Path.home() / "Desktop"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    @staticmethod
    def _launcher_prefix(content):
        """Read the exact WINEPREFIX from a desktop launcher's Exec command."""
        parser = configparser.ConfigParser(
            interpolation=None,
            strict=False,
        )
        try:
            parser.read_string(content)
            command = parser.get("Desktop Entry", "Exec", fallback="")
        except (configparser.Error, ValueError):
            return None

        try:
            arguments = shlex.split(command, posix=True)
        except ValueError:
            return None

        for argument in arguments:
            candidate = argument.strip('"')
            if candidate.startswith("WINEPREFIX="):
                value = candidate.partition("=")[2]
                return str(Path(value).expanduser().absolute()) if value else None
        return None

    def discover_prefix_launchers(self, prefix_path):
        """Find Wine desktop launchers whose declared prefix matches exactly."""
        prefix = Path(prefix_path).expanduser().resolve()
        discovered = []
        errors = []

        if not self.applications_dir.is_dir():
            return {"launchers": discovered, "errors": errors}

        for entry in self.applications_dir.rglob("*.desktop"):
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
                content = entry.read_text(encoding="utf-8")
                declared_prefix = self._launcher_prefix(content)
                if declared_prefix is None:
                    continue
                try:
                    resolved_prefix = Path(declared_prefix).resolve(strict=True)
                except OSError:
                    continue
                if resolved_prefix != prefix:
                    continue
                discovered.append({
                    "name": entry.stem,
                    "desktop_file": str(entry),
                    "prefix": str(resolved_prefix),
                })
            except (OSError, UnicodeError) as error:
                errors.append(f"{entry.name}: {error}")

        return {"launchers": discovered, "errors": errors}

    @staticmethod
    def discover_start_menu_shortcuts(prefix_path, start_menu_roots=None):
        """Discover only .lnk files resolving to existing EXEs in this prefix."""
        prefix = Path(prefix_path).expanduser().resolve()
        drive_c = prefix / "drive_c"
        if drive_c.is_symlink() or not drive_c.is_dir():
            return {"shortcuts": [], "errors": ["Invalid prefix drive_c"]}

        if start_menu_roots is None:
            roots = [
                drive_c / "ProgramData/Microsoft/Windows/Start Menu/Programs",
            ]
            users = drive_c / "users"
            if users.is_dir() and not users.is_symlink():
                roots.extend(
                    user / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs"
                    for user in users.iterdir()
                    if user.is_dir() and not user.is_symlink()
                )
        else:
            roots = [Path(root) for root in start_menu_roots]

        shortcuts = []
        errors = []
        for root in roots:
            if root.is_symlink() or not root.is_dir():
                continue
            for entry in root.rglob("*.lnk"):
                try:
                    if entry.is_symlink() or not entry.is_file():
                        continue
                    target = resolve_shell_link_target(entry.read_bytes(), prefix)
                    if target is None:
                        continue
                    shortcuts.append({
                        "name": entry.stem,
                        "shortcut": str(entry),
                        "executable_path": str(target),
                        "prefix": str(prefix),
                        "discovery_source": "start_menu",
                    })
                except (OSError, UnicodeError) as error:
                    errors.append(f"{entry.name}: {error}")

        shortcuts.sort(key=lambda item: item["name"].casefold())
        return {"shortcuts": shortcuts, "errors": errors}

    def integrate_prefix(self, prefix_path):
        prefix_path = str(Path(prefix_path).resolve())
        integrated = []
        errors = []

        if not self.applications_dir.is_dir():
            return {
                "integrated": integrated,
                "errors": ["Runtime applications directory not found"],
            }

        for entry in self.applications_dir.rglob("*.desktop"):
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
                content = entry.read_text(encoding="utf-8")
                declared_prefix = self._launcher_prefix(content)
                if declared_prefix is None:
                    continue
                try:
                    resolved_prefix = Path(declared_prefix).resolve(strict=True)
                except OSError:
                    continue
                if str(resolved_prefix) != prefix_path:
                    continue

                destination = self.desktop_dir / entry.name

                if destination.exists() or destination.is_symlink():
                    if destination.is_symlink() or not destination.is_file():
                        errors.append(
                            f"{entry.name}: destination exists and is not a regular file"
                        )
                        continue
                    if destination.read_text(encoding="utf-8") != content:
                        errors.append(
                            f"{entry.name}: destination already exists; refusing to overwrite"
                        )
                        continue
                elif destination.resolve() != entry.resolve():
                    shutil.copy2(entry, destination)

                destination.chmod(
                    destination.stat().st_mode | 0o111
                )

                subprocess.run(
                    ["gio", "set", str(destination),
                     "metadata::trusted", "true"],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                integrated.append(entry.name)

            except (OSError, subprocess.SubprocessError) as error:
                errors.append(f"{entry.name}: {error}")

        try:
            subprocess.run(
                ["update-desktop-database",
                 str(Path.home() / ".local/share/applications")],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            errors.append(f"Desktop database update: {error}")

        return {
            "integrated": integrated,
            "errors": errors,
        }
