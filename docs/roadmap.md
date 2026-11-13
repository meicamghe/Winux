# Winux Roadmap

This roadmap describes the planned evolution of Winux from its current early Engine implementation into a complete desktop experience and, eventually, an installable Linux distribution.

Milestones are capability goals, not release-date promises. A milestone is complete only when its acceptance criteria are met and documented.

## Current status

**Current phase: Engine foundation (Alpha)**

The repository already contains an initial CLI-driven engine with Wine checks, named prefix management, EXE/MSI installation workflows, installed-application discovery, application launching, and installation/run logging.

Desktop launcher integration has been started, but still needs hardening and testing. A graphical desktop manager and a bootable Winux OS image are future work.

## Milestone 0.1 — Reliable Engine foundation

**Goal:** Make the core engine predictable, testable, and safe to operate.

- [x] Establish the Python package and CLI entry point.
- [x] Add Wine availability/version diagnostics.
- [x] Implement named Wine prefix creation, listing, inspection, and deletion.
- [x] Add initial EXE/MSI installation workflows.
- [x] Discover installed applications from prefix registry data.
- [x] Launch discovered applications through Wine.
- [x] Record installation and application-run logs.
- [ ] Add automated unit tests for core modules.
- [ ] Standardize error types, CLI exit codes, and diagnostic output.
- [ ] Validate destructive operations and improve recovery from interrupted installs.
- [ ] Document supported host dependencies and known limitations.

**Acceptance criteria**

- Core commands behave consistently on a clean supported Linux installation.
- Invalid prefixes and application paths fail safely with actionable errors.
- Tests cover normal operation and common failure cases.
- Logs identify the operation, target prefix, and failure details without exposing secrets.

## Milestone 0.5 — Application lifecycle

**Goal:** Make installing, discovering, launching, and removing Windows applications a coherent workflow.

- [ ] Improve EXE/MSI metadata and architecture inspection.
- [ ] Test x86 and x64 Windows applications in supported 64-bit WoW64 prefixes.
- [ ] Improve executable discovery when registry metadata is incomplete.
- [ ] Add application uninstall and repair workflows where technically feasible.
- [ ] Track application-to-prefix relationships and installation history reliably.
- [ ] Complete desktop launcher integration, including trust, duplicate handling, and refresh.
- [ ] Test behavior on the supported desktop environments.
- [ ] Add end-to-end tests using redistributable test applications.

**Acceptance criteria**

- A user can install a supported application, find it in Winux, launch it, and remove it using documented commands.
- Architecture decisions and compatibility limitations are visible to the user.
- Desktop launchers do not create uncontrolled duplicate entries.
- Failed operations provide logs and clear recovery guidance.

## Milestone 0.8 — Winux Desktop

**Goal:** Provide a graphical interface backed by the same Engine services.

- [ ] Define stable engine interfaces independent of the CLI.
- [ ] Select and document the GUI technology.
- [ ] Build an application library showing installed Windows applications.
- [ ] Add GUI workflows for installing EXE/MSI files.
- [ ] Add launch, uninstall, and application-details views.
- [ ] Add prefix management and runtime settings.
- [ ] Surface diagnostics and logs in the GUI.
- [ ] Add accessibility, localization, and usability testing.

**Acceptance criteria**

- Common application-management tasks can be completed without a terminal.
- The GUI uses Engine services instead of duplicating Wine logic.
- GUI state remains consistent with the underlying prefixes and installed applications.

## Milestone 1.0 — Installable Winux OS

**Goal:** Deliver a reproducible, bootable, installable Winux distribution.

- [ ] Choose and document the Linux base distribution and release strategy.
- [ ] Choose the supported desktop environment and display stack.
- [ ] Define system requirements, partitioning, boot, and installation approach.
- [ ] Integrate Winux Engine and Winux Desktop into the system image.
- [ ] Define update, security, and package-management policies.
- [ ] Create a reproducible ISO build pipeline.
- [ ] Test installation in virtual machines and on selected physical hardware.
- [ ] Publish release notes, checksums, known issues, and recovery instructions.

**Acceptance criteria**

- The ISO boots and installs on the documented supported hardware/VM configurations.
- A fresh installation includes a working Engine and Desktop.
- Updates and recovery procedures are documented and tested.
- The release has a clear support matrix and known-compatibility statement.

## Quality gates for every milestone

- **Correctness:** automated tests and reproducible manual test cases.
- **Compatibility:** explicitly document the tested Linux, Wine, and application versions.
- **Security:** never execute installers as root by default; validate paths and avoid unsafe shell construction.
- **Reliability:** preserve logs and handle failed or interrupted operations safely.
- **Documentation:** update architecture, installation, usage, and troubleshooting docs with each meaningful change.

## Compatibility policy

Winux aims to support both x86 and x64 Windows applications through compatible Wine configurations. This is not a promise that every Windows application will run. Applications that depend on Windows kernel drivers, unsupported services, anti-cheat systems, or specialized hardware may remain incompatible.

## Immediate next priorities

1. Add automated tests around prefix management and application discovery.
2. Review and harden the installer and runner error paths.
3. Finish desktop launcher integration and test it on the current GNOME environment.
4. Define the Engine interface that the future GUI will consume.
