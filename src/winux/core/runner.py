import logging
import os
from datetime import datetime
from pathlib import Path

from winux.core.applications import ApplicationManager
from winux.core.prefix import PrefixManager
from winux.core.processes import ProcessManager
from winux.runtime.manager import RuntimeManager


class ApplicationRunner:
    def __init__(self, runtime_manager=None, process_manager=None):
        self.runtime_manager = (
            runtime_manager if runtime_manager is not None else RuntimeManager()
        )
        self.process_manager = (
            process_manager if process_manager is not None else ProcessManager()
        )
        self.prefix_manager = PrefixManager(
            runtime_manager=self.runtime_manager
        )
        self.application_manager = ApplicationManager()
        self.logger = logging.getLogger("winux.runner")

        self.log_dir = (
            Path.home() / ".local/share/winux/logs/app-runs"
        )
        self._reject_symlink_components(self.log_dir)
        self.log_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        self._reject_symlink_components(self.log_dir)
        if not self.log_dir.is_dir():
            raise ValueError("Application log path must be a directory")
        self.log_dir.chmod(0o700)

    @staticmethod
    def _reject_symlink_components(path):
        """Reject symlinks in existing components of the log path."""
        path = Path(os.path.abspath(path))

        for component in reversed((path, *path.parents)):
            if component.is_symlink():
                raise ValueError(
                    f"Application log path must not contain symlinks: {component}"
                )

    @staticmethod
    def _open_log_file(path):
        """Create a private log file without following existing symlinks."""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        return os.fdopen(descriptor, "ab")

    def _resolve_application(self, prefix_name, application_id):
        """Resolve and validate an application before starting its process."""
        prefix_path = self.prefix_manager.get_path(prefix_name)
        runtime = self.prefix_manager.get_runtime(prefix_name)

        if not runtime.is_available():
            raise RuntimeError(
                f"Runtime is not available: {runtime.name}"
            )

        application = self.application_manager.info(
            prefix_name,
            application_id,
        )

        executable_value = application.get("executable_path")
        if not executable_value:
            raise FileNotFoundError(
                "Application executable path was not found"
            )

        drive_c = (prefix_path / "drive_c").resolve(strict=True)
        executable = Path(executable_value).resolve(strict=True)

        if not executable.is_file():
            raise FileNotFoundError(
                f"Application executable not found: {executable}"
            )

        try:
            executable.relative_to(drive_c)
        except ValueError:
            raise ValueError(
                "Application executable is outside the runtime prefix"
            ) from None

        return prefix_path, runtime, application, executable

    def run_foreground(self, prefix_name, application_id):
        """Run an installed application and wait for its exit.

        Standard streams are inherited so systemd can capture the output.
        This method deliberately does not detach the process.
        """
        prefix_path, runtime, _application, executable = (
            self._resolve_application(prefix_name, application_id)
        )

        process = runtime.run(
            prefix_path,
            executable,
            cwd=str(executable.parent),
        )

        return process.wait()

    def run(self, prefix_name, application_id):
        prefix_path, runtime, application, executable = (
            self._resolve_application(prefix_name, application_id)
        )

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        log_file = self.log_dir / f"{prefix_name}-{timestamp}.log"

        with self._open_log_file(log_file) as output:
            process = runtime.run(
                prefix_path,
                executable,
                cwd=str(executable.parent),
                stdin=-3,
                stdout=output,
                stderr=-2,
                start_new_session=True,
            )

        application_name = (
            application.get("DisplayName") or application_id
        )

        result = {
            "pid": process.pid,
            "process_id": None,
            "executable": str(executable),
            "log": str(log_file),
            "application": application_name,
        }

        try:
            record = self.process_manager.register(
                pid=process.pid,
                application=application_name,
                prefix=prefix_name,
                runtime=runtime.name,
                executable=str(executable),
                log=str(log_file),
            )
            result["process_id"] = record["id"]
        except Exception as error:
            self.logger.warning(
                "Application started but process registration failed "
                "(pid=%s, application=%s): %s",
                process.pid,
                application_name,
                error,
            )
            result["process_registration_error"] = str(error)

        return result
