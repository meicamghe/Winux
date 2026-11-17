#!/usr/bin/env bash
set -Eeuo pipefail

# GitHub-hosted runners expose same-UID user-session processes (systemd and
# sd-pam) whose /proc/<pid>/exe links are intentionally unreadable. The
# production inspector correctly fails closed on those ambiguous entries.
# Run this disposable integration fixture under a dedicated unprivileged UID
# so its /proc view contains only the fixture's own processes, without
# weakening production process inspection or ignoring unknown processes.
if [[ "${WINUX_RESTORE_TEST_ISOLATED:-0}" != "1" ]]; then
  script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  command -v sudo >/dev/null 2>&1 || {
    echo "MISSING: sudo is required to isolate the Wine restore integration user" >&2
    exit 2
  }
  nobody_uid="$(id -u nobody)"
  if [[ "$(id -u)" != "$nobody_uid" ]]; then
    isolated_home="$(mktemp -d "${TMPDIR:-/tmp}/winux-restore-user.XXXXXX")"
    chown nobody:"$(id -gn nobody)" "$isolated_home"
    chmod 700 "$isolated_home"
    trap 'rm -rf -- "$isolated_home"' EXIT
    set +e
    sudo -u nobody -- env \
      WINUX_RESTORE_TEST_ISOLATED=1 \
      HOME="$isolated_home" TMPDIR=/tmp \
      bash "$script_path"
    status=$?
    set -e
    exit "$status"
  fi
fi

for tool in wine wineboot wineserver timeout python3 i686-w64-mingw32-gcc x86_64-w64-mingw32-gcc; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "MISSING: required tool '$tool' is not installed" >&2
    exit 2
  }
done

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/winux-prefix-restore.XXXXXX")"
home="$work_dir/home"
source_prefix="$home/.local/share/winux/prefixes/source"
restored_prefix="$home/.local/share/winux/prefixes/restored"
archive="$work_dir/source-prefix.wux"
mkdir -p "$home"
export HOME="$home"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

cleanup() {
  WINEPREFIX="$source_prefix" wineserver -k >/dev/null 2>&1 || true
  WINEPREFIX="$restored_prefix" wineserver -k >/dev/null 2>&1 || true
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

cat > "$work_dir/smoke.c" <<'EOF'
int main(void) {
    return 0;
}
EOF
i686-w64-mingw32-gcc -Os -s -o "$work_dir/smoke-x86.exe" "$work_dir/smoke.c"
x86_64-w64-mingw32-gcc -Os -s -o "$work_dir/smoke-x64.exe" "$work_dir/smoke.c"

echo "Wine: $(wine --version)"
echo "Creating a real Wine-managed WoW64 source prefix"
python3 - <<'PY'
from winux.core.prefix import PrefixManager

manager = PrefixManager()
created = manager.create("source", architecture="x64")
print(f"CREATED: {created}")
PY

# Backup is permitted only after the Wine server has been stopped. The
# backup API still performs its own conservative /proc blocker inspection.
WINEPREFIX="$source_prefix" wineserver -k >/dev/null 2>&1 || true
timeout --signal=TERM --kill-after=5s 30s env WINEPREFIX="$source_prefix" wineserver -w >/dev/null 2>&1 || true

echo "Backing up and restoring the real Wine prefix"
python3 - <<'PY'
import os
from pathlib import Path
from winux.core.wine_processes import inspect_prefix_processes

prefix = Path.home() / ".local/share/winux/prefixes/source"
state = inspect_prefix_processes(prefix)
print(f"WINE PROCESS PREFLIGHT: {state}")
for pid in state["pids"]:
    process = Path("/proc") / pid
    try:
        comm = (process / "comm").read_text().strip()
    except OSError as error:
        comm = f"<unreadable:{type(error).__name__}>"
    try:
        executable = os.readlink(process / "exe")
    except OSError as error:
        executable = f"<unreadable:{type(error).__name__}>"
    try:
        raw = (process / "environ").read_bytes()
        wineprefix = next(
            (item.split(b"=", 1)[1].decode(errors="replace")
             for item in raw.split(bytes([0])) if item.startswith(b"WINEPREFIX=")),
            None,
        )
    except OSError as error:
        wineprefix = f"<unreadable:{type(error).__name__}>"
    print(f"BLOCKER pid={pid} comm={comm!r} exe={executable!r} WINEPREFIX={wineprefix!r}")
PY
python3 - "$archive" <<'PY'
import sys
from pathlib import Path
from winux.core.prefix import PrefixManager
from winux.core.prefix_archive import inspect_prefix_backup
from winux.core.prefix_backup import backup_prefix
from winux.core.prefix_restore import restore_prefix

archive = Path(sys.argv[1])
manager = PrefixManager()
backup = backup_prefix(
    "source",
    archive,
    confirm_all_wine_apps_closed=True,
    prefix_manager=manager,
)
inspection = inspect_prefix_backup(archive)
restored = restore_prefix(archive, "restored", prefix_manager=manager)
manager.get_path("restored")
assert inspection["architecture"] == "win64"
assert restored["runtime"] == manager.runtime_manager.get_default_name()
assert (Path(restored["path"]) / "system.reg").is_file()
assert (Path(restored["path"]) / "dosdevices/c:").is_symlink()
assert not (Path(restored["path"]) / "dosdevices/z:").exists()
print(f"BACKUP: {backup['files']} files, {backup['total_bytes']} bytes")
print(f"RESTORED: {restored['path']} ({restored['architecture']}, {restored['runtime']})")
PY

for architecture in x86 x64; do
  executable="$work_dir/smoke-$architecture.exe"
  echo "RUN AFTER RESTORE: $architecture Windows executable"
  if WINEPREFIX="$restored_prefix" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$executable"; then
    echo "PASS: restored prefix launched $architecture executable"
  else
    status=$?
    echo "FAIL: restored prefix $architecture executable returned status $status" >&2
    exit "$status"
  fi
done

echo "PASS: real Wine prefix backup and restore, followed by x86/x64 PE execution"
