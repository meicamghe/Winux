# Wine upstream integration policy

## Purpose

Wine is Winux's compatibility implementation, not a component that Winux should
reimplement. Winux owns the user-facing lifecycle: runtime discovery, prefix
isolation, installer orchestration, application inventory, process management,
desktop integration, diagnostics, and optional host adapters. Wine owns the
Windows API implementation and PE loader.

Upstream references:

- [Wine source repository](https://gitlab.winehq.org/wine/wine)
- [WineHQ documentation](https://gitlab.winehq.org/wine/wine/-/wikis/Documentation)
- [Wine 11.0 release notes](https://list.winehq.org/hyperkitty/list/wine-releases%40list.winehq.org/message/UL6L2GJ55VYUJ5KUMBZ3TZSXRFJ52QG6/)
- [WineHQ current releases](https://www.winehq.org/)

## Architecture policy

- Keep Wine behind the `Runtime` interface. Core application, prefix, and
  installer code must not call Wine-specific subprocesses directly.
- Keep one isolated prefix per application or deliberately shared application
  group. Never reuse the user's default `~/.wine` implicitly.
- Detect the Windows executable/installer architecture independently from the
  prefix architecture.
- Winux creates 64-bit WoW64 prefixes and targets both x86 and x64 Windows
  applications in the same prefix, subject to the installed Wine build.
- Set `WINEARCH` only when initializing a new prefix. Do not leak a shell's
  inherited `WINEARCH` into ordinary run, install, registry, or uninstall
  operations.
- Always set an explicit absolute `WINEPREFIX` for every managed operation.
- Use Wine's own tools for their intended responsibilities: `wine` for PE
  execution and registry operations, `wineboot` for prefix initialization,
  `msiexec` for MSI packages, and `wineserver` for Wine process lifecycle.
- Do not assume a successful installer exit proves that the installed
  application or its business workflow works.

## WoW64 and version policy

Wine 11.0 (January 2026) marks the new WoW64 mode as fully supported and
documents feature parity with the old mode. Wine 11.0 also documents that
pure 32-bit prefixes (`WINEARCH=win32`) are deprecated and are not supported
by the new WoW64 mode. Winux's 64-bit-prefix strategy is therefore aligned
with the upstream direction.

Builds without the new WoW64 mode may expose different behavior, including
experimental-mode messages. Winux must report the installed Wine version and
validate actual runtime behavior rather than assuming that every distribution
package has identical capabilities.

Policy:

1. Do not hard-fail solely because a runtime differs from the validated
   baseline; report the version and the relevant compatibility caveat.
2. Use WineHQ Stable 11.0, package version `11.0.0.0~noble-1`, as the only
   CI and integration validation baseline.
3. Keep x86 and x64 executable smoke tests in real-Wine CI.
4. Test installer formats and application workflows separately from PE loader
   smoke tests.
5. Never silently convert or recreate an existing prefix to change its
   architecture or WoW64 mode.

## Compatibility boundaries

Wine provides Windows API compatibility, not a complete Windows kernel.
Winux must keep these outcomes distinct:

- **Installed:** the installer returned an accepted exit status.
- **Launchable:** the target executable starts successfully.
- **Workflow-tested:** the application's essential workflow was exercised.
- **Integration-tested:** external dependencies such as COM/OLE, local IPC,
  printing, scanners, or services were exercised.
- **Unsupported/blocked:** a required Windows kernel driver, unavailable
  service behavior, or unsupported API prevents the workflow.

In particular, a Winux-managed Linux user service is not the Windows Service
Control Manager. Wine COM/OLE support must be tested per interface and
application; it is not proof of Microsoft Word automation compatibility.
Windows printer kernel drivers must not be loaded into Linux. Host printing
belongs behind a Linux-native backend and an application-specific adapter.

## Current Winux implementation mapping

| Wine responsibility | Winux integration |
|---|---|
| PE application execution | `WineRuntime.run()` via `wine` |
| EXE installer execution | `WineRuntime.install()` via `wine` |
| MSI installation | `WineRuntime.install()` via `msiexec /i` |
| Prefix initialization | `WineRuntime.create_prefix()` via `wineboot --init` |
| Prefix isolation | Explicit `WINEPREFIX` environment |
| Registry inventory | `WineRuntime.query_registry()` |
| Uninstall command execution | `WineRuntime.uninstall()` |
| Process lifecycle | Winux process/service managers plus Wine's `wineserver` |

## Continuous integration coverage

The repository now has dedicated CI coverage for:

- The distribution-provided Wine runtime, including x86 and x64 PE execution
  smoke tests in 64-bit WoW64 prefixes.
- Official WineHQ Stable packages on Ubuntu 24.04, pinned and checked against
  exact package version `11.0.0.0~noble-1`, with real x86/x64 EXE and MSI
  installer fixtures.
- EXE and MSI installation and launch workflows, with uninstall lifecycle
  checks being validated separately from basic install success.
- Application inventory status, including explicit detection of registered
  executables that are missing from the prefix.

A green installer job proves only the tested fixture's behavior on that CI
runtime. It does not establish compatibility for arbitrary Windows installers
or applications. In particular, registry-based uninstall discovery can differ
between x86 and x64 MSI packages and must be tested rather than assumed.

## Remaining validation work

- Record Wine version and relevant package/runtime details in CI artifacts.
- Complete and stabilize MSI uninstall registration checks for both package
  architectures; a successful MSI install does not guarantee a usable
  Add/Remove Programs entry.
- Keep application-specific COM/OLE, Windows service, and printer tests out of
  generic runtime smoke tests; give each a separate compatibility fixture.
- Revisit this policy when Wine upstream changes WoW64, prefix, or service
  behavior.

This document describes integration policy. It does not claim that all listed
Wine capabilities are implemented or that arbitrary Windows applications
work under Wine.
