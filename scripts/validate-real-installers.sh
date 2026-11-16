#!/usr/bin/env bash
set -Eeuo pipefail

for tool in python wine wineboot wineserver timeout makensis 7z i686-w64-mingw32-gcc x86_64-w64-mingw32-gcc; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "MISSING: required tool '$tool' is not installed" >&2
    exit 2
  }
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/winux-installer-wow64.XXXXXX")"
export HOME="$work_dir/home"
mkdir -p "$HOME"
cleanup() {
  for name in fixture-x86 fixture-x64; do
    WINEPREFIX="$HOME/.local/share/winux/prefixes/$name" wineserver -k >/dev/null 2>&1 || true
  done
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

cat > "$work_dir/fixture.c" <<'EOF'
#include <stdio.h>
int main(void) {
    FILE *marker = fopen("fixture-ran.txt", "w");
    if (!marker) return 10;
    fputs("Winux installed and launched this Windows application\n", marker);
    return fclose(marker) == 0 ? 0 : 11;
}
EOF

cat > "$work_dir/fixture.nsi" <<'EOF'
!include "MUI2.nsh"
Name "Winux WoW64 Installer Fixture"
OutFile "fixture-setup.exe"
InstallDir "$LOCALAPPDATA\\WinuxFixture"
RequestExecutionLevel user
SilentInstall silent
Section "Install"
  SetOutPath "$INSTDIR"
  File "fixture.exe"
  CreateDirectory "$SMPROGRAMS\\WinuxFixture"
  CreateShortCut "$SMPROGRAMS\\WinuxFixture\\Winux Fixture.lnk" "$INSTDIR\\fixture.exe"
  WriteUninstaller "$INSTDIR\\uninstall.exe"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinuxFixture" "DisplayName" "Winux EXE Fixture"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinuxFixture" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinuxFixture" "UninstallString" '"$INSTDIR\\uninstall.exe"'
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\\fixture.exe"
  Delete "$INSTDIR\\uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\\WinuxFixture\\Winux Fixture.lnk"
  RMDir "$SMPROGRAMS\\WinuxFixture"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinuxFixture"
SectionEnd
EOF

for architecture in x86 x64; do
  case "$architecture" in
    x86) compiler=i686-w64-mingw32-gcc ;;
    x64) compiler=x86_64-w64-mingw32-gcc ;;
  esac
  "$compiler" -Os -s -o "$work_dir/fixture.exe" "$work_dir/fixture.c"
  (cd "$work_dir" && makensis -V2 -DARCH="$architecture" fixture.nsi >/dev/null)
  setup="$work_dir/fixture-setup.exe"
  prefix="fixture-$architecture"

  echo "CREATE: $architecture WoW64 prefix"
  timeout --signal=TERM --kill-after=5s 120s winux prefix create "$prefix" --arch x64

  echo "INSTALL: $architecture application using Winux installer engine"
  timeout --signal=TERM --kill-after=5s 180s winux install "$setup" --prefix "$prefix" --timeout 120

  prefix_path="$HOME/.local/share/winux/prefixes/$prefix"
  mapfile -t installed_candidates < <(find "$prefix_path/drive_c" -type f -path '*/WinuxFixture/fixture.exe' -print)
  if [[ "${#installed_candidates[@]}" -ne 1 ]]; then
    echo "FAIL: expected one installed executable for $architecture, found ${#installed_candidates[@]}" >&2
    find "$prefix_path/drive_c" -type f -iname 'fixture.exe' -print >&2 || true
    exit 1
  fi
  installed="${installed_candidates[0]}"
  test -s "$installed"

  echo "LAUNCH: installed $architecture application"
  (
    cd "$(dirname "$installed")"
    WINEPREFIX="$prefix_path" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$installed"
  )
  test -s "$(dirname "$installed")/fixture-ran.txt"

  echo "DISCOVER: Start Menu shortcut for $architecture application"
  rm -f "$(dirname "$installed")/fixture-ran.txt"
  PREFIX_NAME="$prefix" EXPECTED_EXECUTABLE="$installed" python - <<'PY'
import os
import time
from pathlib import Path
from winux.core.applications import ApplicationManager
from winux.core.runner import ApplicationRunner

prefix = os.environ["PREFIX_NAME"]
expected = str(Path(os.environ["EXPECTED_EXECUTABLE"]).resolve())
apps = ApplicationManager().list(prefix)
matches = [
    app for app in apps
    if app.get("discovery_source") == "start_menu"
    and app.get("executable_path") == expected
]
if len(matches) != 1:
    raise SystemExit(
        f"Expected one Start Menu discovery result for {expected}, got {len(matches)}"
    )
app = matches[0]
print(f"PASS: Start Menu discovered {app['DisplayName']} ({app['registry_id']})")
result = ApplicationRunner().run(prefix, app["registry_id"])
print(f"LAUNCHED: PID {result['pid']}")
marker = Path(expected).parent / "fixture-ran.txt"
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    if marker.is_file() and marker.stat().st_size:
        print("PASS: application launched through Winux Start Menu inventory")
        break
    time.sleep(0.25)
else:
    raise SystemExit("Application did not create its marker after Start Menu launch")
PY

  echo "UNINSTALL: $architecture EXE application through Winux"
  PREFIX_NAME="$prefix" EXPECTED_EXECUTABLE="$installed" python - <<'PY'
import os
from pathlib import Path
from winux.core.applications import ApplicationManager

manager = ApplicationManager()
prefix = os.environ["PREFIX_NAME"]
expected = Path(os.environ["EXPECTED_EXECUTABLE"]).resolve()
apps = manager.list(prefix)
matches = [app for app in apps if app.get("DisplayName") == "Winux EXE Fixture"]
if len(matches) != 1:
    raise SystemExit(f"Expected one EXE uninstall record, found {len(matches)}")
manager.uninstall(prefix, matches[0]["registry_id"], timeout=120)
if expected.exists():
    raise SystemExit(f"Uninstaller left executable behind: {expected}")
remaining = [app for app in manager.list(prefix) if app.get("DisplayName") == "Winux EXE Fixture"]
if remaining:
    raise SystemExit(f"Stale EXE inventory record remains: {remaining}")
print("PASS: EXE uninstall removed files and registry inventory")
PY

  echo "PASS: Winux installed, discovered, launched and uninstalled $architecture application"
done

echo "PASS: real EXE installer workflow completed for x86 and x64 applications"
