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
    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine" />
    <Media Id="1" Cabinet="fixture.cab" EmbedCab="yes" />
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="@PROGRAMFILES@" Name="ProgramFiles">
        <Directory Id="INSTALLDIR" Name="WinuxMsiFixture" />
      </Directory>
    </Directory>
    <Feature Id="Complete" Title="Winux MSI Fixture" Level="1">
      <ComponentRef Id="MainComponent" />
      <ComponentRef Id="ArpComponent" />
    </Feature>
    <DirectoryRef Id="INSTALLDIR">
      <Component Id="MainComponent" Guid="*" Win64="@WIN64@">
        <File Id="FixtureExe" Source="fixture.exe" KeyPath="yes" />
      </Component>
    </DirectoryRef>
    <DirectoryRef Id="TARGETDIR">
      <Component Id="ArpComponent" Guid="*" Win64="@WIN64@">
        <RegistryKey Root="HKLM" Key="Software\Microsoft\Windows\CurrentVersion\Uninstall\[ProductCode]">
          <RegistryValue Type="string" Name="DisplayName" Value="Winux MSI Fixture" KeyPath="yes" />
          <RegistryValue Type="string" Name="Publisher" Value="Winux CI" />
          <RegistryValue Type="string" Name="InstallLocation" Value="[INSTALLDIR]" />
          <RegistryValue Type="string" Name="UninstallString" Value="msiexec.exe /x [ProductCode] /qn" />
        </RegistryKey>
      </Component>
    </DirectoryRef>
  </Product>
</Wix>
EOF

for architecture in x86 x64; do
  case "$architecture" in
    x86)
      compiler=i686-w64-mingw32-gcc
      programfiles=ProgramFilesFolder
      win64=no
      ;;
    x64)
      compiler=x86_64-w64-mingw32-gcc
      programfiles=ProgramFiles64Folder
      win64=yes
      ;;
  esac
  "$compiler" -Os -s -o "$work_dir/fixture.exe" "$work_dir/fixture.c"
  sed -e "s/@PROGRAMFILES@/$programfiles/g" \
      -e "s/@WIN64@/$win64/g" \
      "$work_dir/fixture.wxs.in" > "$work_dir/fixture.wxs"
  (cd "$work_dir" && wixl -a "$architecture" -o "fixture-$architecture.msi" fixture.wxs)
  msi="$work_dir/fixture-$architecture.msi"
  echo "MSI SUMMARY: $(msiinfo suminfo "$msi" | tr "\n" ";")"
  echo "MSI FIXTURE FILES:"
  ls -la "$work_dir"
  msiinfo suminfo "$msi" | grep -Eiq "Template.*(Intel|x64)"

  prefix="msi-$architecture"
  echo "CREATE: $architecture MSI test prefix"
  timeout --signal=TERM --kill-after=5s 120s winux prefix create "$prefix" --arch x64

  echo "INSTALL: $architecture MSI using Winux installer engine"
  if ! timeout --signal=TERM --kill-after=5s 180s winux install "$msi" --prefix "$prefix" --timeout 120; then
    echo "INSTALLATION LOGS:" >&2
    find "$HOME/.local/share/winux/logs/installations" -type f -name "*.log" -print -exec cat {} \; >&2 || true
    exit 1
  fi

  prefix_path="$HOME/.local/share/winux/prefixes/$prefix"
  mapfile -t installed_candidates < <(find "$prefix_path/drive_c" -type f -path '*/WinuxMsiFixture/fixture.exe' -print)
  if [[ "${#installed_candidates[@]}" -ne 1 ]]; then
    echo "FAIL: expected one MSI-installed executable for $architecture, found ${#installed_candidates[@]}" >&2
    find "$prefix_path/drive_c" -type f -iname 'fixture.exe' -print >&2 || true
    exit 1
  fi
  installed="${installed_candidates[0]}"
  test -s "$installed"

  echo "LAUNCH: installed MSI $architecture application"
  (
    cd "$(dirname "$installed")"
    WINEPREFIX="$prefix_path" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$installed"
  )
  test -s "$(dirname "$installed")/msi-fixture-ran.txt"
  echo "UNINSTALL: $architecture MSI application through Winux"
  PREFIX_NAME="$prefix" EXPECTED_EXECUTABLE="$installed" python - <<'PY'
import os
from pathlib import Path
from winux.core.applications import ApplicationManager

manager = ApplicationManager()
prefix = os.environ["PREFIX_NAME"]
expected = Path(os.environ["EXPECTED_EXECUTABLE"]).resolve()
apps = manager.list(prefix)
matches = [app for app in apps if app.get("DisplayName") == "Winux MSI Fixture"]
if not matches:
    print("DEBUG: complete application inventory:", apps)
    for key in ApplicationManager.UNINSTALL_KEYS:
        result = manager.runtime_manager.get().query_registry(
            manager.prefix_manager.get_path(prefix), key,
            capture_output=True, text=True, timeout=60,
        )
        print(f"DEBUG REGISTRY {key}: returncode={result.returncode}\\n{result.stdout}")
    raise SystemExit("No MSI uninstall inventory record was discovered")
commands = {
    (app.get("QuietUninstallString") or app.get("UninstallString") or "").strip()
    for app in matches
}
commands.discard("")
if len(commands) != 1:
    details = [
        {
            "registry_key": app.get("registry_key"),
            "registry_id": app.get("registry_id"),
            "UninstallString": app.get("UninstallString"),
            "QuietUninstallString": app.get("QuietUninstallString"),
        }
        for app in matches
    ]
    raise SystemExit(
        f"Expected one logical MSI uninstall command across registry views; "
        f"found {len(commands)} commands in {len(matches)} records: {details}"
    )
selected = next(
    app for app in matches
    if (app.get("QuietUninstallString") or app.get("UninstallString") or "").strip()
)
print(f"MSI inventory records: {len(matches)}; using {selected['registry_key']}")
manager.uninstall(prefix, selected["registry_id"], timeout=120)
if expected.exists():
    raise SystemExit(f"MSI uninstaller left executable behind: {expected}")
remaining = [app for app in manager.list(prefix) if app.get("DisplayName") == "Winux MSI Fixture"]
if remaining:
    raise SystemExit(f"Stale MSI inventory record remains: {remaining}")
print("PASS: MSI uninstall removed files and registry inventory")
PY
  echo "PASS: Winux installed, launched and uninstalled MSI $architecture application"
done

echo "PASS: real MSI installer workflow completed for x86 and x64 applications"
