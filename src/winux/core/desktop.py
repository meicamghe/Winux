import os
import shutil
import subprocess
from pathlib import Path


class DesktopManager:
    def __init__(self):
        self.applications_dir = (
            Path.home() / ".local/share/applications/wine/Programs"
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

    def integrate_prefix(self, prefix_path):
        prefix_path = str(Path(prefix_path).resolve())
        integrated = []
        errors = []

        if not self.applications_dir.is_dir():
            return {
                "integrated": integrated,
                "errors": ["Wine applications directory not found"],
            }

        for entry in self.applications_dir.rglob("*.desktop"):
            try:
                content = entry.read_text(encoding="utf-8")

                if prefix_path not in content:
                    continue

                destination = self.desktop_dir / entry.name

                if destination.resolve() != entry.resolve():
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
