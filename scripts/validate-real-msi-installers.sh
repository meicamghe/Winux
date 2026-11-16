#!/usr/bin/env bash
set -Eeuo pipefail

for tool in python wine wineboot wineserver timeout wixl msiinfo i686-w64-mingw32-gcc x86_64-w64-mingw32-gcc; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "MISSING: required tool '$tool' is not installed" >&2
    exit 2
  }
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/winux-msi-wow64.XXXXXX")"
export HOME="$work_dir/home"
mkdir -p "$HOME"
cleanup() {
  for name in msi-x86 msi-x64; do
    WINEPREFIX="$HOME/.local/share/winux/prefixes/$name" wineserver -k >/dev/null 2>&1 || true
  done
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

cat > "$work_dir/fixture.c" <<'EOF'
#include <stdio.h>
int main(void) {
    FILE *marker = fopen("msi-fixture-ran.txt", "w");
    if (!marker) return 10;
    fputs("Winux installed and launched this MSI application\n", marker);
    return fclose(marker) == 0 ? 0 : 11;
}
EOF

cat > "$work_dir/fixture.wxs.in" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="Winux MSI Fixture" Language="1033" Version="1.0.0" Manufacturer="Winux CI" UpgradeCode="8F0E5D6A-2C4C-4A41-A9D2-0E44F2D6A2A1">
    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine" Platform="@PLATFORM@" />
    <MediaTemplate />
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="@PROGRAMFILES@" Name="ProgramFiles">
        <Directory Id="INSTALLDIR" Name="WinuxMsiFixture" />
      </Directory>
    </Directory>
    <Feature Id="Complete" Title="Winux MSI Fixture" Level="1">
      <ComponentRef Id="MainComponent" />
    </Feature>
    <DirectoryRef Id="INSTALLDIR">
      <Component Id="MainComponent" Guid="*" Win64="@WIN64@">
        <File Id="FixtureExe" Source="fixture.exe" KeyPath="yes" />
      </Component>
    </DirectoryRef>
  </Product>
</Wix>
EOF

for architecture in x86 x64; do
  case "$architecture" in
    x86)
      compiler=i686-w64-mingw32-gcc
      platform=Intel
      programfiles=ProgramFilesFolder
      win64=no
      ;;
    x64)
      compiler=x86_64-w64-mingw32-gcc
      platform=x64
      programfiles=ProgramFiles64Folder
      win64=yes
      ;;
  esac
  "$compiler" -Os -s -o "$work_dir/fixture.exe" "$work_dir/fixture.c"
  sed -e "s/@PLATFORM@/$platform/g" \
      -e "s/@PROGRAMFILES@/$programfiles/g" \
      -e "s/@WIN64@/$win64/g" \
      "$work_dir/fixture.wxs.in" > "$work_dir/fixture.wxs"
  (cd "$work_dir" && wixl -a "$architecture" -o "fixture-$architecture.msi" fixture.wxs)
  msi="$work_dir/fixture-$architecture.msi"
  msiinfo suminfo "$msi" | grep -Eiq "Template.*(Intel|x64)"

  prefix="msi-$architecture"
  echo "CREATE: $architecture MSI test prefix"
  timeout --signal=TERM --kill-after=5s 120s winux prefix create "$prefix" --arch x64

  echo "INSTALL: $architecture MSI using Winux installer engine"
  timeout --signal=TERM --kill-after=5s 180s winux install "$msi" --prefix "$prefix" --timeout 120

  prefix_path="$HOME/.local/share/winux/prefixes/$prefix"
  installed="$prefix_path/drive_c/Program Files/WinuxMsiFixture/fixture.exe"
  if [[ "$architecture" == "x64" ]]; then
    installed="$prefix_path/drive_c/Program Files/WinuxMsiFixture/fixture.exe"
  fi
  test -s "$installed" || {
    echo "FAIL: MSI-installed executable missing for $architecture" >&2
    find "$prefix_path/drive_c" -type f -iname 'fixture.exe' -print >&2 || true
    exit 1
  }

  echo "LAUNCH: installed MSI $architecture application"
  (
    cd "$(dirname "$installed")"
    WINEPREFIX="$prefix_path" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$installed"
  )
  test -s "$(dirname "$installed")/msi-fixture-ran.txt"
  echo "PASS: Winux installed and launched MSI $architecture application"
done

echo "PASS: real MSI installer workflow completed for x86 and x64 applications"
