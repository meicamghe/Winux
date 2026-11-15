import json
import logging
import re
import shutil
from pathlib import Path

from winux.runtime.manager import RuntimeManager


class PrefixManager:
    # Winux uses 64-bit WoW64 prefixes for both x86 and x64 applications.
    ARCHITECTURES = {
        "x86": "win64",
        "x64": "win64",
        "win64": "win64",
    }

    LEGACY_ARCHITECTURE = "win64"

    def __init__(self, runtime_manager=None):
        self.runtime_manager = (
            runtime_manager if runtime_manager is not None else RuntimeManager()
        )
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

        metadata = self._read_metadata(path)
        runtime_name = metadata.get(
            "runtime", self.runtime_manager.get_default_name()
        )

        if not isinstance(runtime_name, str) or not runtime_name.strip():
            raise ValueError("Invalid prefix runtime metadata")

        runtime = self.runtime_manager.get(runtime_name)
        if not runtime.validate_prefix(path):
            raise ValueError("Invalid Winux prefix")

        if path.resolve().parent != self.base_dir:
            raise ValueError("Prefix path is outside Winux directory")

        return path

    def _read_metadata(self, path):
        metadata = path / ".winux-prefix.json"

        # Check symlinks before exists(): a dangling symlink reports exists=False.
        if metadata.is_symlink():
            raise ValueError("Invalid prefix metadata")
        if not metadata.exists():
            return {
                "name": path.name,
                "architecture": self.LEGACY_ARCHITECTURE,
                "runtime": self.runtime_manager.get_default_name(),
                "format_version": 1,
            }

        if not metadata.is_file():
            raise ValueError("Invalid prefix metadata")

        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("Unable to read prefix metadata") from error

        if not isinstance(data, dict):
            raise ValueError("Invalid prefix metadata")

        # Older metadata may omit name/architecture; the historical Winux
        # prefix format used win64 WoW64 prefixes by default.
        if "name" in data and data["name"] != path.name:
            raise ValueError("Prefix metadata name does not match its directory")

        data.setdefault("name", path.name)
        data.setdefault("architecture", self.LEGACY_ARCHITECTURE)
        if data["architecture"] != "win64":
            raise ValueError("Invalid prefix architecture metadata")

        format_version = data.get("format_version", 1)
        if (
            isinstance(format_version, bool)
            or not isinstance(format_version, int)
            or format_version != 1
        ):
            raise ValueError("Unsupported prefix metadata format version")

        runtime_name = data.get("runtime", self.runtime_manager.get_default_name())
        if not isinstance(runtime_name, str) or not runtime_name.strip():
            raise ValueError("Invalid prefix runtime metadata")

        return data

    def get_runtime(self, name):
        path = self._get_valid_path(name)
        metadata = self._read_metadata(path)
        runtime_name = metadata.get(
            "runtime", self.runtime_manager.get_default_name()
        )

        if not isinstance(runtime_name, str) or not runtime_name.strip():
            raise ValueError("Invalid prefix runtime metadata")

        return self.runtime_manager.get(runtime_name)

    def get_architecture(self, name):
        path = self._get_valid_path(name)
        data = self._read_metadata(path)
        architecture = data.get("architecture")

        if architecture != "win64":
            raise ValueError("Invalid prefix architecture metadata")

        return architecture

    def create(self, name, architecture="win64"):
        self.validate_name(name)
        architecture = self.normalize_architecture(architecture)

        runtime = self.runtime_manager.get()

        if not runtime.is_available():
            raise RuntimeError(
                f"Runtime is not available: {self.runtime_manager.get_default_name()}"
            )

        path = self.base_dir / name

        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Prefix already exists: {name}")

        path.mkdir(mode=0o700)

        try:
            result = runtime.create_prefix(path, architecture)

            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip() or "Runtime prefix initialization failed"
                )

            if not runtime.validate_prefix(path):
                raise RuntimeError("Runtime created an invalid prefix")

            metadata = {
                "name": name,
                "architecture": architecture,
                "runtime": runtime.name,
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
        prefixes = []

        for path in self.base_dir.iterdir():
            if path.is_symlink() or not path.is_dir():
                continue

            try:
                metadata = self._read_metadata(path)
                runtime_name = metadata.get(
                    "runtime", self.runtime_manager.get_default_name()
                )

                if not isinstance(runtime_name, str) or not runtime_name.strip():
                    raise ValueError("Invalid prefix runtime metadata")

                runtime = self.runtime_manager.get(runtime_name)

                if runtime.validate_prefix(path):
                    prefixes.append(path.name)
            except Exception:
                self.logger.exception(
                    "Prefix validation failed: %s", path.name
                )

        return sorted(prefixes)

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
