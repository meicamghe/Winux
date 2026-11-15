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
## 2026-11-15 - Installer and managed-service hardening

### Implemented

- Service state loading now rejects dangling symlinks rather than interpreting them as an absent state file.
- Installer timeout validation now rejects booleans, strings, NaN, infinities, zero, negative values, and integers too large for a finite timeout; only finite positive integers/floats are accepted. Validation occurs before installer inspection.
- Runtime diagnostics now report availability of msiinfo (MSI architecture inspection) and 7z (NSIS application inspection) as optional tools.
- Added regression tests for dangling service-state symlinks, invalid timeout values, and optional installer inspection tools.

### Verification status

Changes and tests were committed to main. They have not been executed in a local checkout during this session. No systemd user service was installed, enabled, started, stopped, or deleted. No installer was run.
## 2026-11-15 - Service backend failure-state handling

### Implemented

- systemctl execution now converts process-launch and timeout failures into actionable backend errors.
- Service status no longer reports "not-found" when the user systemd manager is unreachable, times out, or cannot execute. It returns "unknown" with an error detail, preventing recovery logic from confusing manager failure with a genuinely missing unit.
- `winux doctor` now probes the current user's systemd manager, not just the presence of the `systemctl` binary. An unavailable user manager is a warning because the Engine can still run applications without managed services.
- Added regression tests for manager outage, timeout, missing systemctl, process-launch failures, and diagnostic reporting.

### Verification status

Code and tests are committed to main. Tests were not executed in this assistant session. No actual systemd unit was started, stopped, enabled, disabled, or deleted.

## 2026-11-15 - Service state path and installer inspection hardening

### Implemented

- Service state reads and writes now reject symbolic links in existing parent-directory components, not only a symlink at the final JSON filename.
- State writes re-check parent path components after directory creation and reject a directory or other non-regular object at the state-file path.
- MSI architecture inspection now converts executable-launch failures into an actionable `msiinfo` error.
- NSIS listing and executable extraction now convert executable-launch failures into actionable `7z` errors.
- Added regression tests for symlinked service-state parents, non-regular state paths, and missing inspection tools at MSI/NSIS inspection stages.

### Verification status

Changes and tests are committed to main. They have not been run in a local checkout in this session. No actual service or Windows installer was launched.
## 2026-11-15 - Runtime selection and service deletion safety

### Implemented

- `RuntimeManager.get` now uses the default runtime only when the caller passes `None`; an empty runtime name is rejected rather than silently selecting Wine. `set_default` inherits the same strict behavior.
- `ServiceManager.delete` now refuses destructive operations when the backend reports an error or cannot determine active/enabled state. This prevents deleting unit files while the user service manager is unreachable.
- Added regression tests for empty runtime names and service deletion with unknown backend state.

### Verification status

Source and tests are committed to main and were reviewed after writing. They have not been executed in a local checkout in this session; no real service was modified.

## 2026-11-15 - Installer validation follow-up

### Implemented

- Batch installation now shares the exact timeout validator used by single installation, including valid finite floats and rejection of booleans, non-finite values, and oversized integers before execution.
- Installation history now rejects booleans, floats, strings, zero, and negative limits instead of treating some of them as valid integer limits.
- Added regression tests for both behaviors.

### Verification status

Changes are committed to main. The source and test additions were reviewed after writing, but the suite has not been executed in a local checkout. No installer was run.

## 2026-11-15 - Batch installer timeout consistency

### Implemented

- Centralized installer timeout validation in `Installer._validate_timeout`.
- Single and batch installation now apply the same finite-positive-number rules.
- Batch manifests accept valid positive floating-point timeouts and reject booleans, non-finite values, zero/negative values, and oversized integers before any installation starts.
- Added regression tests for valid float timeouts and invalid batch timeout values.

### Verification status

Source and tests are committed to main. They have not been executed in a local checkout in this session; no installer was run.

## 2026-11-15 - Platform-neutral service backend contract

### Implemented

- Added `core/service_contracts.py` with a runtime-checkable `ServiceBackend` Protocol, shared service ID validation, and platform-neutral restart policies.
- `ServiceManager` now validates injected backends against the shared contract and no longer depends on systemd-specific constants for service IDs or restart policy validation.
- `SystemdUserBackend` implements the shared contract while retaining its existing class constants as compatibility aliases.
- Added contract regression tests and documented the new core module in the architecture source tree.

### Architectural effect

- The service manager's lifecycle logic now has an explicit backend boundary. A future non-systemd implementation can satisfy the contract without changing service-definition and recovery logic.
- This does not add a second service backend yet; systemd user services remain the only implemented platform backend.

### Verification status

Changes and tests are committed to main. They have not been executed in a local checkout in this session.
### Follow-up

