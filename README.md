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
- EXE and MSI installer support.
- Windows application discovery through registry information.
- Application information retrieval.
- Launching installed Windows applications.
- Installation and execution logging.
- Basic desktop shortcut integration.

Both x86 and x64 Windows applications are considered in the compatibility design.

Actual application compatibility depends on Wine, application requirements, and the Linux environment.

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
│   │   ├── prefix.py
│   │   ├── runner.py
│   │   ├── processes.py
│   │   ├── services.py
│   │   └── service_contracts.py
│   ├── platform/
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
- [ ] Improved desktop integration
- [ ] Automated testing framework
- [ ] Graphical application manager
- [ ] System settings and configuration interface
- [ ] Winux OS image and installer

- [Application compatibility requirements and EMWAT-derived Engine gaps](docs/COMPATIBILITY-REQUIREMENTS.md)

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
