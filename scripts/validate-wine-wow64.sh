#!/usr/bin/env bash
set -Eeuo pipefail

for tool in wine wineboot wineserver timeout i686-w64-mingw32-gcc x86_64-w64-mingw32-gcc; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "MISSING: required tool '$tool' is not installed" >&2
    exit 2
  }
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/winux-wow64-smoke.XXXXXX")"
prefix="$work_dir/prefix"
cleanup() {
  WINEPREFIX="$prefix" wineserver -k >/dev/null 2>&1 || true
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
echo "Prefix: $prefix (win64 WoW64)"
WINEPREFIX="$prefix" WINEARCH=win64 WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 90s wineboot --init

# Record the real Wine-created drive-link layout for the prefix backup design.
# This is diagnostic evidence only: never follow or archive these links here.
echo "Wine prefix dosdevices layout:"
dosdevices="$prefix/dosdevices"
if [[ -d "$dosdevices" && ! -L "$dosdevices" ]]; then
  while IFS= read -r -d '' link; do
    printf '  %s -> %s\n' "${link#"$dosdevices"/}" "$(readlink -- "$link")"
  done < <(find "$dosdevices" -mindepth 1 -maxdepth 1 -type l -print0 | sort -z)
  for drive in 'c:' 'z:'; do
    if [[ -L "$dosdevices/$drive" ]]; then
      printf '  expected-drive %s: symlink target=%s resolved=%s\n' \
        "$drive" "$(readlink -- "$dosdevices/$drive")" "$(readlink -f -- "$dosdevices/$drive")"
    else
      printf '  expected-drive %s: not a symlink\n' "$drive"
    fi
  done
else
  echo "  dosdevices directory missing or is a symlink"
fi

for architecture in x86 x64; do
  executable="$work_dir/smoke-$architecture.exe"
  echo "RUN: $architecture Windows executable"
  if WINEPREFIX="$prefix" WINEDEBUG=-all timeout --signal=TERM --kill-after=5s 45s wine "$executable"; then
    echo "PASS: $architecture executable launched and exited successfully"
  else
    status=$?
    echo "FAIL: $architecture executable returned status $status" >&2
    exit "$status"
  fi
done

echo "PASS: both PE32 (x86) and PE32+ (x64) smoke executables ran in one win64 prefix"
