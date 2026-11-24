import platform
import re
import shutil
import subprocess

from winux.runtime.manager import RuntimeManager
from winux.platform.distribution import detect_host_environment


def _command_status(name):
    return shutil.which(name)


def _systemd_user_manager_status(systemctl_path):
    """Return whether the current user's systemd manager is responding."""
    try:
        result = subprocess.run(
            [systemctl_path, "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return False, detail or "systemd user manager is unavailable"

    return True, "systemd user manager is responding"



def _wine_version_warning(version):
    """Return a compatibility warning for Wine versions older than 11.0."""
    if not isinstance(version, str):
        return "Wine version could not be parsed; WoW64 compatibility is unknown"

    match = re.search(r"\bwine[- ]?(\d+)\.(\d+)(?:\.\d+)?\b", version, re.IGNORECASE)
    if not match:
        return "Wine version could not be parsed; WoW64 compatibility is unknown"

    major, minor = (int(part) for part in match.groups())
    if (major, minor) < (11, 0):
        return (f"Wine {major}.{minor} detected; Wine 11.0 or newer is "
                "recommended for fully supported new WoW64 mode")
    return ("Wine 11.0+ detected; this version alone does not confirm that "
            "the installed build has new WoW64 enabled")

def check_runtime(runtime_manager=None):
    """Run read-only diagnostics for Winux's core runtime requirements.

    Missing optional integrations are reported as warnings, not failures.
    No prefixes, applications, or services are created or started.
    """
    print("Winux System Diagnostics")
    print("-" * 35)

    failed = False

    try:
        manager = (
            runtime_manager
            if runtime_manager is not None
            else RuntimeManager()
        )
        name = manager.get_default_name()
        runtime = manager.get(name)

        if not runtime.is_available():
            print(f"[FAIL] Runtime '{name}' is not available.")
            failed = True
        else:
            print(f"[OK] Runtime: {name}")

            try:
                wine_version = runtime.version()
                print(f"[OK] Version: {wine_version}")
                version_warning = _wine_version_warning(wine_version) if name == "wine" else None
                if version_warning:
                    print(f"[WARN] {version_warning}")
            except Exception as error:
                print(f"[FAIL] Runtime version check failed: {error}")
                failed = True

        host = detect_host_environment()
        distro = host["distribution"]
        version = f" {distro['version_id']}" if distro["version_id"] else ""
        print(f"[INFO] Linux distribution: {distro['name']}{version} ({distro['id']})")
        print(f"[INFO] Init system: {host['init_system']}")
        managers = ", ".join(host["package_managers"]) or "unknown"
        print(f"[INFO] Package manager(s): {managers}")
        print(f"[INFO] Host architecture: {platform.machine() or 'unknown'}")

        required_commands = {
            "wineboot": "Prefix initialization",
        }
        optional_commands = {
            "msiexec": "MSI installation",
            "wineserver": "Wine process lifecycle",
            "winepath": "Windows/Linux path conversion",
            "msiinfo": "MSI architecture inspection",
            "7z": "NSIS installer inspection",
        }

        for command, purpose in required_commands.items():
            if _command_status(command):
                print(f"[OK] {command}: available ({purpose})")
            else:
                print(f"[FAIL] {command}: missing ({purpose})")
                failed = True

        for command, purpose in optional_commands.items():
            if _command_status(command):
                print(f"[OK] {command}: available ({purpose})")
            else:
                print(f"[WARN] {command}: missing ({purpose} unavailable)")

        systemctl_path = _command_status("systemctl")
        if not systemctl_path:
            print("[WARN] systemd user manager: systemctl is unavailable")
        else:
            manager_available, detail = _systemd_user_manager_status(
                systemctl_path
            )
            if manager_available:
                print("[OK] systemd user manager: available")
            else:
                print(f"[WARN] systemd user manager: unavailable ({detail})")

        for plugin_error in manager.plugin_errors():
            print(
                "[WARN] Runtime plugin "
                f"{plugin_error['plugin']} failed during "
                f"{plugin_error['stage']}: {plugin_error['error']}"
            )

        # Discover optional service backend plugins for diagnostics without
        # instantiating a backend or requiring systemd.
        from winux.platform.service_backends import ServiceBackendManager

        service_backends = ServiceBackendManager()
        for plugin_error in service_backends.plugin_errors():
            print(
                "[WARN] Service backend plugin "
                f"{plugin_error['plugin']} failed during "
                f"{plugin_error['stage']}: {plugin_error['error']}"
            )

        return not failed

    except Exception as error:
        print(f"[FAIL] Runtime check failed: {error}")
        return False