- Added an explicit conformance test for `SystemdUserBackend` as well as the fake backend.
- Removed the remaining systemd-specific service ID and restart-policy references from `ServiceManager`; it now consumes only the shared service contract. The systemd backend remains the default implementation.
- The combined commit status endpoint returned no status records for the documentation commit; this is not evidence of a passing CI run.
- Updated the architecture document to state explicitly that the protocol is a portability boundary, not proof of non-systemd support: `SystemdUserBackend` remains the only implemented backend.

## 2026-11-15 - Service backend registry

### Implemented

- Added a service-backend registry parallel to runtime discovery.
- The built-in systemd user backend is registered as the default backend.
- Third-party backends can be registered manually or discovered through the
  `winux.service_backends` Python entry-point group.
- `ServiceManager` retains direct backend injection for tests and embedding,
  while its default construction resolves the selected backend through the
  registry.
- Backend registration validates the shared `ServiceBackend` contract.
- Plugin load and registration errors are recorded as diagnostics rather than
  preventing the built-in backend from being used.

### Verification status

The implementation and regression tests have been added to the repository.
They have not yet been executed in the user's local checkout; no CI result is
available. The registry does not add a second built-in service backend.

- Follow-up review: backend instances are created lazily, so merely constructing
  the registry does not require systemctl to be installed. Plugin import errors
  and backend registration errors are recorded separately.
- Added an integration regression test for selecting a named backend through
  `ServiceManager` while retaining explicit backend injection.

## 2026-11-15 - Service backend registry refinement

### Implemented

- Added lazy backend factory instantiation and validation of the created object
  against the platform-neutral `ServiceBackend` protocol.
- Registry listings now distinguish loaded backend instances from factories
  without instantiating a backend as a side effect.
- Callable factory objects are handled safely in registry diagnostics.
- Added regression coverage for lazy creation, singleton reuse, invalid
  factory results, and callable factory-object listing.
- Added an integration test proving that `ServiceManager` can select a named
  backend from an injected registry while retaining direct backend injection.
- Updated README source-tree documentation and corrected the architecture
  document's stale reference to `platform/wine.py`.

### Verification status

Source, test, packaging metadata, and documentation were fetched again from
GitHub and inspected for the expected changes. Tests have not been executed
in a local checkout, and the repository currently reports no GitHub Actions
workflow runs. No actual systemd service was created or modified.

## 2026-11-15 - Runtime and service backend input validation

### Implemented

- Runtime and service backend selection now reject empty and non-string names
  with explicit `ValueError` messages rather than leaking dictionary-key
  `TypeError` exceptions.
- Default runtime/backend names are validated before registry membership
  checks.
- Service backend registration now distinguishes an already-instantiated
  object satisfying the protocol from a callable factory. This prevents a
  callable backend instance from being invoked accidentally.
- Registry diagnostics identify callable backend instances as loaded objects,
  not factories.
- Added regression tests for callable backend instances and malformed
  selection names.

### Verification status

The changed source and test files were fetched again from GitHub for review.
Tests have not been executed in a local checkout. No runtime, service, or
systemd operations were performed.

## 2026-11-15 - Doctor service-plugin diagnostics and runtime plugin instance handling

### Implemented

- `winux doctor` now discovers optional service-backend plugins and reports
  their load/registration failures as warnings, matching runtime plugin
  diagnostics. It does not instantiate a service backend or make systemd a
  requirement for ordinary application execution.
- Runtime diagnostics now preserve an explicitly injected manager even if it
  is falsey, rather than silently replacing it with a new manager.
- Runtime plugin discovery now recognizes an already-instantiated object
  satisfying the runtime contract before treating a callable as a factory.
  This avoids accidentally invoking callable runtime instances.
- Added a regression test for callable runtime instances and a doctor warning
  test for broken service-backend plugins.
- Expanded architecture documentation to explain the managed Linux service
  boundary and clarify that entry-point extensibility does not mean multiple
  init systems are already supported.

### Verification status

The updated source, tests, and architecture documentation were committed to
main and fetched again for inspection. Tests were not executed in a local
checkout; no GitHub Actions workflow runs were available. No actual system
service was created or changed.

## 2026-11-15 - Registry constructor and diagnostics regression coverage

### Implemented

- Added constructor-level regression tests ensuring RuntimeManager and
  ServiceBackendManager reject empty and non-string default names.
- Confirmed `winux doctor` reports service-backend plugin discovery failures
  as warnings without treating optional plugins as core runtime failures.
- Confirmed callable runtime instances are recognized as implementations,
  while runtime classes and ordinary factories remain lazily instantiated.

### Verification status

