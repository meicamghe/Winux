import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path


class PrefixManager:
    # Winux uses 64-bit WoW64 prefixes for both x86 and x64 applications.
    ARCHITECTURES = {
        "x86": "win64",
        "x64": "win64",
        "win64": "win64",
    }

    LEGACY_ARCHITECTURE = "win64"

    def __init__(self):
        self.base_dir = Path.home() / ".local/share/winux/prefixes"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir = self.base_dir.resolve()

        log_dir = Path.home() / ".local/share/winux/logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("winux.prefix")
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            handler = logging.FileHandler(log_dir / "prefix-manager.log")
            self.logger.addHandler(handler)

    def validate_name(self, name):
        if not isinstance(name, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}", name
        ):
            raise ValueError("Invalid prefix name")

    def normalize_architecture(self, architecture):
        if architecture not in self.ARCHITECTURES:
            raise ValueError(
                "Architecture must be x86, x64 or win64; "
                "Winux creates only 64-bit WoW64 prefixes"
            )
        return self.ARCHITECTURES[architecture]

    def _get_valid_path(self, name):
        self.validate_name(name)
        path = self.base_dir / name

        if path.is_symlink() or not path.is_dir():
            raise FileNotFoundError(name)

        registry = path / "system.reg"

        if registry.is_symlink() or not registry.is_file():
            raise ValueError("Invalid Winux prefix")

        if path.resolve().parent != self.base_dir:
            raise ValueError("Prefix path is outside Winux directory")

        return path

    def get_architecture(self, name):
        path = self._get_valid_path(name)
        metadata = path / ".winux-prefix.json"

        # Prefixes created by Winux Alpha 0.5 were all win64.
        if not metadata.exists():
            return self.LEGACY_ARCHITECTURE

        if metadata.is_symlink() or not metadata.is_file():
            raise ValueError("Invalid prefix metadata")

        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
            architecture = data["architecture"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError("Unable to read prefix architecture") from error

        if architecture != "win64":
            raise ValueError("Invalid prefix architecture metadata")

        return architecture

    def create(self, name, architecture="win64"):
        self.validate_name(name)
        architecture = self.normalize_architecture(architecture)

        wineboot = shutil.which("wineboot")
        if not wineboot:
            raise RuntimeError("wineboot not found")

        path = self.base_dir / name

        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Prefix already exists: {name}")

        path.mkdir(mode=0o700)

        env = os.environ.copy()
        env["WINEPREFIX"] = str(path)
        env["WINEARCH"] = architecture

        try:
            result = subprocess.run(
                [wineboot, "--init"],
                env=env,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip() or "Wine initialization failed"
                )

            if not (path / "system.reg").is_file():
                raise RuntimeError("Invalid Wine prefix")

            metadata = {
                "name": name,
                "architecture": architecture,
                "format_version": 1
            }

            metadata_file = path / ".winux-prefix.json"
            metadata_file.write_text(
                json.dumps(metadata, indent=2),
                encoding="utf-8"
            )
            metadata_file.chmod(0o600)

            self.logger.info(
                "Created prefix: %s (%s)", name, architecture
            )
            return path

        except Exception:
            self.logger.exception("Prefix creation failed: %s", name)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            raise

    def list(self):
        return sorted(
            p.name for p in self.base_dir.iterdir()
            if not p.is_symlink()
            and p.is_dir()
            and (p / "system.reg").is_file()
            and not (p / "system.reg").is_symlink()
        )

    def get_path(self, name):
        return self._get_valid_path(name)

    def delete(self, name, confirm=False):
        path = self._get_valid_path(name)

        if confirm is not True:
            raise PermissionError(
                "Deletion requires explicit confirmation"
            )

        shutil.rmtree(path)
        self.logger.info("Deleted prefix: %s", name)
        return True
