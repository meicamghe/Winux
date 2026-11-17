#!/usr/bin/env bash
set -Eeuo pipefail

# Disposable real-prefix restore fixture; never relax production process checks.
# Create the Wine prefix as the runner user. Ubuntu's Wine 9 package crashes
# during wineboot when launched under the dedicated nobody account, while the
# later backup/restore process inspection must run under that isolated UID.
if [[ "${WINUX_RESTORE_TEST_ISOLATED:-0}" != "1" ]]; then
  script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  repo_root="$(cd "$(dirname "$script_path")/.." && pwd)"
  command -v sudo >/dev/null 2>&1 || {
    echo "MISSING: sudo is required to isolate the Wine restore integration user" >&2
    exit 2
  }
  nobody_uid="$(id -u nobody)"
  if [[ "$(id -u)" != "$nobody_uid" ]]; then
    isolated_home="$(mktemp -d "${TMPDIR:-/tmp}/winux-restore-user.XXXXXX")"
    mkdir -p "$isolated_home/scripts" "$isolated_home/home"
    cp "$script_path" "$isolated_home/scripts/validate-wine-prefix-restore.sh"
    cp -a "$repo_root/src" "$isolated_home/src"
    export HOME="$isolated_home/home"
    export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
    echo "Wine: $(wine --version)"
    echo "Creating a real Wine-managed WoW64 source prefix as the runner user"
    env -u LD_LIBRARY_PATH python3 - <<'PYCREATE'
from winux.core.prefix import PrefixManager
manager = PrefixManager()
created = manager.create("source", architecture="x64")
print(f"CREATED: {created}")
PYCREATE
    source_prefix="$HOME/.local/share/winux/prefixes/source"
    WINEPREFIX="$source_prefix" wineserver -k >/dev/null 2>&1 || true
    timeout --signal=TERM --kill-after=5s 30s env WINEPREFIX="$source_prefix" wineserver -w >/dev/null 2>&1 || true
    sudo chown -R nobody:"$(id -gn nobody)" "$isolated_home"
    sudo chmod 700 "$isolated_home"
    trap 'sudo rm -rf -- "$isolated_home"' EXIT
    set +e
    sudo -u nobody -- env \
      WINUX_RESTORE_TEST_ISOLATED=1 \
      WINUX_RESTORE_PREFIX_PRECREATED=1 \
      HOME="$isolated_home/home" TMPDIR=/tmp \
      bash "$isolated_home/scripts/validate-wine-prefix-restore.sh"
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
home="$HOME"
source_prefix="$home/.local/share/winux/prefixes/source"
restored_prefix="$home/.local/share/winux/prefixes/restored"
archive="$work_dir/source-prefix.wux"
mkdir -p "$work_dir"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

cleanup() {
  WINEPREFIX="$source_prefix" wineserver -k >/dev/null 2>&1 || true
  WINEPREFIX="$restored_prefix" wineserver -k >/dev/null 2>&1 || true
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

cat > "$work_dir/smoke.c" <<'EOF'
int main(void) { return 0; }
EOF
i686-w64-mingw32-gcc -Os -s -o "$work_dir/smoke-x86.exe" "$work_dir/smoke.c"
x86_64-w64-mingw32-gcc -Os -s -o "$work_dir/smoke-x64.exe" "$work_dir/smoke.c"

if [[ "${WINUX_RESTORE_PREFIX_PRECREATED:-0}" != "1" ]]; then
  echo "ERROR: integration prefix was not pre-created" >&2
  exit 2
fi
[[ -f "$source_prefix/system.reg" ]] || {
  echo "ERROR: pre-created source prefix is missing" >&2
  exit 2
}
echo "Using runner-created prefix owned by isolated test user: $source_prefix"

echo "Backing up and restoring the real Wine prefix"
env -u LD_LIBRARY_PATH python3 - <<'PY'
import os
from pathlib import Path
from winux.core.wine_processes import inspect_prefix_processes
prefix = Path.home() / ".local/share/winux/prefixes/source"
state = inspect_prefix_processes(prefix)
print(f"WINE PROCESS PREFLIGHT: {state}")
for pid in state["pids"]:
    process = Path("/proc") / pid
    try: comm = (process / "comm").read_text().strip()
    except OSError as error: comm = f"<unreadable:{type(error).__name__}>"
    try: executable = os.readlink(process / "exe")
    except OSError as error: executable = f"<unreadable:{type(error).__name__}>"
    try:
        raw = (process / "environ").read_bytes()
        wineprefix = next((item.split(b"=", 1)[1].decode(errors="replace")
                           for item in raw.split(bytes([0])) if item.startswith(b"WINEPREFIX=")), None)
    except OSError as error: wineprefix = f"<unreadable:{type(error).__name__}>"
    print(f"BLOCKER pid={pid} comm={comm!r} exe={executable!r} WINEPREFIX={wineprefix!r}")
PY
env -u LD_LIBRARY_PATH python3 - "$archive" <<'PY'
import sys
from pathlib import Path
from winux.core.prefix import PrefixManager
from winux.core.prefix_archive import inspect_prefix_backup
from winux.core.prefix_backup import backup_prefix
from winux.core.prefix_restore import restore_prefix
archive = Path(sys.argv[1])
manager = PrefixManager()
backup = backup_prefix("source", archive, confirm_all_wine_apps_closed=True, prefix_manager=manager)
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

# Control: prove this Wine build can launch both architectures in the
# original prefix before attributing any failure to the restore output.
for architecture in x86 x64; do
  executable="$work_dir/smoke-$architecture.exe"
  echo "CONTROL RUN IN SOURCE PREFIX: $architecture Windows executable"
  if (cd "$source_prefix/drive_c" && env -u LD_LIBRARY_PATH WINEPREFIX="$source_prefix" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$executable"); then
    echo "PASS: source prefix launched $architecture executable"
  else
    status=$?
    echo "FAIL: source prefix $architecture executable returned status $status" >&2
    exit "$status"
  fi
done

for architecture in x86 x64; do
  executable="$work_dir/smoke-$architecture.exe"
  echo "RUN AFTER RESTORE: $architecture Windows executable"
  if (cd "$restored_prefix/drive_c" && env -u LD_LIBRARY_PATH WINEPREFIX="$restored_prefix" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$executable"); then
    echo "PASS: restored prefix launched $architecture executable"
  else
    status=$?
    echo "FAIL: restored prefix $architecture executable returned status $status" >&2
    exit "$status"
  fi
done

echo "PASS: real Wine prefix backup and restore, followed by x86/x64 PE execution"
