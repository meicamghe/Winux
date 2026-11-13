import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from winux.core.applications import ApplicationManager
from winux.core.prefix import PrefixManager


class ApplicationRunner:
    def __init__(self):
        self.prefix_manager = PrefixManager()
        self.application_manager = ApplicationManager()

        self.log_dir = (
            Path.home() / ".local/share/winux/logs/app-runs"
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run(self, prefix_name, application_id):
        wine = shutil.which("wine")
        if not wine:
            raise RuntimeError("Wine executable not found")

        prefix_path = self.prefix_manager.get_path(prefix_name)

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
                "Application executable is outside the Wine prefix"
            )

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        log_file = self.log_dir / (
            f"{prefix_name}-{timestamp}.log"
        )

        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)

        with log_file.open("ab") as output:
            process = subprocess.Popen(
                [wine, str(executable)],
                cwd=str(executable.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        return {
            "pid": process.pid,
            "executable": str(executable),
            "log": str(log_file),
            "application": application.get("DisplayName"),
        }
