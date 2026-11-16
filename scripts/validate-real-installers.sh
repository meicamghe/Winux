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
InstallDir "$PROGRAMFILES\\WinuxFixture"
RequestExecutionLevel user
Section "Install"
  SetOutPath "$INSTDIR"
  File "fixture.exe"
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
  installed="$prefix_path/drive_c/Program Files/WinuxFixture/fixture.exe"
  test -s "$installed" || {
    echo "FAIL: installed executable missing for $architecture" >&2
    find "$prefix_path/drive_c" -maxdepth 5 -type f -iname '*.exe' -print >&2 || true
    exit 1
  }

  echo "LAUNCH: installed $architecture application"
  (
    cd "$(dirname "$installed")"
    WINEPREFIX="$prefix_path" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$installed"
  )
  test -s "$(dirname "$installed")/fixture-ran.txt"
  echo "PASS: Winux installed and launched $architecture application"
done

echo "PASS: real EXE installer workflow completed for x86 and x64 applications"