All affected GitHub files were fetched again after the updates and inspected.
The regression tests have not been executed in a local checkout. No workflow
runs are currently available for this repository.

## 2026-11-15 - Dependency injection consistency and first CI workflow

### Implemented

- Replaced truthiness-based dependency selection with explicit `is not None`
  checks in ApplicationRunner, PrefixManager, ApplicationManager, and Installer.
  Falsey but intentionally injected manager/runtime objects are no longer
  silently replaced by default instances.
- ApplicationManager's optional runtime argument now also distinguishes
  `None` from a falsey runtime object.
- Added a runner regression test that verifies falsey injected runtime and
  process managers are preserved, including propagation into PrefixManager.
- Added the first GitHub Actions workflow at
  `.github/workflows/ci.yml`. It runs the unittest suite on Ubuntu 24.04 /
  Python 3.11, builds wheel and source distributions, then installs the wheel
  into a clean virtual environment and smoke-tests the `winux --help` CLI.

### Verification status

Source and test changes were committed and are being re-fetched for review.
The CI workflow has been added but its first hosted run must complete before
any test or packaging success can be claimed. No local test execution was
performed from this session.

## 2026-11-15 - First CI failures resolved; process state hardening

### CI findings and fixes

The first hosted CI run executed 233 unit tests and exposed six pre-existing
regressions/assumption mismatches:

- Process cleanup rejected an empty `/proc/<pid>/cmdline`, which is valid
  metadata for some Linux processes. The schema now permits an empty command
  string while still requiring the field to be a string.
- Runtime empty-name tests expected the old "Unknown runtime" wording even
  though the manager intentionally rejects an empty name as invalid input.
  Assertions now match the current validation contract.
- The runtime-plugin Doctor test depended on host tools and installed entry
  points. It now isolates optional plugin discovery and systemd probes.
- The service-backend registry treated a backend class as an instantiated
  backend because runtime-checkable Protocol checks can match class-level
  methods. It now explicitly distinguishes classes/factories from instances,
  including in registry listings. A regression test covers class factories.

### Additional process state protections

- ProcessManager now rejects symlinks in existing parent path components
  during construction, reads, and writes.
- Dangling state-file symlinks are rejected before checking file existence.
- Existing state paths must be regular files, not directories or other types.
- State directories are created with restrictive 0700 permissions; temporary
  state files are created with 0600 permissions before writing.
- Added tests for symlinked parents on read/write, dangling symlinks, and
  directory paths.

### Verification

Two hosted GitHub Actions runs completed successfully after the CI fixes:
unit tests, wheel/sdist build, and clean-wheel CLI smoke test all succeeded.
The run for the latest backend-factory test commit is:
https://github.com/meicamghe/Winux/actions/runs/43717620444

The subsequent ProcessManager path-hardening changes were verified by a
separate successful hosted CI run (238 tests plus package and CLI checks),
recorded below.

## 2026-11-15 - Process state path validation CI result

The corrected process-state writer now emits valid JSON with a real trailing
newline. The hosted CI run for commit `33532ba` completed successfully:
238 unit tests passed, wheel and source distribution built, and the installed
wheel's `winux --help` smoke test succeeded.

ProcessManager now checks parent path components for symlinks on construction,
read, and write; rejects dangling state-file symlinks and non-regular state
paths; and uses restrictive directory/file permissions. Tests cover parent
symlink read/write, dangling symlinks, and directory-as-state-file cases.

A further ServiceManager boundary fix rejects backend classes passed as if
they were instances and preserves explicitly injected falsey prefix and
application managers. Its hosted CI run subsequently passed, as recorded in
the next section.

## 2026-11-15 - ServiceManager boundary and injection CI result

- ServiceManager now rejects a backend class passed as an instance; classes
  are factories and must be instantiated before satisfying the Protocol.
- ServiceManager preserves explicitly injected falsey PrefixManager and
  ApplicationManager objects instead of replacing them with defaults.
- Added regression tests for both behaviors.
- Latest hosted run for commit `1674df2` passed all 240 unit tests, built
  wheel and source distribution, installed the wheel into a clean virtual
  environment, and passed the `winux --help` smoke test:
  https://github.com/meicamghe/Winux/actions/runs/43717899761

## 2026-11-15 - Runner lifecycle consolidation and packaged service validation

### Implemented

- Added an installed-wheel smoke check for `winux.service_runner` to the CI
  workflow. This verifies that the internal module used by generated systemd
  service commands is actually present and importable from the built wheel.
- Consolidated the duplicated prefix/runtime/application/executable
  resolution and validation logic in `ApplicationRunner` into
  `_resolve_application()`. Both detached and foreground launch paths now
  share the same runtime availability, executable existence, and prefix
  containment checks.
