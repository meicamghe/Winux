"""Read-only Linux distribution and host integration discovery.

Detection reports facts about the host; it does not claim that a distribution
or package manager is fully supported by Winux.
"""
import os
import platform
import shutil
from pathlib import Path


_PACKAGE_MANAGER_COMMANDS = (
    ("apt", "apt-get"),
    ("dnf", "dnf"),
    ("pacman", "pacman"),
    ("zypper", "zypper"),
    ("apk", "apk"),
    ("xbps", "xbps-install"),
    ("emerge", "emerge"),
    ("nix", "nix"),
    ("rpm-ostree", "rpm-ostree"),
)


def detect_distribution(os_release=None):
    """Return normalized fields from /etc/os-release."""
    if os_release is None:
        try:
            os_release = platform.freedesktop_os_release()
        except (OSError, AttributeError):
            os_release = {}

    os_release = os_release if isinstance(os_release, dict) else {}
    return {
        "id": str(os_release.get("ID") or "unknown").strip().lower() or "unknown",
        "id_like": str(os_release.get("ID_LIKE") or "").strip().lower(),
        "name": str(os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Unknown Linux").strip(),
        "version_id": str(os_release.get("VERSION_ID") or "").strip(),
    }


def detect_package_managers(command_lookup=None):
    """List recognized package-manager executables available on PATH."""
    lookup = command_lookup or shutil.which
    available = []
    for label, executable in _PACKAGE_MANAGER_COMMANDS:
        try:
            if lookup(executable):
                available.append(label)
        except OSError:
            continue
    return available


def detect_init_system(pid1_executable=None):
    """Identify PID 1 from its executable name without invoking it."""
    if pid1_executable is None:
        try:
            pid1_executable = os.readlink("/proc/1/exe")
        except OSError:
            return "unknown"
    name = Path(str(pid1_executable).replace(" (deleted)", "")).name.lower()
    aliases = {
        "systemd": "systemd",
        "init": "sysvinit-or-unknown",
        "openrc-init": "openrc",
        "runit": "runit",
        "s6-svscan": "s6",
        "busybox": "busybox-init",
        "tini": "container-init",
        "dumb-init": "container-init",
    }
    return aliases.get(name, name or "unknown")


def detect_host_environment():
    """Collect read-only distribution, package-manager, and init metadata."""
    return {
        "distribution": detect_distribution(),
        "package_managers": detect_package_managers(),
        "init_system": detect_init_system(),
    }
