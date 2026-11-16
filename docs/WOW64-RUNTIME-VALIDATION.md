# Real Wine/WoW64 architecture smoke test

This test complements the fast unit-test architecture matrix. It actually creates
one 64-bit Wine prefix, compiles tiny Windows PE32 and PE32+ executables, and
runs both executables in that same prefix.

## Requirements

- A Wine build with working WoW64 support
- `wineboot`, `wineserver`, and `timeout`
- `i686-w64-mingw32-gcc` and `x86_64-w64-mingw32-gcc`

On Debian/Ubuntu, the cross-compilers are provided by the `gcc-mingw-w64-i686`
and `gcc-mingw-w64-x86-64` packages. Wine package names and 32-bit support
vary by distribution and repository configuration.

## Run

From the repository root:

```bash
chmod +x scripts/validate-wine-wow64.sh
./scripts/validate-wine-wow64.sh
```

The script uses a temporary prefix and removes it on exit. It does not touch
the user's normal Winux prefixes. A successful result proves that the selected
Wine build can initialize a win64 prefix and execute both x86 and x64 smoke
binaries. It does not prove compatibility with arbitrary Windows applications,
installers, services, COM/OLE, printers, or application-specific workflows.

A timeout or nonzero exit is reported as a failure for the affected architecture.
Do not treat a green unit-test matrix as a substitute for this real runtime test.

## Automated real-runtime CI

The repository CI now includes a dedicated Ubuntu 24.04 job that installs
Wine with both the 64-bit and 32-bit runtime packages and the two MinGW
cross-compilers, then runs this script automatically. This is separate from
the fast Python architecture matrix: the job creates a real win64 prefix and
launches actual PE32 and PE32+ binaries.

Verified result on 2026-11-16:

- Workflow run 291: all jobs passed, including
  `test-real-wine-wow64`, `test-wow64-matrix (x86)`,
  `test-wow64-matrix (x64)`, and package/CLI smoke tests.
- Run: https://github.com/meicamghe/Winux/actions/runs/43813840549

This proves that the tested Ubuntu runner's installed Wine configuration can
run both minimal executable architectures in one win64 prefix. It does not
prove that any particular third-party application or installer is compatible.