- Added ProcessManager lifecycle coverage for force-stopping a process that
  explicitly ignores SIGTERM, and for cleaning up a process record after the
  process exits normally.

### Hosted verification

- CI run `43718280601` passed for the packaged service-runner import smoke
  check:
  https://github.com/meicamghe/Winux/actions/runs/43718280601
- CI run `43718294457` passed after the ApplicationRunner validation
  consolidation:
  https://github.com/meicamghe/Winux/actions/runs/43718294457
- CI run `43718317782` passed with the additional ProcessManager lifecycle
  tests:
  https://github.com/meicamghe/Winux/actions/runs/43718317782
- Each successful run completed the unit-test, wheel/sdist build, and clean
  installed-wheel smoke-test steps. The latest run also imported
  `winux.service_runner` from the installed wheel.
- No local test execution was performed; verification is from hosted CI.

### Next engineering tracks

1. Continue ProcessManager/ApplicationRunner lifecycle review, including
   process-registration failure and shutdown/restart behavior.
2. Continue ServiceManager rollback and systemd runner lifecycle review.
3. Design the generic loopback IPC subsystem as a Winux Engine capability
   before implementing any EMWAT-specific endpoint or payload handling.
4. Keep Office automation, printing, and recovery behind optional adapters;
   do not claim compatibility until workflow-level integration tests exist.

## 2026-11-15 - Service rollback safety and LocalBridge architecture

### Service lifecycle hardening

- Service deletion now refuses to proceed when the backend omits or reports
  unknown active/enabled state.
- Service rollback now verifies that the restored unit's active and enabled
  states are knowable before deciding whether to start/stop or enable/disable
  it. Unknown state is reported as incomplete rollback rather than being
  silently interpreted as inactive/disabled.
- Added regression coverage for missing lifecycle state and unknown state
  during rollback.
- Hosted CI run `43718552322` passed after these changes, including the full
  unit-test suite, wheel/sdist build, and installed-wheel smoke test:
  https://github.com/meicamghe/Winux/actions/runs/43718552322

### Local IPC architecture

- Added `docs/LOCAL-IPC-DESIGN.md` defining a generic loopback bridge boundary
  for browser-to-desktop communication.
- The design specifies loopback-only binding, exact Host/Origin validation,
  authentication hooks, request size/time/concurrency limits, safe logging,
  and bounded shutdown.
- Updated `docs/COMPATIBILITY-REQUIREMENTS.md` and
  `docs/architecture.md` to link this design.
- This is a specification, not an implementation. EMWAT's init/invoke payload
  schema and browser security policy remain unknown; no application-specific
  endpoints or semantics have been invented.

### Current next steps

1. Review remaining ProcessManager/ApplicationRunner races and process
   shutdown behavior.
2. Continue ServiceManager/systemd lifecycle and rollback edge-case tests.
3. Implement LocalBridge only against the documented generic contract, with
   the security test matrix as acceptance criteria.
4. Keep EMWAT-specific protocol decoding, Office automation, printing, and
   recovery as adapters/integration work, not responsibilities of Winux core.

## 2026-11-15 - Application log hardening and 246-test CI verification

### Implemented

- ApplicationRunner now rejects symlink components in its log directory,
  creates the app-runs directory with 0700 permissions, and enforces private
  directory permissions.
- Log files are created exclusively with 0600 permissions and no-follow
  semantics. An existing path, including a symlink, is never opened for
  append.
- Added tests for symlinked log directories, pre-existing log-file symlinks,
  and restrictive directory/file permissions.
- The first two CI attempts exposed a test-fixture setup issue: the test tried
  to recreate an already existing parent directory. The fixture was corrected
  to use exist_ok=True and the latest run passed.

### Verification

- Hosted CI run `43718714658` completed successfully:
  - 246 unit tests passed.
  - Wheel and source distribution built.
  - The installed wheel passed the CLI smoke test and the packaged
    `winux.service_runner` import check.
- Run:
  https://github.com/meicamghe/Winux/actions/runs/43718714658

### Current engineering focus

Continue process/log lifecycle review, service rollback safety, and the
LocalBridge implementation plan. LocalBridge remains a design specification
until the transport and security test matrix can be implemented without
inventing EMWAT-specific protocol behavior.

## 2026-11-15 - Process registration recovery and concurrent state safety

### Application lifecycle

- ApplicationRunner no longer leaves a newly launched process unmanaged when
  ProcessManager registration fails. It sends SIGTERM through the Popen handle,
  waits up to five seconds, then escalates to kill if the process does not exit.
- If cleanup itself fails, the raised error reports both the registration and
  cleanup failures, including the process ID.
- Added tests for normal termination and forced termination after timeout.

### Process state concurrency

