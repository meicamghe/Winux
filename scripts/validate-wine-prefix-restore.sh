#!/usr/bin/env bash
set -Eeuo pipefail

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
