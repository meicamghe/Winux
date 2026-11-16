# Winux

**A Linux compatibility platform for running Windows applications.**

Winux is an open-source project that aims to make running Windows applications on Linux easier through an integrated compatibility engine, application management, and desktop integration.

## Project Vision

The long-term goal of Winux is to provide a Linux distribution with a familiar and accessible experience for users coming from Windows.

Winux is being developed in three major layers:

1. **Winux Engine** – Windows application installation, execution, and management.
2. **Winux Desktop** – A graphical interface for discovering, installing, and managing applications.
3. **Winux OS** – A bootable and installable Linux distribution with Winux integrated.

## Current Status

**Development stage: Alpha**

The current project focuses on the Winux Engine.

Implemented capabilities include:

- Wine environment detection.
- Expanded read-only runtime diagnostics through `winux doctor`, including MSI/NSIS inspection tools.
- Windows prefix creation and management.
- EXE and MSI installer support, including explicit argument forwarding for silent or customized installs.
- Windows application discovery through registry information, including logical MSI deduplication by Windows Installer ProductCode across registry views.
- MSI inventory retains all contributing registry IDs, registry keys, and uninstall command variants; non-MSI entries are not merged by display name.
- Application information retrieval.
- Launching installed Windows applications, including forwarding command-line arguments safely.
- Installation and execution logging.
- Linux desktop-entry integration.
- Validated Windows Start Menu shortcut discovery through a conservative Shell Link parser.
- x86 and x64 application execution in a real Wine WoW64 prefix, verified in hosted CI.
- Real NSIS EXE installer integration in hosted CI, including installation, Start Menu discovery, and launch through the Winux application runner.
- Real x86/x64 EXE and MSI install-discover-launch-uninstall lifecycle validation on distro Wine and WineHQ Stable 11.

Both x86 and x64 Windows applications are considered in the compatibility design.

Actual application compatibility depends on Wine, application requirements, and the Linux environment.


## Project Maturity Map

Winux is being developed in six maturity areas. The percentages below are
**indicative engineering estimates**, not automated coverage metrics, release
readiness scores, or guarantees that arbitrary Windows applications will work.
They summarize the current repository state and the remaining work.

| Area | Estimated maturity | Current position |
|---|---:|---|
| **Engine foundation** | **90%** | Core runtime abstraction, Wine integration, prefix lifecycle, diagnostics, and platform boundaries are in place. More runtime implementations and broader distribution validation remain. |
| **Application lifecycle** | **80%** | EXE/MSI installation, application discovery, launch, uninstall safeguards, inventory audit, process handling, managed services, and desktop-entry integration exist. Backup/restore, migration, and broader end-to-end lifecycle coverage remain. |
| **Compatibility and reliability** | **65%** | Automated tests, x86/x64 WoW64 smoke validation, and selected real-installer integration tests exist. Application-specific workflows, COM/OLE, Office automation, genuine Windows services, printing, and recovery still need dedicated validation or adapters. |
| **Linux distribution portability** | **30%** | Runtime and service backend boundaries are being separated from platform-specific implementations. Multiple distro/package-manager backends and a repeatable cross-distro test matrix remain. |
| **Winux Desktop** | **0%** | Product direction and UI scope are identified; the graphical application manager and settings interface have not been implemented. |
| **Winux OS** | **0%** | The installable image/distribution is a later stage and has not been started. |

### Development sequence

1. **Harden the Engine** — complete lifecycle safety, runtime selection, diagnostics,
   and reproducible x86/x64 installer and launch validation.
2. **Prove portability** — implement and test platform backends across multiple
   Linux distributions before depending on one distro's package manager.
3. **Build Winux Desktop** — add the graphical application manager and settings
   interface on top of stable Engine APIs.
4. **Package Winux OS** — create the bootable image and installer only after the
   Engine and Desktop are dependable.

**Current focus: Engine reliability and cross-distribution portability.**
The Desktop and OS stages are intentionally deferred; their 0% values mean
implementation has not started, not that they are abandoned.


## Architecture

```text
Winux
├── Engine
│   ├── Installer
│   ├── Prefix Manager
│   ├── Application Manager
│   ├── Application Runner
│   └── Desktop Integration
│
├── Desktop
│   ├── Application Manager UI
│   ├── Installer UI
│   └── System Settings
│
└── Operating System
    ├── Linux Base
    ├── Desktop Environment
    └── Winux Integration
```

## Requirements

Current development environment:

- Linux
- Python 3
- Wine
- Git

Additional dependencies may be required depending on the Linux distribution and application being installed.

## Development Setup

Clone the repository:

```bash
git clone https://github.com/meicamghe/Winux.git
cd Winux
```

Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Wine and verify the environment:

```bash
wine --version
```