- ProcessManager now serializes register and cleanup read/modify/write cycles
  with an advisory flock on a dedicated per-state-file lock.
- Lock files are created with 0600 permissions, opened with no-follow
  semantics where supported, and rejected if they are symlinks or non-regular
  files.
- Added concurrent registration coverage using six independent managers
  sharing the same state file. The test verifies that no process records are
  lost and that lock permissions remain private.

### Hosted verification

- Source-only lifecycle cleanup commit CI:
  https://github.com/meicamghe/Winux/actions/runs/43718979468
- Combined lifecycle and concurrency-test commit CI:
  https://github.com/meicamghe/Winux/actions/runs/43718982396
- Latest run passed **249 unit tests**, wheel/sdist packaging, installed-wheel
  CLI smoke test, and service-runner import check.
- These changes were verified by hosted CI; no local test execution was
  performed.

### Next

1. Review cross-process locking and cleanup behavior for crash consistency.
2. Continue ServiceManager state-file concurrency review.
3. Start the LocalBridge transport implementation as a generic Engine
   subsystem, retaining strict loopback/Origin/Host/authentication boundaries.
4. Keep Office automation, printer integration, and EMWAT payload decoding
   outside the transport core.

## 2026-11-15 - Service definition concurrency hardening

- ServiceManager now serializes service create/delete operations with a
  per-state-file advisory lock, preventing two concurrent creators from both
  passing the duplicate-name check and installing duplicate services.
- Lock files are created with 0600 permissions, no-follow semantics where
  supported, and symlink/non-regular-file rejection.
- Added regression tests for concurrent duplicate service creation and
  symlinked service lock files.
- Hosted CI run `43719099119` passed **251 unit tests**, wheel/sdist builds,
  installed-wheel CLI smoke test, and service-runner import check:
  https://github.com/meicamghe/Winux/actions/runs/43719099119
- ProcessManager's analogous registration/cleanup lock and the runner's
  unregistered-process cleanup are also covered by the combined 249-test run:
  https://github.com/meicamghe/Winux/actions/runs/43718982396

### Follow-on engineering

1. Review the lock protocol across processes and state-file recovery after
   interrupted writes.
2. Factor shared state-locking mechanics only if doing so preserves the
   security guarantees and avoids needless abstraction.
3. Begin the generic LocalBridge transport and its security tests as a Winux
   Engine capability.

## 2026-11-15 - LocalBridge security policy primitives

### Implemented

- Added `src/winux/core/local_bridge.py` with reusable policy primitives:
  - numeric IPv4/IPv6 loopback-only bind validation;
  - exact normalized HTTP(S) Origin allowlists;
  - exact loopback Host and listener-port validation;
  - explicit policy for requests without Origin;
  - optional per-session token comparison using constant-time comparison;
  - strict Content-Length parsing and maximum-body-size enforcement;
  - validation for positive finite request timeouts and concurrency limits.
- Added `tests/test_local_bridge.py` covering invalid bind addresses, Origin
  confusion, Host mismatches, IPv6 authorities, authentication, and body-size
  limits.
- Updated LocalBridge and compatibility documentation to distinguish
  implemented policy primitives from the not-yet-implemented HTTP transport.
- ServiceManager now also serializes create/delete operations using a private
  per-state-file lock, preventing concurrent duplicate service creation.

### Verification

- CI run `43719219780` passed for the LocalBridge source module:
  https://github.com/meicamghe/Winux/actions/runs/43719219780
- CI run `43719222360` passed with **263 unit tests**, packaging, and installed
  wheel smoke checks:
  https://github.com/meicamghe/Winux/actions/runs/43719222360
- The 263-test run includes ServiceManager concurrent-create and lock-symlink
  tests, plus LocalBridge policy tests.
- HTTP listener, request dispatch, concurrency enforcement, request deadlines,
  graceful shutdown, and EMWAT-specific protocol handling are still pending.

### Next engineering steps

1. Implement the LocalBridge HTTP transport against these policy primitives.
2. Test request dispatch, body reads, timeout behavior, concurrency limits,
   and graceful shutdown before connecting any application adapter.
3. Continue crash-consistency review for process/service state writes.
4. Keep Word automation and printing as separate host adapters.

## 2026-11-15 - LocalBridge HTTP transport implementation

### Implemented

- Added `src/winux/platform/local_bridge.py` as the generic HTTP/1.1
  transport, reusing the existing `LocalBridgePolicy` rather than duplicating
  policy validation.
- Added explicit method/path route registration and immutable request /
  response data objects. There is no generic arbitrary-command endpoint.
- Enforced the exact bound loopback IP and port in Host validation, exact
  normalized Origin allowlists, optional Bearer token authentication, bounded
  Content-Length, and rejection of Transfer-Encoding.
