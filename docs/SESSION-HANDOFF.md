# Winux — Project Handoff

Last reviewed: 2026-11-15

This file is the compact continuity record for future development sessions. It complements the README and architecture documents; it does not replace source code, tests, or detailed design records.

## Product direction

Winux is being built in stages:

1. **Winux Engine:** a reusable engine that should work across supported Linux distributions.
2. **Winux Desktop:** a graphical application manager built on top of the same engine.
3. **Winux OS:** a later installable Linux distribution integrating the engine and desktop.

The user's explicit near-term priority is to build the engine first so it can run on different Linux distributions. Do not jump prematurely into building a custom distribution or spending time on the GUI before the engine is dependable.

## Binding architecture decisions

- Support both 32-bit (x86) and 64-bit (x64) Windows applications/installers. A previous 64-bit-only restriction was superseded.
- Use Wine as the current compatibility layer; actual compatibility remains application- and environment-dependent.
- Detect installer/application architecture instead of assuming one architecture.
- Keep installation, prefix management, application discovery, execution, platform integration, and desktop integration separated.
- Use per-application or named Wine prefixes and keep runtime data under the user's Linux data directory.
- The engine should be distribution-aware only where necessary; avoid hard-coding one distro's package manager or filesystem assumptions.
- Do not run ordinary Windows applications as root.
- A successful installer exit is not proof that the installed application works.

## Current repository baseline

Repository: https://github.com/meicamghe/Winux

The README and `docs/architecture.md` describe an early Engine implementation. Reported capabilities include:

- Wine environment detection
- Prefix creation and management
- EXE/MSI installation workflow
- Installed application discovery through Wine registry data
- Application metadata lookup
- Launching installed applications
- Installation and execution logs
- Basic desktop shortcut integration

Current CLI examples documented in the repository:

```bash
PYTHONPATH=src python3 -m winux --help
PYTHONPATH=src python3 -m winux doctor
```

The architecture document describes commands for prefix lifecycle, install, history/stats, and app list/info/run. Verify actual CLI behavior against source and tests before claiming any feature is complete.

## Development priorities

1. Inspect the current source and test suite before changing implementation.
2. Stabilize Wine detection and dependency checks across multiple Linux distributions.
3. Verify prefix creation, validation, lifecycle and architecture behavior.
4. Test EXE and MSI installers for both x86 and x64 using supported Wine/WoW64 configurations.
5. Improve application discovery and executable resolution.
6. Finish robust desktop launcher integration and test multiple desktop environments.
7. Establish automated tests and repeatable CI for supported Linux distributions.
8. Define a stable engine interface before building the GUI.
9. Only after the engine is stable, develop Winux Desktop and then the OS image.

## Important compatibility constraints

- WoW64 behavior depends on the installed Wine build and distro packaging. Do not assume all 32-bit applications will work merely because architecture detection succeeds.
- Kernel drivers, Windows-only services, specialized hardware and unsupported APIs may prevent an application from working.
- Avoid destructive prefix deletion or migration without explicit user-visible safeguards.
- Keep logs useful while avoiding credentials and sensitive application data.

## Session start checklist

At the start of each new development session:

1. Read this file, `README.md`, and `docs/architecture.md`.
2. Inspect Git status, latest commit, current branch and uncommitted changes in the user's working copy when available.
3. Run the existing test suite before edits.
4. Compare the latest code with the claims in documentation.
5. Continue from the highest-priority incomplete item; do not redo completed analysis without new evidence.
6. Update this handoff and relevant technical docs whenever a decision, interface, behavior, or milestone changes.

## Known continuity gap

Older project chats may contain implementation details, terminal outputs, and user test observations not reproduced here. This document consolidates the durable decisions currently recoverable; it is not a claim that every historical message has been archived. When a historical detail conflicts with this file, prefer the latest explicit user decision and record the resolution here.

## 2026-11-14 - Managed Services Implementation

### Implemented

- Added `ServiceManager` for managed-service definitions and lifecycle actions.
- Added a systemd user-service backend.
- Added a foreground service runner.
- Added CLI commands:
  `service create`, `list`, `status`, `start`, `stop`, `restart`,
  `enable`, `disable`, and `delete`.
- Added service metadata persistence and validation.
- Added service and service-runner tests.
- Kept Winux-managed Linux services distinct from genuine Windows services.

### Verification baseline

Latest verified test result: 176 tests passed.
The 49 service-specific tests also passed.
`compileall` and `git diff --check` passed.

The version 0.5.0 wheel built successfully and was verified to contain
the service manager, systemd backend, and service runner modules.
The wheel was installed into an isolated temporary virtual environment.
The installed CLI help commands and imports for all service modules passed.

No real managed service was started or enabled during these checks.

### Important limitations and next steps

- Do not assume that genuine Windows services work under Wine.
- Do not launch Windows applications or services as root.
- Do not enable or run real services as part of documentation verification.
- Test service creation, unit generation, lifecycle handling, and failure
  recovery with isolated fixtures.
- Review source-checkout and installed-package behavior of the service runner.
- Keep documentation synchronized with implementation and tests.

## 2026-11-15 - Engine diagnostics and application compatibility boundaries

### Implemented in this session

- Expanded winux doctor from a Wine-only check to a read-only diagnostic report.
- It now reports host architecture, Wine availability/version, wineboot as a required prefix-initialization tool, and msiexec, wineserver, and winepath as optional capabilities.
- Runtime plugin discovery errors are reported as warnings instead of being hidden.
- Added isolated tests for successful checks, missing required tools, missing optional tools, runtime failures, and plugin warnings.

### Architecture direction reinforced

- Winux remains the primary product. EMWAT is a compatibility case study, not a separate core or mandatory dependency.
- Added a reusable application capability matrix covering x86/x64, prefixes, managed services, local IPC, office automation, printers, scanners, and recovery.
- Do not equate Winux-managed Linux user services with genuine Windows Service Control Manager support.
- Do not equate successful installation or launch with workflow compatibility.

### Verification status

The source and tests were committed to GitHub. The doctor CLI now exits with status 1 when required runtime diagnostics fail; CLI regression tests cover both failure and success. The new test suite has not yet been executed in the user's Linux working copy; do not report it as passing until it is run. No real Wine prefix or Windows application was created or launched during this documentation/code update.
## 2026-11-15 - Prefix and process-state hardening

### Implemented

- Prefix metadata is now validated against its directory name and supported architecture.
- Prefix metadata format versions are checked; unsupported versions are rejected.
- Legacy metadata that predates explicit name/architecture fields remains readable using the historical win64 WoW64 default.
- Dangling metadata symlinks are rejected instead of being mistaken for legacy prefixes.
- Persisted process records now validate required fields, UUID-like IDs, positive non-boolean PIDs, non-negative UIDs, numeric Linux process start times, and field types before status or signal operations.
- Added regression tests for each of these validation cases.
- Updated README and architecture source trees to match the current runtime, process, service, and service-runner modules.

### Verification status

These changes and tests are committed to the main repository. They have not been executed in a local checkout in this session; do not mark them as passing until the complete test suite is run. No live processes were signaled and no Wine prefixes were created or deleted during this update.