# Winux Architecture

## 1. Purpose

Winux is a Linux-based compatibility platform intended to make installing, managing, and launching Windows desktop applications straightforward for Linux users.

The project is developed in stages. The current codebase is an early **Engine** implementation. The desktop environment and installable operating-system image described below are future targets, not existing features.

## 2. Architectural principles

- Keep Windows application compatibility behind a dedicated engine layer.
- Isolate applications in named Wine prefixes.
- Keep installation, application discovery, execution, and desktop integration as separate responsibilities.
- Prefer Linux-native user data locations for Winux-managed state.
- Record useful installation and execution logs for troubleshooting.
- Detect application and installer architecture rather than assuming every installer has the same architecture.
- Treat Wine compatibility as application-dependent; Winux cannot guarantee that every Windows program will run.

## 3. Current source layout

```text
src/winux/
├── __init__.py
├── __main__.py
├── core/
│   ├── __init__.py
│   ├── installer.py
│   ├── prefix.py
│   ├── applications.py
│   ├── runner.py
│   └── desktop.py
├── platform/
│   ├── __init__.py
│   └── wine.py
└── runtime/
    └── __init__.py
```

### CLI entry point — `__main__.py`

The command-line interface exposes the current engine workflows, including:

- `doctor`
- `prefix create/list/delete/info`
- `install`
- `history` and `stats`
- `app list/info/run`

The CLI is the current user-facing entry point. A graphical interface is a later milestone.

### Wine platform check — `platform/wine.py`

This layer checks whether Wine is available and reports its version. It is the starting point for isolating Wine-specific platform detection and behavior from the higher-level engine.

### Prefix manager — `core/prefix.py`

The prefix manager creates and manages named Wine prefixes. Prefixes are stored under:

```text
~/.local/share/winux/prefixes/
```

It provides operations to create, list, inspect, and delete prefixes, and validates that a selected prefix is a usable Wine prefix.

The current design uses 64-bit Wine prefixes. Both 32-bit and 64-bit Windows applications are intended to be supported through Wine's WoW64 capabilities where the installed Wine build supports them. This does not mean Winux creates a separate pure 32-bit prefix for every 32-bit application.

### Installer — `core/installer.py`

The installer handles Windows installer files, currently EXE and MSI. Its responsibilities include installer processing, architecture detection, selecting a target prefix, coordinating installation, and recording installation logs.

Installation data and lock files are kept under Winux's user data directory, including:

```text
~/.local/share/winux/logs/installations/
~/.local/share/winux/locks/
```

Installer success and application compatibility are different things: a successful installer exit does not guarantee that the installed application will work correctly.

### Application manager — `core/applications.py`

The application manager discovers installed applications by reading Windows uninstall registry information inside a prefix. It exposes application metadata such as display name, version, publisher, registry identifier, executable path, and installation path when available.

### Application runner — `core/runner.py`

The runner locates an application's executable in its prefix, validates that the path belongs to that prefix, sets `WINEPREFIX`, and launches the application through Wine. It also records execution logs under:

```text
~/.local/share/winux/logs/app-runs/
```

### Desktop integration — `core/desktop.py`

A desktop manager has been started to integrate Wine-generated desktop launchers with the user's desktop. This area is still being developed and needs further testing for duplicate entries, missing desktop utilities, launcher trust, and different desktop environments.

## 4. Runtime data layout

Winux-managed runtime data is stored in the user's data directory rather than in the source tree:

```text
~/.local/share/winux/
├── prefixes/
├── logs/
│   ├── installations/
│   └── app-runs/
└── locks/
```

This keeps application environments and logs separate from the project source and Python development environment.

## 5. Application lifecycle

The intended engine workflow is:

1. Check that Wine and required host tools are available.
2. Create or select a named Wine prefix.
3. Inspect the installer and determine its type and architecture.
4. Run the installer with the selected prefix.
5. Discover the installed application from the prefix's registry.
6. Launch the application through the runner.
7. Integrate available Wine-generated launchers with the Linux desktop.
8. Keep logs available for troubleshooting.