- Added route-aware CORS preflight. Preflight does not require the actual
  request's Bearer token; actual requests still do.
- Bounded concurrency before creating handler threads, applied socket
  timeouts, disabled request-line logging, rejected response-header
  line-break injection, and hid handler exception details from clients.
- Shutdown now stops accepting requests and waits for in-flight handlers
  within the supplied deadline. It returns false if handlers have not drained,
  allowing the caller to retry shutdown.
- Added HTTP-level tests for route dispatch, Host/Origin checks, CORS,
  authentication, body limits, unsupported transfer encoding, preflight,
  response-header injection, concurrency, port conflicts, and shutdown.

### Hosted verification

- CI run `43719798103` passed **281 unit tests**, wheel/sdist packaging,
  installed-wheel CLI smoke test, and `winux.service_runner` import check:
  https://github.com/meicamghe/Winux/actions/runs/43719798103
- Earlier implementation attempts exposed a syntax error, CORS preflight
  header filtering, and a flaky raw-socket timeout assertion. These were
  corrected or removed; the final hosted run passed.
- No local test execution was performed.

### Remaining work

1. Add route-specific Content-Type schemas and correlation IDs if needed by
   adapters.
2. Exercise IPv6 listener behavior in hosted CI.
3. Build a small generic sample adapter and integration harness.
4. Implement EMWAT routes only after its request schema and authentication
   requirements are confirmed; current capture evidence is insufficient.

## 2026-11-15 - Generic LocalBridge transport implemented

### Engine capability

- The generic HTTP transport lives in src/winux/platform/local_bridge.py;
  security policy remains in src/winux/core/local_bridge.py. This keeps
  transport mechanics separate from application-specific route semantics.
- The transport supports explicit method/path routes, IPv4/IPv6 loopback
  listeners, Host and Origin validation, optional Bearer authentication,
  route-aware CORS preflight, bounded request bodies, rejected transfer
  encodings, socket timeouts, and bounded concurrent handlers.
- Response headers are validated, handler exceptions return generic errors,
  request-line logging is disabled to avoid leaking query parameters, and
  shutdown stops accepting work and waits for active requests within a
  configured deadline.
- Added tests for active-request draining and rejection when the concurrency
  limit is reached.
- The LocalBridge design, compatibility matrix, and architecture docs now
  distinguish the implemented generic transport from the not-yet-built
  EMWAT-specific adapter.

### Verification

- Hosted CI run 43719816658 passed **283 unit tests**, wheel/sdist builds,
  installed-wheel CLI smoke test, and service-runner import:
  https://github.com/meicamghe/Winux/actions/runs/43719816658
- The transport implementation and documentation are committed. No EMWAT
  payload schema or route behavior has been guessed.

### Next engineering work

1. Deepen LocalBridge tests for slow-client body timeouts, duplicate headers,
   and shutdown deadline behavior under load.
2. Define a small application-adapter contract and an example health adapter.
3. Keep EMWAT init/invoke, Word automation, printing, and recovery in separate
   adapters after their contracts are verified.
4. Continue Engine state persistence crash-consistency review.

## 2026-11-15 - LocalBridge IPv6 and packaged-module verification

- Added an IPv6 loopback HTTP listener integration test (skipped only if the
  host has no IPv6 loopback support).
- Extended the installed-wheel smoke test to import both
  `winux.platform.local_bridge` and `winux.core.local_bridge`, in addition to
  the service runner.
- Latest CI run `43719933763` passed **284 unit tests**, wheel/sdist builds,
  CLI smoke test, and all three installed-module imports:
  https://github.com/meicamghe/Winux/actions/runs/43719933763
- The first raw-socket timeout test was nondeterministic in the hosted runner
  and was removed; socket timeouts remain configured in the transport, while
  the suite verifies bounded shutdown and concurrency behavior directly.

## 2026-11-15 - LocalBridge slow-client and malformed-header coverage

- Added integration tests proving that duplicate Content-Length headers are
  rejected and slow/incomplete request bodies time out rather than reaching
  application routes.
- Added active-request shutdown-drain and concurrency-limit tests alongside
  existing route, Host/Origin, authentication, CORS, and response-header tests.
- Hosted CI run 43720058573 passed **286 unit tests**, wheel/sdist packaging,
  installed-wheel CLI smoke test, and service-runner import:
  https://github.com/meicamghe/Winux/actions/runs/43720058573
- The initial raw-socket test needed to read the full HTTP response rather
  than a single TCP chunk; the test was corrected and the complete suite now
  passes.

## 2026-11-15 - Service lifecycle serialization

