# Winux Roadmap

This roadmap tracks the evolution of Winux from its current command-line engine into a desktop experience and, eventually, an installable Linux distribution.

Milestones are capability-based rather than date-based. A milestone is complete only when its acceptance criteria are implemented, tested, and documented.

## Current status

**Stage:** Alpha — Engine foundation

The current codebase includes:

- CLI entry point and diagnostic command.
- Wine availability check.
- Windows prefix creation, listing, inspection, and deletion.
- EXE/MSI installation workflow with architecture detection, locking, and installation logs.
- Installed-application discovery through Windows uninstall registry entries and validated Windows Start Menu shortcuts.
- Application information lookup and launching.
- Linux desktop-entry integration work.
- Real x86/x64 Wine WoW64 smoke validation and NSIS EXE install/discover/launch integration in hosted CI.

The current design uses 64-bit Wine prefixes with WoW64 to support both 32-bit (x86) and 64-bit (x64) Windows applications. Actual compatibility depends on Wine, the application, and required Windows components. Separate pure 32-bit prefix creation is not a current requirement.

## Milestones

### 0.1 — Engine foundation

**Goal:** Make the core engine predictable and safe to use.

- [x] Establish Python package and CLI structure.
- [x] Detect Wine and report its version.
- [x] Create and manage Wine prefixes.
- [x] Store Winux runtime data under the user's local data directory.
- [ ] Define stable error types and consistent CLI exit codes.
- [ ] Add automated unit tests for path validation and prefix management.
- [ ] Document supported Linux and Wine prerequisites.

**Exit criteria:** Core prefix operations have automated tests and failures produce clear, actionable diagnostics.

### 0.5 — Application lifecycle

**Goal:** Install, discover, inspect, and launch Windows applications through Winux.

- [x] Install EXE and MSI packages.
- [x] Detect installer and application architecture where possible.
- [x] Record installation logs and identifiers.
- [x] Discover installed applications from prefix registry data.
- [x] Discover and launch applications through validated Windows Start Menu shortcuts.
- [x] Display application details.
- [x] Launch an installed application in its associated prefix.
- [ ] Add an application manifest/database for Winux-managed installations.
- [ ] Improve uninstall and repair workflows.
- [ ] Add integration tests using redistributable test applications.
- [ ] Make desktop shortcut/menu integration reliable and idempotent.

**Exit criteria:** A user can install, list, inspect, launch, and uninstall a supported test application using documented CLI commands, with test coverage and useful logs.

### 0.6 — Reliability and compatibility

**Goal:** Improve diagnostics and make application behavior easier to troubleshoot.

- [x] Validate EXE/MSI signatures and installer architecture metadata before installation.
- [ ] Detect common missing Wine dependencies and explain them.
- [ ] Capture process exit status and structured launch diagnostics.
- [ ] Add per-application environment and launch settings.
- [ ] Handle duplicate application names and shortcut collisions.
- [x] Test x86 and x64 PE executables in one real WoW64 prefix in hosted CI.
- [x] Test real x86/x64 NSIS EXE installation, Start Menu discovery, and launch through Winux in hosted CI.
- [ ] Document known limitations, including drivers, kernel components, and Windows services.

**Exit criteria:** Common installation and launch failures are diagnosable, and supported architecture behavior is covered by repeatable tests.

### 0.8 — Winux Desktop

**Goal:** Provide a graphical interface for everyday application management.

- [ ] Select and document a GUI toolkit and desktop integration approach.
- [ ] Create an application library with install, launch, and uninstall actions.
- [ ] Add prefix management screens.
- [ ] Add installation progress and log viewing.
- [ ] Add application settings and per-app configuration.
- [ ] Integrate with the Linux application menu and desktop environment.
- [ ] Keep GUI operations backed by the same tested Engine APIs.

**Exit criteria:** A user can perform the main application lifecycle tasks without using the terminal.

### 0.9 — System integration

**Goal:** Prepare Winux components for packaging and system-wide installation.

- [ ] Define package layout, configuration locations, and upgrade behavior.
- [ ] Add system checks and dependency handling.
- [ ] Create reproducible build and test workflows.
- [ ] Define logging, backup, and recovery behavior.
- [ ] Test installation and upgrades in clean virtual machines.

**Exit criteria:** Winux can be installed and upgraded repeatably on a documented Linux base system.

### 1.0 — Installable Winux OS

**Goal:** Deliver a bootable and installable Winux image.

- [ ] Choose and document the Linux base distribution.
- [ ] Define desktop environment, default applications, and system settings.
- [ ] Integrate the Winux Engine and Desktop.
- [ ] Build a bootable amd64 ISO.
- [ ] Test live boot and installation in virtual machines.
- [ ] Test first boot, updates, recovery, and removal/rollback strategy.
- [ ] Publish release notes, checksums, and installation documentation.

**Exit criteria:** A clean virtual machine can boot the ISO, install Winux, complete first boot, and install and launch a supported Windows application.

## Engineering rules

1. Keep the Engine independent of the GUI. The CLI and future GUI should call the same core APIs.
2. Do not promise universal Windows application compatibility. Validate each supported scenario and document limitations.
3. Support x86 and x64 Windows applications through the selected WoW64 strategy; verify behavior with tests.
4. Never commit Wine prefixes, virtual environments, installers, logs, credentials, or user application data.
5. Prefer small, reviewable commits and update documentation when behavior or CLI commands change.
6. Mark a task complete only after implementation and verification, not merely because a design has been proposed.

## Quality gates for every milestone

- **Correctness:** automated tests and reproducible manual test cases.
- **Compatibility:** document the tested Linux, Wine, and application versions.
- **Security:** do not run installers as root by default; validate paths and avoid unsafe shell construction.
- **Reliability:** preserve useful logs and handle failed or interrupted operations safely.
- **Documentation:** update architecture, installation, usage, and troubleshooting docs with meaningful changes.

## Immediate next priorities

1. Add automated tests around prefix management and application discovery.
2. Review and harden installer and runner error paths.
3. Finish desktop launcher integration and test it on the current GNOME environment.
4. Define the stable Engine interface that the future GUI will consume.
