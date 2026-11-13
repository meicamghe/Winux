import fcntl
import os
import shutil
import subprocess
import tempfile
from pathlib import PurePosixPath
import uuid
from datetime import datetime, timezone
from pathlib import Path

from winux.core.prefix import PrefixManager


class Installer:
    def __init__(self):
        self.prefix_manager = PrefixManager()

        self.data_dir = Path.home() / ".local/share/winux"
        self.log_dir = self.data_dir / "logs" / "installations"
        self.lock_dir = self.data_dir / "locks"

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def _get_msi_architecture(self, source):
        msiinfo = shutil.which("msiinfo")

        if not msiinfo:
            raise RuntimeError("msiinfo is required to inspect MSI architecture")

        try:
            result = subprocess.run(
                [msiinfo, "suminfo", str(source)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("MSI inspection timed out") from error

        if result.returncode != 0:
            raise ValueError(
                result.stderr.strip() or "Unable to read MSI summary information"
            )

        for line in result.stdout.splitlines():
            if "Template" in line:
                value = line.split(":", 1)[-1].strip()
                architecture = value.split(";", 1)[0].strip().lower()

                if architecture in ("intel", "x86"):
                    return "x86"

                if architecture == "x64":
                    return "x64"

                raise ValueError(
                    f"Unsupported MSI architecture: {architecture or 'unknown'}"
                )

        raise ValueError("MSI Template Summary is missing")

    def _get_exe_architecture(self, source):
        size = source.stat().st_size

        with source.open("rb") as file:
            header = file.read(64)

            if header[:2] != b"MZ":
                raise ValueError("Invalid EXE signature")

            pe_offset = int.from_bytes(header[60:64], "little")

            if pe_offset < 64 or pe_offset + 26 > size:
                raise ValueError("Invalid PE header offset")

            file.seek(pe_offset)
            pe_header = file.read(26)

            if len(pe_header) != 26 or pe_header[:4] != b"PE\x00\x00":
                raise ValueError("Invalid Windows PE executable")

            machine = int.from_bytes(pe_header[4:6], "little")
            optional_magic = int.from_bytes(pe_header[24:26], "little")

            if machine == 0x14C and optional_magic == 0x10B:
                return "x86"

            if machine == 0x8664 and optional_magic == 0x20B:
                return "x64"

            raise ValueError(
                f"Unsupported EXE architecture: machine=0x{machine:04X}, "
                f"optional_magic=0x{optional_magic:04X}"
            )

    def _inspect_nsis_application_architecture(self, source):
        seven_zip = shutil.which("7z")

        if not seven_zip:
            raise RuntimeError("7-Zip is required to inspect NSIS installers")

        try:
            listing = subprocess.run(
                [seven_zip, "l", "-slt", str(source)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("NSIS inspection timed out") from error

        if listing.returncode != 0:
            raise ValueError(
                listing.stderr.strip() or "Unable to inspect installer archive"
            )

        if not any(line.startswith(("SubType = Nsis", "Type = Nsis")) for line in listing.stdout.splitlines()):
            raise ValueError("Installer is not a recognized NSIS package")

        archive_path = str(source.resolve())
        entries = []

        for line in listing.stdout.splitlines():
            if not line.startswith("Path = "):
                continue

            entry = line[7:].strip()

            if not entry or entry == archive_path:
                continue

            normalized = entry.replace("\\", "/")
            candidate = PurePosixPath(normalized)

            if candidate.suffix.lower() != ".exe":
                continue

            parts = [part.lower() for part in candidate.parts]

            excluded = {
                "$pluginsdir", "updater", "contextmenu",
                "uninstaller", "uninstall"
            }

            if any(part in excluded for part in parts[:-1]):
                continue

            entries.append(normalized)

        root_entries = [
            entry for entry in entries
            if len(PurePosixPath(entry).parts) == 1
        ]

        candidates = root_entries if root_entries else entries

        if len(candidates) != 1:
            raise ValueError(
                "Unable to identify a unique main application executable. "
                f"Candidates: {candidates}"
            )

        application_executable = candidates[0]
        seven_zip_command = [
            seven_zip, "e", "-y", "-so",
            str(source), application_executable
        ]

        try:
            extracted = subprocess.run(
                seven_zip_command,
                capture_output=True,
                timeout=120,
                check=False
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("NSIS executable extraction timed out") from error

        if extracted.returncode != 0 or not extracted.stdout:
            raise ValueError("Unable to extract the application executable")

        with tempfile.TemporaryDirectory(prefix="winux-nsis-") as temp_dir:
            executable_path = Path(temp_dir) / "application.exe"
            executable_path.write_bytes(extracted.stdout)
            application_architecture = self._get_exe_architecture(
                executable_path
            )

        installer_architecture = self._get_exe_architecture(source)

        return {
            "installer_architecture": installer_architecture,
            "application_architecture": application_architecture,
            "application_executable": application_executable
        }

    def _validate_installer_file(self, source, extension):
        size = source.stat().st_size

        if size < 64:
            raise ValueError("Installer file is too small")

        if extension == ".exe":
            return self._get_exe_architecture(source)

        if extension == ".msi":
            with source.open("rb") as file:
                signature = file.read(8)

            if signature != bytes.fromhex("D0CF11E0A1B11AE1"):
                raise ValueError("Invalid MSI/OLE file signature")

            return self._get_msi_architecture(source)

        raise ValueError("Unsupported installer format")

    def install(self, installer_file, prefix_name, timeout=3600):
        source = Path(installer_file).expanduser()

        if source.is_symlink():
            raise ValueError("Symbolic links are not accepted")

        if not source.is_file():
            raise FileNotFoundError(source)

        source = source.resolve()
        extension = source.suffix.lower()

        if extension not in (".exe", ".msi"):
            raise ValueError("Only EXE and MSI files are supported")

        installer_architecture = self._validate_installer_file(source, extension)

        application_architecture = (
            "not-inspected" if extension == ".msi" else "unknown"
        )
        application_executable = "not-inspected" if extension == ".msi" else "unknown"
        inspection_warning = None

        if extension == ".exe":
            try:
                nsis_info = self._inspect_nsis_application_architecture(source)
                application_architecture = nsis_info["application_architecture"]
                application_executable = nsis_info["application_executable"]
            except (ValueError, RuntimeError, OSError) as error:
                inspection_warning = str(error)

        if timeout <= 0:
            raise ValueError("Timeout must be positive")

        prefix_path = self.prefix_manager.get_path(prefix_name)

        if extension == ".exe":
            executable = shutil.which("wine")
            command = [executable, str(source)]
        else:
            executable = shutil.which("msiexec")
            command = [executable, "/i", str(source)]

        if not executable:
            raise RuntimeError("Required Wine component not found")

        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        prefix_architecture = self.prefix_manager.get_architecture(prefix_name)

        install_id = uuid.uuid4().hex[:12]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_file = self.log_dir / f"{timestamp}-{install_id}.log"
        lock_file = self.lock_dir / f"{prefix_name}.lock"

        started = datetime.now(timezone.utc)

        with open(log_file, "w", encoding="utf-8") as log:
            log.write(f"Install ID: {install_id}\n")
            log.write(f"Started: {started.isoformat()}\n")
            log.write(f"Installer: {source}\n")
            log.write(f"Type: {extension[1:].upper()}\n")
            log.write(f"Installer Architecture: {installer_architecture}\n")
            log.write(f"Application Architecture: {application_architecture}\n")
            log.write(f"Application Executable: {application_executable}\n")
            if inspection_warning:
                log.write(f"Inspection Warning: {inspection_warning}\n")
            log.write(f"Prefix: {prefix_name}\n")
            log.write(f"Command: {command!r}\n")
            log.write("=" * 60 + "\n")
            log.flush()

            try:
                with open(lock_file, "w", encoding="utf-8") as lock:
                    try:
                        fcntl.flock(
                            lock.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB
                        )
                    except BlockingIOError:
                        error = (
                            f"Another installation is using prefix: {prefix_name}"
                        )
                        log.write("\\nStatus: FAILED\\n")
                        log.write(f"Error: {error}\\n")
                        log.write(
                            f"Finished: {datetime.now(timezone.utc).isoformat()}\\n"
                        )
                        log.flush()
                        raise RuntimeError(error)

                    log.write("Status: RUNNING\n")
                    log.flush()

                    try:
                        result = subprocess.run(
                            command,
                            env=env,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=timeout,
                            check=False
                        )

                        if result.returncode != 0:
                            raise RuntimeError(
                                f"Installer exited with code {result.returncode}"
                            )

                        log.write("\nStatus: SUCCESS\n")

                        return {
                            "success": True,
                            "install_id": install_id,
                            "file": str(source),
                            "installer_architecture": installer_architecture,
                            "application_architecture": application_architecture,
                            "application_executable": application_executable,
                            "prefix": prefix_name,
                            "returncode": result.returncode,
                            "log": str(log_file)
                        }

                    except subprocess.TimeoutExpired:
                        log.write("\nStatus: TIMEOUT\n")
                        raise

                    except Exception as error:
                        log.write(f"\nStatus: FAILED\nError: {error}\n")
                        raise

                    finally:
                        log.write(
                            f"Finished: {datetime.now(timezone.utc).isoformat()}\n"
                        )

            except Exception:
                raise

    def history(self, limit=20):
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("Limit must be a positive integer")

        records = []

        for log_file in sorted(
            self.log_dir.glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        ):
            content = log_file.read_text(
                encoding="utf-8",
                errors="replace"
            )

            fields = {}

            for line in content.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1)
                    fields[key] = value

            statuses = [
                line.split(": ", 1)[1]
                for line in content.splitlines()
                if line.startswith("Status: ")
            ]

            records.append({
                "install_id": fields.get("Install ID", "Unknown"),
                "started": fields.get("Started", "Unknown"),
                "installer": fields.get("Installer", "Unknown"),
                "type": fields.get("Type", "Unknown"),
                "installer_architecture": fields.get("Installer Architecture", "Unknown"),
                "application_architecture": fields.get("Application Architecture", "Unknown"),
                "application_executable": fields.get("Application Executable", "Unknown"),
                "prefix": fields.get("Prefix", "Unknown"),
                "status": statuses[-1] if statuses else "UNKNOWN",
                "log": str(log_file)
            })

            if len(records) >= limit:
                break

        return records

    def stats(self):
        records = self.history(limit=10**9)

        counts = {
            "total": len(records),
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "unknown": 0
        }

        for record in records:
            status = record["status"].upper()

            if status == "SUCCESS":
                counts["success"] += 1
            elif status == "FAILED":
                counts["failed"] += 1
            elif status == "TIMEOUT":
                counts["timeout"] += 1
            else:
                counts["unknown"] += 1

        counts["success_rate"] = (
            round(counts["success"] / counts["total"] * 100, 2)
            if counts["total"] else 0
        )

        return counts