- Serialized ServiceManager list/get/start/stop/restart/enable/disable
  operations with the same per-state-file advisory lock already used by
  create/delete. This prevents lifecycle actions from racing with service
  removal or definition creation.
- Kept the service runner's `get_definition` lookup lock-free: it reads the
  atomically replaced JSON file, avoiding a deadlock where systemd stop waits
  for a service runner that is blocked on the manager's lock.
- Added a regression test proving a start operation waits while another
  manager instance holds the state lock.
- Hosted CI run `43720095250` passed **287 unit tests**, wheel/sdist builds,
  installed-wheel CLI smoke test, and LocalBridge module imports:
  https://github.com/meicamghe/Winux/actions/runs/43720095250

## 2026-11-15 - Durable process and service state writes

- ProcessManager and ServiceManager now fsync the parent directory after
  atomically replacing their JSON state files. The temporary file itself is
  fsynced before replace, and state files retain restrictive permissions.
- Added tests that verify both the state-file and parent-directory fsync calls.
- Hosted CI passed:
  - Process state fsync: 287 tests
    https://github.com/meicamghe/Winux/actions/runs/43720212575
  - Service state fsync: 289 tests
    https://github.com/meicamghe/Winux/actions/runs/43720221901
- These checks improve crash durability of state updates; they do not replace
  the need for recovery tests against abrupt power loss or filesystem faults.

## 2026-11-15 - LocalBridge correlation and diagnostic redaction

- Added a random 32-character request ID to each accepted HTTP request.
  Adapters receive it on `LocalBridgeRequest.request_id`, and responses carry
  `X-Winux-Request-ID`.
- Structured diagnostics record request ID, method, path, status, and elapsed
  time. Query strings and request bodies are not logged.
- Changed adapter exception logging to omit exception messages and tracebacks,
  preventing accidental disclosure of document text or credentials embedded
  in exception messages. Clients receive only a generic 500 response.
- Added a test verifying that a secret exception message is absent from both
  the HTTP response and captured logs.
- Hosted CI run `43720531599` passed **290 unit tests**, packaging, installed
  CLI smoke test, and imports of the packaged bridge and service-runner
  modules:
  https://github.com/meicamghe/Winux/actions/runs/43720531599

## 2026-11-15 - Atomic prefix metadata persistence

- PrefixManager now writes `.winux-prefix.json` through a temporary file
  created inside the prefix directory with mode 0600.
- The temporary file is flushed and fsynced, atomically renamed into place,
  and the prefix directory is fsynced so the metadata rename is durable.
- Existing or symlinked metadata paths are refused rather than overwritten.
- Added tests for private metadata permissions, a real trailing newline, and
  refusing an existing metadata symlink without modifying its target.
- Hosted CI run `43720800367` passed **291 unit tests**, wheel/sdist builds,
  and installed-wheel CLI and module-import smoke tests:
  https://github.com/meicamghe/Winux/actions/runs/43720800367

## 2026-11-15 - Service state FIFO protection

- ServiceManager now checks that an existing state path is a regular file
  before reading it. This prevents a FIFO or other special file from blocking
  the process during state loading.
- Added a regression test that creates a FIFO at the service-state path and
  verifies it is rejected without attempting to read from it.
- Hosted CI run `43720913671` passed **292 unit tests**, wheel/sdist builds,
  installed-wheel CLI smoke test, and LocalBridge/service-runner import checks:
  https://github.com/meicamghe/Winux/actions/runs/43720913671

## 2026-11-15 - Prefix storage and process registration validation

### Implemented

- PrefixManager now rejects symbolic links in existing components of its
  prefix and log storage paths instead of resolving through them silently.
- Prefix storage is revalidated before create, list, and prefix lookup, so
  replacing the storage root with a symlink after manager construction is
  rejected as well.
- Prefix log-file symlinks are rejected during logger initialization.
- Prefix architecture normalization now rejects non-string input with a
  controlled ValueError instead of leaking a TypeError.
- ProcessManager.register now requires a positive integer PID and non-empty
  application, prefix, runtime, and executable strings. Optional log paths
  must also be non-empty strings when supplied.
- Invalid process metadata is rejected before process inspection or state
  persistence, preventing malformed registrations from making the complete
  process-state file unreadable.
- Added regression tests for each boundary and synchronized the architecture
  source tree with the LocalBridge modules.

### Hosted verification

- GitHub Actions run
  https://github.com/meicamghe/Winux/actions/runs/43721576182
  completed the 299-test unit suite, wheel and source-distribution builds,
  and installed-wheel CLI smoke test successfully.
- Verification is from hosted GitHub Actions; no test suite was run in the
  user's local Linux checkout.

## 2026-11-15 - Private prefix storage

### Implemented

