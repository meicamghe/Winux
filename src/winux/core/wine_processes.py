"""Conservative, read-only inspection of Wine processes using a prefix.

This is a blocker detector, not a proof that a prefix is quiescent. In
particular, a process can hide or rewrite its environment after startup, and
Wine clients can be launched outside Winux immediately after an inspection.
Backup must remain disabled until a stronger exclusion protocol is available.
"""

import os
from pathlib import Path


_WINE_EXECUTABLES = {
    "wine", "wine64", "wine-preloader", "wine64-preloader",
    "wineserver", "wineboot", "wineboot.exe", "msiexec",
}


def _normalise_prefix(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _read_environment(path):
    raw = path.read_bytes()
    values = {}
    for item in raw.split(b"\\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        if key == b"WINEPREFIX":
            if key in values:
                raise ValueError("duplicate WINEPREFIX environment entries")
            values[key] = os.fsdecode(value)
    value = values.get(b"WINEPREFIX")
    return value if value else None


def _is_wine_candidate(process_dir):
    """Return True for recognizable Wine loaders/servers and PE processes."""
    executable = os.readlink(process_dir / "exe")
    executable_name = os.path.basename(executable).lower()
    if executable_name in _WINE_EXECUTABLES:
        return True

    comm = (process_dir / "comm").read_text(encoding="utf-8").strip().lower()
    return comm.endswith(".exe") or comm in _WINE_EXECUTABLES


def inspect_prefix_processes(prefix_path, *, proc_root="/proc", uid=None):
    """Return a conservative busy/clear/unknown snapshot for one Wine prefix.

    A matching WINEPREFIX in any same-UID process environment is a blocker.
    Recognizable Wine processes without readable, explicit prefix information
    make the result unknown (or busy for Wine's implicit ~/.wine prefix).
    Processes owned by other UIDs cannot normally access a private managed
    prefix and are outside this user's inspection scope.

    The result is advisory: it cannot prevent a new Wine client from starting
    after the snapshot, nor detect a process that deliberately scrubs all
    identifying information.
    """
    target = _normalise_prefix(prefix_path)
    default_prefix = _normalise_prefix(Path.home() / ".wine")
    current_uid = os.getuid() if uid is None else uid
    root = Path(proc_root)

    try:
        entries = list(root.iterdir())
    except OSError as error:
        return {
            "state": "unknown",
            "pids": [],
            "reasons": [f"cannot enumerate process table: {type(error).__name__}"],
        }

    blockers = []
    uncertain = []

    for entry in entries:
        if not entry.name.isdigit():
            continue

        try:
            if entry.stat().st_uid != current_uid:
                continue
        except FileNotFoundError:
            continue
        except OSError as error:
            uncertain.append((entry.name, f"cannot inspect process ownership: {type(error).__name__}"))
            continue

        try:
            environment_prefix = _read_environment(entry / "environ")
        except FileNotFoundError:
            continue
        except OSError as error:
            # Without the environment, a process that might be Wine cannot be
            # safely excluded. Determine whether it is recognizable below.
            environment_prefix = None
            environment_error = type(error).__name__
        except ValueError as error:
            uncertain.append((entry.name, str(error)))
            continue
        else:
            environment_error = None

        if environment_prefix is not None:
            if _normalise_prefix(environment_prefix) == target:
                blockers.append(entry.name)
            continue

        try:
            candidate = _is_wine_candidate(entry)
        except FileNotFoundError:
            continue
        except OSError as error:
            uncertain.append((entry.name, f"cannot identify process executable: {type(error).__name__}"))
            continue

        if not candidate:
            continue

        if environment_error is not None:
            uncertain.append((entry.name, f"Wine process environment unreadable: {environment_error}"))
        elif target == default_prefix:
            blockers.append(entry.name)
        else:
            uncertain.append((entry.name, "Wine process has no explicit WINEPREFIX"))

    if blockers:
        return {
            "state": "busy",
            "pids": sorted(set(blockers), key=int),
            "reasons": ["matching Wine prefix process detected"],
        }
    if uncertain:
        return {
            "state": "unknown",
            "pids": sorted({pid for pid, _ in uncertain}, key=int),
            "reasons": sorted({reason for _, reason in uncertain}),
        }
    return {"state": "clear", "pids": [], "reasons": []}