Some steps are implemented in the current engine; desktop integration and end-to-end lifecycle handling remain areas for continued testing and refinement.

## 6. Architecture support

Winux aims to handle both x86 and x64 Windows applications. Actual support depends on the installed Wine build, its WoW64 configuration, application dependencies, and any Windows-specific features required by the application.

Applications that require Windows kernel drivers, unsupported services, special hardware access, or other unavailable Windows components may not work under Wine.

## 7. Target architecture

The longer-term product is organized into three layers:

### Winux Engine

The compatibility and application-management foundation:

- Wine detection and configuration
- Prefix lifecycle management
- EXE/MSI installation
- Application discovery and metadata
- Application execution
- Logs and diagnostics
- Linux desktop launcher integration

### Winux Desktop

A future graphical experience built on top of the engine:

- Application installer and manager
- Installed Windows application library
- Prefix and runtime settings
- Launch, repair, and removal workflows
- User-friendly diagnostics

The desktop must call engine services rather than reimplementing Wine and prefix operations independently.

### Winux OS

A future bootable and installable Linux distribution:

- A selected Linux base
- A supported desktop environment
- Winux Engine preinstalled and configured
- Winux Desktop integrated into the user experience
- A reproducible build and ISO-generation process

The OS layer should consume the same engine and desktop components used during development, rather than becoming a separate implementation.

## 8. Development priorities

1. Stabilize prefix creation, validation, and lifecycle operations.
2. Improve EXE/MSI inspection and installation reliability.
3. Strengthen application discovery and executable resolution.
4. Complete and test desktop launcher integration.
5. Add automated tests and documented troubleshooting.
6. Define stable interfaces between the engine and a future GUI.
7. Build the graphical application manager.
8. Select the Linux base and establish a reproducible OS image build.

## 9. Compatibility and security considerations

- Run applications as the logged-in user; do not run ordinary Windows applications as root.
- Validate paths before launching or deleting files within a prefix.
- Do not store credentials, access tokens, or private installer data in the repository.
- Treat installers and application files as untrusted input.
- Preserve logs without recording secrets unnecessarily.
- Make destructive prefix deletion explicit and clearly identify the selected prefix.
- Document Wine and host dependency requirements.

## 10. Documentation status

This document describes the current source structure and the intended direction of the project. It should be updated when module responsibilities, runtime paths, supported workflows, or the product architecture change.

## Managed Services and Process Management

### Winux Managed Services

Winux Managed Services provide lifecycle management for Windows applications
running through Wine in the background.

The current implementation includes:
- `ServiceManager` in `winux/core/services.py`.
- `SystemdUserBackend` in `winux/platform/service_backend.py`.
- Internal foreground entry point in `winux/service_runner.py`.
- CLI commands for create, list, status, start, stop, restart, enable,
  disable, and delete.
- Configurable restart policies: `no`, `on-failure`, and `always`.

Service definitions are stored in the Winux user data directory.
systemd user units are stored under `~/.config/systemd/user/`.
The service manager and backend do not require root privileges.

Service creation installs a unit and stores its definition. It does not
automatically start or enable the service. Starting and enabling are separate
operations.

The systemd user manager controls the lifecycle of the foreground runner.
The runner launches the configured Windows application through Wine.
Winux's general ProcessManager remains a separate facility for processes
launched through the normal application-run workflow.

### Windows Service Compatibility

Winux Managed Services must not be confused with Windows services.
A Winux-managed service is a Linux user service that launches a Windows
application. Running a genuine Windows service that depends on Windows
Service Control Manager APIs is a separate compatibility problem and is
not guaranteed by the current implementation.

### Security and Reliability

- Windows applications must never be launched as root.
- Service definitions and unit files are written using atomic file updates.
- Service IDs and service commands are validated.
- systemd is invoked without a shell.
- Service lifecycle errors must not be silently ignored.
- Actual service execution must be tested separately from unit creation.
