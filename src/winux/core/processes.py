import json
import math
import logging
import os
import signal
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ProcessManager:
    """Persistent and identity-safe management of Winux processes."""

    def __init__(self, state_file=None):
        data_dir = Path.home() / ".local/share/winux"
        self.state_file = Path(
            state_file if state_file is not None else data_dir / "processes.json"
        )
        self._reject_symlink_components(self.state_file.parent)
        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        self._reject_symlink_components(self.state_file.parent)

        if self.state_file.is_symlink():
            raise ValueError("Process state file must not be a symbolic link")
        if self.state_file.exists() and not self.state_file.is_file():
            raise ValueError("Process state path must be a regular file")

        self.logger = logging.getLogger("winux.processes")

    @staticmethod
    def _reject_symlink_components(path):
        """Reject symbolic links in existing components of the state path."""
        path = Path(os.path.abspath(path))

        for component in reversed((path, *path.parents)):
            if component.is_symlink():
                raise ValueError(
                    f"Process state path must not contain symlinks: {component}"
                )

    @staticmethod
    def _process_start_time(pid):
        """Return Linux /proc process start time, or None if unavailable."""
        try:
            content = Path(f"/proc/{int(pid)}/stat").read_text(
                encoding="utf-8"
            )
            closing = content.rfind(")")
            if closing < 0:
                return None

            fields = content[closing + 2:].split()

            # Linux process states Z and X are no longer running.
            if fields[0] in {"Z", "X"}:
                return None

            return fields[19]
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _process_uid(pid):
        try:
            return Path(f"/proc/{int(pid)}").stat().st_uid
        except (OSError, ValueError):
            return None

    @staticmethod
    def _process_command(pid):
        try:
            raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
            return raw.replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
        except OSError:
            return ""

    def _read_records(self):
        self._reject_symlink_components(self.state_file.parent)

        # Check symlinks before exists(): dangling symlinks report exists=False.
        if self.state_file.is_symlink():
            raise ValueError("Process state file must not be a symbolic link")

        if not self.state_file.exists():
            return []

        if not self.state_file.is_file():
            raise ValueError("Process state path must be a regular file")

        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Unable to read process state file") from error

        if not isinstance(data, list):
            raise ValueError("Invalid process state format")

        required_fields = {
            "id", "pid", "process_start_time", "uid", "application",
            "prefix", "runtime", "executable", "command", "log",
            "started_at",
        }
        for record in data:
            if (
                not isinstance(record, dict)
                or not required_fields.issubset(record)
            ):
                raise ValueError("Invalid process record")

            process_id = record["id"]
            if (
                not isinstance(process_id, str)
                or len(process_id) != 32
                or any(char not in "0123456789abcdef" for char in process_id)
            ):
                raise ValueError("Invalid process record ID")

            pid = record["pid"]
            uid = record["uid"]
            if (
                isinstance(pid, bool)
                or not isinstance(pid, int)
                or pid <= 0
                or isinstance(uid, bool)
                or not isinstance(uid, int)
                or uid < 0
            ):
                raise ValueError("Invalid process identity in state file")

            start_time = record["process_start_time"]
            if (
                not isinstance(start_time, str)
                or not start_time.isdigit()
            ):
                raise ValueError("Invalid process start time in state file")

            for field in (
                "application", "prefix", "runtime", "executable",
                "started_at",
            ):
                if not isinstance(record[field], str) or not record[field]:
                    raise ValueError(f"Invalid process field: {field}")

            # /proc/<pid>/cmdline may legitimately be empty for kernel
            # threads or processes that expose no command line.
            if not isinstance(record["command"], str):
                raise ValueError("Invalid process field: command")

            if record["log"] is not None and not isinstance(record["log"], str):
                raise ValueError("Invalid process log path")
        return data

    def _write_records(self, records):
        self._reject_symlink_components(self.state_file.parent)
        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        self._reject_symlink_components(self.state_file.parent)

        if self.state_file.is_symlink():
            raise ValueError("Process state file must not be a symbolic link")
        if self.state_file.exists() and not self.state_file.is_file():
            raise ValueError("Process state path must be a regular file")

        fd, temporary_name = tempfile.mkstemp(
            prefix=".processes-",
            suffix=".tmp",
            dir=self.state_file.parent,
        )

        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(records, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_name, self.state_file)
            os.chmod(self.state_file, 0o600)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def register(
        self,
        pid,
        application,
        prefix,
        runtime,
        executable,
        log=None,
    ):
        pid = int(pid)
        start_time = self._process_start_time(pid)

        if start_time is None:
            raise ProcessLookupError(
                f"Process is not running or cannot be inspected: {pid}"
            )

        uid = self._process_uid(pid)
        if uid != os.getuid():
            raise PermissionError(
                "Cannot register a process owned by another user"
            )

        record = {
            "id": uuid.uuid4().hex,
            "pid": pid,
            "process_start_time": start_time,
            "uid": uid,
            "application": str(application),
            "prefix": str(prefix),
            "runtime": str(runtime),
            "executable": str(executable),
            "command": self._process_command(pid),
            "log": str(log) if log is not None else None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        records = self._read_records()
        records.append(record)
        self._write_records(records)
        return {**record, "status": "running"}

    def _status(self, record):
        pid = record.get("pid")
        start_time = record.get("process_start_time")

        if not isinstance(pid, int) or not isinstance(start_time, str):
            return "invalid"

        current_start_time = self._process_start_time(pid)

        if current_start_time is None:
            return "exited"

        if current_start_time != start_time:
            return "stale"

        if self._process_uid(pid) != record.get("uid"):
            return "stale"

        return "running"

    def list(self, include_inactive=True):
        result = []

        for record in self._read_records():
            item = dict(record)
            item["status"] = self._status(record)

            if include_inactive or item["status"] == "running":
                result.append(item)

        return result

    def get(self, process_id):
        for record in self._read_records():
            if record.get("id") == process_id:
                item = dict(record)
                item["status"] = self._status(record)
                return item

        raise KeyError(f"Unknown Winux process: {process_id}")

    def _signal_record(self, record, sig):
        pid = record["pid"]

        if self._status(record) != "running":
            return False

        # pidfd pins the exact process identity and prevents PID-reuse races.
        if not hasattr(os, "pidfd_open") or not hasattr(
            signal, "pidfd_send_signal"
        ):
            raise RuntimeError(
                "Safe process signaling requires Linux pidfd support"
            )

        try:
            pidfd = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            return False

        try:
            # Verify that the pinned process is still the registered process.
            if self._process_start_time(pid) != record["process_start_time"]:
                return False

            if self._process_uid(pid) != os.getuid():
                raise PermissionError(
                    "Refusing to signal a process owned by another user"
                )

            try:
                signal.pidfd_send_signal(pidfd, sig, None, 0)
            except ProcessLookupError:
                return False

            return True
        finally:
            os.close(pidfd)

    def stop(self, process_id, timeout=5, force=False):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError(
                "Timeout must be a finite, non-negative number"
            )

        record = None
        for candidate in self._read_records():
            if candidate.get("id") == process_id:
                record = candidate
                break

        if record is None:
            raise KeyError(f"Unknown Winux process: {process_id}")

        status = self._status(record)
        if status != "running":
            return {
                "id": process_id,
                "pid": record.get("pid"),
                "status": status,
                "stopped": False,
            }

        self._signal_record(record, signal.SIGTERM)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._status(record) != "running":
                return {
                    "id": process_id,
                    "pid": record["pid"],
                    "status": "exited",
                    "stopped": True,
                    "forced": False,
                }
            time.sleep(0.1)

        if self._status(record) != "running":
            return {
                "id": process_id,
                "pid": record["pid"],
                "status": "exited",
                "stopped": True,
                "forced": False,
            }

        if not force:
            return {
                "id": process_id,
                "pid": record["pid"],
                "status": "running",
                "stopped": False,
                "forced": False,
            }

        self._signal_record(record, signal.SIGKILL)

        deadline = time.monotonic() + max(timeout, 1)
        while time.monotonic() < deadline:
            if self._status(record) != "running":
                return {
                    "id": process_id,
                    "pid": record["pid"],
                    "status": "exited",
                    "stopped": True,
                    "forced": True,
                }
            time.sleep(0.1)

        return {
            "id": process_id,
            "pid": record["pid"],
            "status": "running",
            "stopped": False,
            "forced": True,
        }

    def cleanup(self):
        records = self._read_records()
        retained = [
            record for record in records
            if self._status(record) == "running"
        ]

        removed = len(records) - len(retained)
        if removed:
            self._write_records(retained)

        return {
            "removed": removed,
            "remaining": len(retained),
        }
