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
