import configparser
import os
import shlex
import shutil
import subprocess
from pathlib import Path


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
            arguments = shlex.split(command, posix=False)
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
