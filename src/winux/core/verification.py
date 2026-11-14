import ipaddress
import socket
from pathlib import Path, PurePosixPath, PureWindowsPath


class VerificationManager:
    """Verify installed Windows applications using declarative profiles."""

    CHECK_TYPES = {"file", "process", "port", "registry"}

    def validate_profile(self, profile):
        """Validate profile structure and check parameters without executing checks."""
        if not isinstance(profile, dict):
            raise ValueError("Verification profile must be a dictionary")

        checks = profile.get("checks")

        if not isinstance(checks, list) or not checks:
            raise ValueError("Verification profile must contain checks")

        for index, check in enumerate(checks, start=1):
            if not isinstance(check, dict):
                raise ValueError(
                    f"Verification check #{index} must be a dictionary"
                )

            check_type = check.get("type")

            if check_type not in self.CHECK_TYPES:
                raise ValueError(
                    f"Unsupported verification check: {check_type}"
                )

            if check_type == "file":
                value = check.get("path")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("File check requires a path")

                windows_path = PureWindowsPath(value)
                relative = PurePosixPath(value.replace("\\", "/"))

                if (
                    relative.is_absolute()
                    or windows_path.is_absolute()
                    or windows_path.drive
                    or windows_path.root
                    or ".." in relative.parts
                ):
                    raise ValueError(
                        "File check path must stay inside the Wine prefix"
                    )

            elif check_type == "process":
                executable = check.get("executable")
                if not isinstance(executable, str) or not executable.strip():
                    raise ValueError(
                        "Process check requires an executable name"
                    )
                if "/" in executable or "\\" in executable:
                    raise ValueError(
                        "Process check expects an executable name only"
                    )

            elif check_type == "port":
                host = check.get("host", "127.0.0.1")
                port = check.get("port")
                timeout = check.get("timeout", 2)

                if not isinstance(host, str) or not host.strip():
                    raise ValueError("Port check requires a valid host")

                if host.casefold() != "localhost":
                    try:
                        address = ipaddress.ip_address(host)
                    except ValueError as error:
                        raise ValueError(
                            "Port checks are restricted to localhost"
                        ) from error

                    if not address.is_loopback:
                        raise ValueError(
                            "Port checks are restricted to localhost"
                        )

                if (
                    not isinstance(port, int)
                    or isinstance(port, bool)
                    or not 1 <= port <= 65535
                ):
                    raise ValueError("Port check requires a valid TCP port")

                if (
                    not isinstance(timeout, (int, float))
                    or isinstance(timeout, bool)
                    or not 0 < timeout <= 30
                ):
                    raise ValueError(
                        "Port check timeout must be between 0 and 30 seconds"
                    )

            elif check_type == "registry":
                key = check.get("key")
                if not isinstance(key, str) or not key.strip():
                    raise ValueError("Registry check requires a key")

                expected_value = check.get("contains")
                if expected_value is not None and not isinstance(
                    expected_value, str
                ):
                    raise ValueError(
                        "Registry contains value must be a string"
                    )

        return True

    def verify(self, profile, prefix_path, runtime=None):
        self.validate_profile(profile)
        checks = profile["checks"]
        results = []

        for check in checks:
            if not isinstance(check, dict):
                raise ValueError("Each verification check must be a dictionary")

            check_type = check.get("type")

            if check_type not in self.CHECK_TYPES:
                raise ValueError(f"Unsupported verification check: {check_type}")

            method = getattr(self, f"_check_{check_type}")
            results.append(method(check, Path(prefix_path), runtime))

        failed = [item for item in results if not item["passed"]]

        if failed:
            status = "FAILED"
        else:
            status = "VERIFIED"

        details = "; ".join(
            f"{item['type']}: {item['details']}" for item in results
        )

        return {
            "status": status,
            "details": details,
            "checks": results,
        }

    def _check_file(self, check, prefix_path, runtime):
        value = check.get("path")

        if not isinstance(value, str) or not value.strip():
            raise ValueError("File check requires a path")

        windows_path = PureWindowsPath(value)
        normalized = value.replace("\\", "/")
        relative = PurePosixPath(normalized)

        if (
            relative.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
            or ".." in relative.parts
        ):
            raise ValueError("File check path must stay inside the Wine prefix")

        prefix_root = Path(prefix_path).resolve()
        drive_c = Path(prefix_path) / "drive_c"
        root = drive_c.resolve()
        target = root.joinpath(*relative.parts)

        # Reject a symlinked drive_c and symlinks in every child component.
        has_symlink = drive_c.is_symlink()
        current = drive_c

        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                has_symlink = True

        resolved_target = target.resolve(strict=False)
        inside_prefix = (
            root.is_relative_to(prefix_root)
            and resolved_target.is_relative_to(root)
        )

        passed = (
            inside_prefix
            and not has_symlink
            and target.is_file()
        )

        return {
            "type": "file",
            "passed": passed,
            "details": f"{value}: {'found' if passed else 'not found'}",
        }

    def _check_process(self, check, prefix_path, runtime):
        executable = check.get("executable")

        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("Process check requires an executable name")

        if "/" in executable or "\\" in executable:
            raise ValueError("Process check expects an executable name only")

        expected = executable.casefold()
        found = False

        proc = Path("/proc")

        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue

            try:
                command_line = (entry / "cmdline").read_bytes()
            except (OSError, PermissionError):
                continue

            arguments = [
                item.decode(errors="replace")
                for item in command_line.split(b"\0")
                if item
            ]

            # Only argv[0] identifies the executable. Other arguments
            # may contain the same filename without running that program.
            if (
                arguments
                and Path(arguments[0].replace("\\", "/")).name.casefold()
                == expected
            ):
                found = True
                break

        return {
            "type": "process",
            "passed": found,
            "details": (
                f"{executable}: {'running' if found else 'not running'}"
            ),
        }

    def _check_port(self, check, prefix_path, runtime):
        host = check.get("host", "127.0.0.1")
        port = check.get("port")
        timeout = check.get("timeout", 2)

        if not isinstance(host, str) or not host.strip():
            raise ValueError("Port check requires a valid host")

        # Verification profiles must not probe remote network services.
        if host.casefold() != "localhost":
            try:
                address = ipaddress.ip_address(host)
            except ValueError as error:
                raise ValueError(
                    "Port checks are restricted to localhost"
                ) from error

            if not address.is_loopback:
                raise ValueError("Port checks are restricted to localhost")

        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("Port check requires a valid TCP port")

        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
            raise ValueError("Port check timeout must be between 0 and 30 seconds")

        try:
            with socket.create_connection((host, port), timeout=timeout):
                passed = True
        except OSError:
            passed = False

        return {
            "type": "port",
            "passed": passed,
            "details": (
                f"{host}:{port}: {'reachable' if passed else 'unreachable'}"
            ),
        }

    def _check_registry(self, check, prefix_path, runtime):
        if runtime is None:
            raise ValueError("Registry check requires a runtime")

        key = check.get("key")

        if not isinstance(key, str) or not key.strip():
            raise ValueError("Registry check requires a key")

        expected_value = check.get("contains")

        result = runtime.query_registry(
            prefix_path,
            key,
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = result.stdout or ""

        passed = result.returncode == 0 and key.casefold() in output.casefold()

        if passed and expected_value is not None:
            if not isinstance(expected_value, str):
                raise ValueError("Registry contains value must be a string")
            passed = expected_value.casefold() in output.casefold()

        return {
            "type": "registry",
            "passed": passed,
            "details": (
                f"{key}: {'found' if passed else 'not found'}"
            ),
        }
