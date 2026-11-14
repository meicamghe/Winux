import os
import shutil
import subprocess
from pathlib import Path

from winux.runtime.base import Runtime


class WineRuntime(Runtime):
    """Wine implementation of the Winux runtime interface."""

    name = "wine"

    def _find(self, executable):
        path = shutil.which(executable)
        if not path:
            raise RuntimeError(f"{executable} executable not found")
        return path

    def _env(self, prefix_path):
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        return env

    def is_available(self):
        return shutil.which("wine") is not None

    def version(self):
        wine = self._find("wine")
        result = subprocess.run(
            [wine, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "Unable to determine Wine version"
            )
        return result.stdout.strip()

    def validate_prefix(self, prefix_path: Path) -> bool:
        prefix_path = Path(prefix_path)
        registry = prefix_path / "system.reg"
        return (
            prefix_path.is_dir()
            and not prefix_path.is_symlink()
            and registry.is_file()
            and not registry.is_symlink()
        )

    def create_prefix(self, prefix_path: Path, architecture: str):
        wineboot = self._find("wineboot")
        env = self._env(prefix_path)
        env["WINEARCH"] = architecture

        return subprocess.run(
            [wineboot, "--init"],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def run(self, prefix_path: Path, executable: Path, args=None, **kwargs):
        wine = self._find("wine")
        command = [wine, str(executable), *(args or [])]

        return subprocess.Popen(
            command,
            env=self._env(prefix_path),
            **kwargs,
        )

    def install(self, prefix_path: Path, installer: Path, **kwargs):
        extension = installer.suffix.lower()

        if extension == ".exe":
            command = [self._find("wine"), str(installer)]
        elif extension == ".msi":
            command = [self._find("msiexec"), "/i", str(installer)]
        else:
            raise ValueError("Unsupported installer format")

        return subprocess.run(
            command,
            env=self._env(prefix_path),
            check=False,
            **kwargs,
        )

    def query_registry(self, prefix_path: Path, key: str, **kwargs):
        wine = self._find("wine")
        return subprocess.run(
            [wine, "reg", "query", key, "/s"],
            env=self._env(prefix_path),
            check=False,
            **kwargs,
        )

    def uninstall(self, prefix_path: Path, command, **kwargs):
        wine = self._find("wine")
        return subprocess.run(
            [wine, *command],
            env=self._env(prefix_path),
            check=False,
            **kwargs,
        )
