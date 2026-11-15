# Winux Application Compatibility Requirements

This document records reusable Engine requirements exposed by analysis of EMWAT and similar Windows desktop applications. It does not make EMWAT a dependency of Winux and does not claim that EMWAT currently works under Wine.

## Design rule

Application-specific behavior belongs in compatibility profiles or adapters. The Winux core should provide reusable primitives: runtime and prefix management, process supervision, local IPC, desktop application launching, diagnostics, and host integration.

## Capability matrix

| Application requirement | Generic Winux capability | Current status | Engineering direction |
|---|---|---|---|
| x86 and x64 Windows binaries | Architecture detection and WoW64 prefix support | Implemented in current design; depends on Wine build | Keep installer detection separate from prefix bitness; test real x86/x64 fixtures |
| Per-application isolation | Named Wine prefixes | Implemented | Add safe export/backup/migration before destructive lifecycle features |
| Background Windows application | Managed Linux user service wrapping Wine process | Initial implementation | Validate restart, stop, shutdown, logs, and user-session behavior |
| Genuine Windows service / SCM | Windows service control manager compatibility | Not guaranteed by Wine; not equivalent to Winux-managed service | Detect and report service dependencies; avoid implying full SCM support |
| Local browser-to-desktop bridge | Reusable LocalBridge transport and application adapters | Policy primitives implemented; HTTP transport not started | Implement bounded HTTP listener/dispatch, deadlines, concurrency, graceful shutdown, redacted diagnostics, and adapter contract; see LOCAL-IPC-DESIGN.md |
| Office document automation | Office adapter and document-session lifecycle | Not implemented in core | Keep Office-specific APIs out of prefix/process managers; support multiple office backends |
| Word COM / OLE automation | Runtime/application compatibility or native office adapter | Application-dependent; unresolved | Probe required COM interfaces and distinguish Wine support from native LibreOffice adaptation |
| Printer integration | Host print backend (CUPS/IPP) and app compatibility checks | Not integrated | Never attempt to load Windows kernel printer drivers on Linux |
| Scanner / imaging integration | Host device abstraction (SANE or supported portals) | Not integrated | Separate device discovery, capture, image processing, and document insertion |
| Crash recovery / autosave | Per-app recovery adapter and managed data lifecycle | Not implemented generically | Define recovery contracts per application; do not guess file formats or locations |

## What EMWAT analysis tells Winux

The EMWAT reverse-engineering work is useful as a demanding compatibility case because it combines a Windows background service and desktop Agent, loopback HTTP communication with a browser, Word automation and document lifecycle events, print-dialog and printer-driver integration, and recovery/autosave workflows.

These are separate capability classes. A successful Wine installation or application launch is not evidence that the complete workflow is supported.

## Required Engine boundaries

1. Runtime: runtime-specific operations such as prefix creation, launch, registry access, and uninstall.
2. PrefixManager: isolated application environments and metadata.
3. ProcessManager: identity-safe process tracking and termination.
4. ServiceManager: Linux user-service lifecycle for managed Wine applications.
5. LocalBridge: future reusable loopback IPC capability, not an EMWAT-specific endpoint hard-coded into the core.
6. OfficeAdapter: future optional integration for office document workflows.
7. HostDeviceBackend: future host printer/scanner integration.

No layer should silently assume that a Windows service, COM server, kernel driver, or proprietary device driver is supported merely because Wine is installed.

## Compatibility profile proposal

A future application profile may declare required executable architectures, minimum runtime version, Windows service names and operations, COM/OLE interfaces, local ports and IPC protocols, host devices, document formats and lifecycle events, known limitations, and verification steps.

Profiles should describe requirements and test procedures. They must not contain credentials, private document content, or opaque protocol payloads.

## Validation levels

- Installed: installer completed successfully.
- Launchable: main executable starts and remains alive.
- Workflow-tested: the application's essential user workflow passes.
- Integration-tested: host services, IPC, devices, and office integrations pass.
- Unsupported: a required kernel driver, Windows-only service, or unavailable API blocks the workflow.

Winux should expose these as distinct outcomes rather than a single compatible boolean.