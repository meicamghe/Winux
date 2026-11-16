import logging
import os
import subprocess
import stat
from datetime import datetime
from pathlib import Path

from winux.core.applications import ApplicationManager
from winux.core.prefix import PrefixManager
from winux.core.processes import ProcessManager
from winux.runtime.manager import RuntimeManager


class ApplicationRunner:
    @staticmethod
    def _normalize_arguments(args):
        if args is None:
            return []
        if not isinstance(args, (list, tuple)):
            raise TypeError("Application arguments must be a list or tuple of strings")
        if any(not isinstance(argument, str) for argument in args):
            raise TypeError("Application arguments must contain only strings")
        if any("\\x00" in argument for argument in args):
            raise ValueError("Application arguments must not contain NUL characters")
        return list(args)

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

    @classmethod
    def _open_log_file(cls, path):
        """Create a private log file without following directory or file symlinks."""
        path = Path(path)
        cls._reject_symlink_components(path.parent)

        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise ValueError("Application log path must be a directory")

            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(
                path.name,
                flags,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                return os.fdopen(descriptor, "ab")
            except Exception:
                os.close(descriptor)
                os.unlink(path.name, dir_fd=directory_fd)
                raise
        finally:
            os.close(directory_fd)

    @staticmethod
    def _terminate_unregistered_process(process, timeout=5):
        """Stop a launched process if Winux cannot register its identity."""
        try:
            process.terminate()
        except ProcessLookupError:
            return

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

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

    def run_foreground(self, prefix_name, application_id, args=None):
        """Run an installed application and wait for its exit.

        Standard streams are inherited so systemd can capture the output.
        This method deliberately does not detach the process.
        """
        arguments = self._normalize_arguments(args)
        prefix_path, runtime, _application, executable = (
            self._resolve_application(prefix_name, application_id)
        )

        process = runtime.run(
            prefix_path,
            executable,
            args=arguments,
            cwd=str(executable.parent),
        )

        return process.wait()

    def run(self, prefix_name, application_id, args=None):
        arguments = self._normalize_arguments(args)
        prefix_path, runtime, application, executable = (
            self._resolve_application(prefix_name, application_id)
        )

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        log_file = self.log_dir / f"{prefix_name}-{timestamp}.log"

        with self._open_log_file(log_file) as output:
            process = runtime.run(
                prefix_path,
                executable,
                args=arguments,
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
            try:
                self._terminate_unregistered_process(process)
            except Exception as cleanup_error:
                raise RuntimeError(
                    "Application process registration failed and the "
                    "unregistered process could not be stopped. "
                    f"PID: {process.pid}. Registration error: {error}. "
                    f"Cleanup error: {cleanup_error}"
                ) from error

            raise RuntimeError(
                "Application process was stopped because Winux could not "
                f"register it (PID: {process.pid}): {error}"
            ) from error

        return result