- Prefix and log storage directories are now restricted to mode 0700.
- The prefix-manager log file is restricted to mode 0600.
- Prefix log-file symlinks are rejected even when a logger handler already
  exists, preventing logger reuse from bypassing the path check.
- Added tests for private directory/file permissions and symlinked log files.
- Updated the architecture documentation to record these storage guarantees.

### Hosted verification

- GitHub Actions run
  https://github.com/meicamghe/Winux/actions/runs/43721692997
  passed all 301 unit tests, built the wheel and source distribution, and
  passed the installed-wheel CLI smoke test.
- Verification is from hosted GitHub Actions, not a local checkout.

## 2026-11-15 - Installer storage hardening

### Implemented

- Installer data, installation-log, and lock directories now reject symbolic
  links in existing path components and are restricted to mode 0700.
- Installation logs are created exclusively with mode 0600 and without
  following symbolic links.
- Per-prefix lock files are opened without truncation or following symbolic
  links, checked to be regular files, and restricted to mode 0600.
- Installer storage directories are revalidated before installation and
  history access, including after manager construction.
- Installation history ignores symbolic-link and non-regular log entries.
- Added regression tests for directory replacement, lock-file symlinks,
  history symlinks, and private file/directory permissions.
- Updated the architecture documentation with these guarantees.

### Hosted verification

- GitHub Actions run
  https://github.com/meicamghe/Winux/actions/runs/43721861376
  passed all 305 unit tests, wheel and source-distribution builds, and the
  installed-wheel CLI smoke test.
- Verification is from hosted GitHub Actions, not a local checkout.

## 2026-11-15 - Wine prefix drive C and registry path containment

### Implemented

- Prefix lookup and listing now reject prefixes whose `drive_c` entry is
  missing, not a directory, or a symbolic link.
- Prefix creation validates that the runtime produced a real `drive_c`
  directory before writing metadata; invalid prefixes are rolled back.
- Registry-derived Windows paths are accepted only when they are absolute
  paths on drive C.
- Converted paths are resolved and constrained to the real prefix
  `drive_c`; parent traversal, drive-relative paths, and symlinked drive
  roots are rejected.
- Updated PrefixManager, ApplicationManager, installer test fixtures, and
  architecture documentation with regression coverage.

### Hosted verification

- GitHub Actions run
  https://github.com/meicamghe/Winux/actions/runs/43722246971
  passed all 311 unit tests, wheel and source-distribution builds, and the
  installed-wheel CLI smoke test.
- Verification is from hosted GitHub Actions, not a local checkout.

## 2026-11-15 - Application uninstall input validation

### Implemented

- Application uninstall timeout validation now rejects booleans, strings,
  zero/negative values, NaN, infinities, and integers too large for a finite
  timeout before looking up or invoking an uninstaller.
- Uninstall commands must be non-empty strings before parsing and execution.
- Added regression tests proving invalid inputs do not reach application
  lookup or Wine execution.
- Updated the architecture documentation.

### Hosted verification

- GitHub Actions run
  https://github.com/meicamghe/Winux/actions/runs/43722350679
  passed all 313 unit tests, wheel and source-distribution builds, and the
  installed-wheel CLI smoke test.
- Verification is from hosted GitHub Actions, not a local checkout.

## 2026-11-15 - Application log directory replacement protection

- ApplicationRunner now revalidates the log directory's path components each
  time it creates a run log, not only during manager construction.
- Log creation opens the parent directory with directory/no-follow flags and
  creates the file relative to that pinned directory descriptor. This blocks
  a replaced final log-directory symlink from redirecting log creation.
- Added a regression test that replaces the log directory with a symlink
  after runner construction and verifies that no file is created outside
  Winux and the Windows application is not launched.
- Hosted CI run is pending for this change; do not count this regression as
  passing until the workflow completes.

## 2026-11-15 - Atomic application inventory exports

- Application inventory JSON and CSV exports are now written to a private
  temporary file in the destination directory, flushed and fsynced, then
  atomically replaced into place.
- The export file is created with mode 0600. A destination symlink is replaced
  as a directory entry rather than followed, so its target remains untouched.
- Failed serialization leaves any existing destination unchanged and removes
  the temporary file.
- Added regression tests for symlink destinations, private permissions, and
  write-failure preservation.
- Hosted CI verification is pending.

## 2026-11-15 - Process and service state-write hardening

- Process state writes no longer call path-based chmod after atomic replacement.
  The temporary file already receives mode 0600 through its open descriptor;
  avoiding chmod(path) prevents following a destination swapped to a symlink.
- Service state writes now close the raw temporary-file descriptor if wrapping
  it with fdopen fails, while still removing the temporary file.
- Added regression tests for both conditions.
- Hosted CI verification for these latest changes is pending.
