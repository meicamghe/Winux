from datetime import datetime
from pathlib import Path

from winux.core.applications import ApplicationManager
from winux.core.prefix import PrefixManager
from winux.runtime.manager import RuntimeManager


class ApplicationRunner:
    def __init__(self, runtime_manager=None):
        self.runtime_manager = runtime_manager or RuntimeManager()
        self.prefix_manager = PrefixManager(
            runtime_manager=self.runtime_manager
        )
        self.application_manager = ApplicationManager()

        self.log_dir = (
            Path.home() / ".local/share/winux/logs/app-runs"
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run(self, prefix_name, application_id):
        prefix_path = self.prefix_manager.get_path(prefix_name)
        runtime = self.prefix_manager.get_runtime(prefix_name)

        if not runtime.is_available():
            raise RuntimeError(
                f"Runtime is not available: {runtime.name}"
            )

        application = self.application_manager.info(
            prefix_name,
            application_id
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

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        log_file = self.log_dir / (
            f"{prefix_name}-{timestamp}.log"
        )

        with log_file.open("ab") as output:
            process = runtime.run(
                prefix_path,
                executable,
                cwd=str(executable.parent),
                stdin=-3,
                stdout=output,
                stderr=-2,
                start_new_session=True,
            )

        return {
            "pid": process.pid,
            "executable": str(executable),
            "log": str(log_file),
            "application": application.get("DisplayName"),
        }