Run Winux from the source directory:

```bash
PYTHONPATH=src python3 -m winux --help
```

Check the system:

```bash
PYTHONPATH=src python3 -m winux doctor
```

## Project Structure

```text
Winux/
├── src/winux/
│   ├── __main__.py
│   ├── service_runner.py
│   ├── core/
│   │   ├── applications.py
│   │   ├── desktop.py
│   │   ├── installer.py
│   │   ├── local_bridge.py
│   │   ├── prefix.py
│   │   ├── runner.py
│   │   ├── processes.py
│   │   ├── services.py
│   │   └── service_contracts.py
│   ├── platform/
│   │   ├── local_bridge.py
│   │   ├── runtime.py
│   │   ├── service_backend.py
│   │   └── service_backends.py
│   └── runtime/
│       ├── base.py
│       ├── manager.py
│       └── wine.py
├── tests/
├── docs/
├── pyproject.toml
└── README.md
```

## Roadmap

The following milestones represent the planned development direction:

- [x] Initial Winux Engine source structure
- [x] Basic EXE and MSI installation workflow
- [x] Prefix management
- [x] Installed application discovery
- [x] Application execution
- [x] Generic loopback IPC transport and security policy
- [ ] EMWAT-specific IPC adapter after protocol confirmation
- [ ] Office automation and host printing adapters
- [ ] Improved desktop integration
- [x] Automated testing framework and GitHub Actions CI
- [ ] Graphical application manager
- [ ] System settings and configuration interface
- [ ] Winux OS image and installer

- [Application compatibility requirements and EMWAT-derived Engine gaps](docs/COMPATIBILITY-REQUIREMENTS.md)
- [Wine upstream integration policy and compatibility boundaries](docs/WINE-INTEGRATION.md)

## Compatibility

Winux uses Wine as its current Windows compatibility layer.

Not every Windows application is guaranteed to work. Applications that require Windows kernel drivers, unsupported services, or specialized hardware integration may need alternative solutions.

## Contributing

Contributions, bug reports, ideas, and technical discussions are welcome.

The project is currently in an early development stage, and its architecture may evolve.

## License

License has not yet been selected.

## Session continuity

For the current project decisions, implementation boundaries, and next-session checklist, see [docs/SESSION-HANDOFF.md](docs/SESSION-HANDOFF.md).

## Local Browser-to-Desktop IPC

Winux now includes a generic loopback HTTP transport with explicit routes,
strict Host and Origin validation, optional Bearer-token authentication,
bounded request bodies and concurrency, correlation IDs, and controlled
shutdown.

The transport is an Engine capability, not an EMWAT-specific implementation.
Application-specific request schemas and document workflows belong in
adapters. See [docs/LOCAL-IPC-DESIGN.md](docs/LOCAL-IPC-DESIGN.md) for the API,
security boundaries, test coverage, and remaining integration work.

## Managed Services and Process Management

Winux includes an initial managed-service subsystem for running Windows
applications in the background through Wine.

Implemented capabilities:
- Create and manage Winux service definitions.
- Start, stop, restart, enable, disable, and delete managed services.
- systemd user-service backend.
- Configurable restart policies: `no`, `on-failure`, and `always`.
- Foreground service runner for systemd lifecycle management.
- Process listing, inspection, stopping, and cleanup.
- Service metadata stored separately from systemd unit files.

Creating a service does not automatically start or enable it.
Enabling a service configures it for the user's systemd session.

**Important:** Winux managed services are Linux services that launch Windows
applications through Wine. This does not mean that Windows Service Control
Manager services are fully supported by Wine.

The service subsystem is an initial implementation. Actual compatibility
with specific Windows services and applications must be tested separately.


## Launching Applications with Arguments

Pass document paths or other application arguments after the application ID, using
`--` to separate Winux options from arguments intended for the Windows program:

```bash
winux app run --prefix office ExampleApp -- "C:\\Users\\Public\\Documents\\report.docx" /readonly
```

Arguments are passed as individual process arguments without shell expansion.
Winux rejects non-string values and NUL characters before starting the process.


## Installer Arguments

Winux can pass explicit arguments to an EXE or MSI installer without invoking a shell.
Repeat `--installer-arg` to preserve argument order:

```bash
winux install setup.exe --prefix office --installer-arg /S --installer-arg '/D=C:\\Apps\\Office'
winux install package.msi --prefix office --installer-arg /qn --installer-arg /norestart
```

Batch installation manifests may define an `installer_args` string array for each application:

```json
{
  "applications": [
    {"file": "setup.exe", "installer_args": ["/S"]},
    {"file": "package.msi", "installer_args": ["/qn", "/norestart"]}
  ]
}
```

Installer switches are vendor-specific; Winux forwards them unchanged and does not guess silent-install options.
