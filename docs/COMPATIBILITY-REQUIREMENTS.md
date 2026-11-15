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
| Application inventory export | JSON/CSV export with atomic replacement and private permissions | Implemented; hosted CI pending | Preserve existing output on failure and never follow destination symlinks |

| Application execution log storage | Private per-run logs with symlink-safe creation | Implemented; directory replacement regression added, CI pending | Keep log creation anchored to a verified directory descriptor and retain restrictive permissions |
| Local browser-to-desktop bridge | Reusable LocalBridge transport and application adapters | Generic HTTP transport and security policy implemented; 292-test CI passed; application adapters pending | Add route-specific content-type/correlation support and integration tests; add EMWAT adapter only after protocol confirmation; see LOCAL-IPC-DESIGN.md |
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
5. LocalBridge: implemented reusable loopback IPC transport and policy; application-specific routes remain adapters, not hard-coded EMWAT endpoints.
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
## 2026-11-15 - State-write safety follow-up

- Process state persistence retains its private 0600 mode through the temporary
  file descriptor and avoids a path-based chmod after atomic replacement.
- Service state persistence closes the raw temporary descriptor when fdopen
  setup fails and removes the uncommitted temporary file.
- Regression tests were added; hosted CI verification is pending.

## 2026-11-15 - Descriptor ownership guarantees

- Process and service state persistence and lock acquisition now explicitly
  transfer raw descriptor ownership only after fdopen succeeds.
- Failed wrapping closes the raw descriptor; failed process state writes also
  remove their temporary file. Regression tests cover all affected paths.
- Hosted CI verification is pending.

## Prefix metadata persistence

Prefix metadata writes use a private same-directory temporary file, fsync the
file before atomic replacement, and fsync the containing directory. Descriptor
ownership is transferred only after file wrapping succeeds; failures close the
raw descriptor and remove the temporary file.


## Systemd unit-file descriptor ownership

SystemdUserBackend keeps ownership of the raw temporary unit-file descriptor
until fdopen succeeds. A wrapping failure closes the descriptor and removes
the temporary file. A regression test covers this path; hosted CI run
https://github.com/meicamghe/Winux/actions/runs/43723953513 is pending.


## Systemd unit installation transaction

SystemdUserBackend treats unit-file publication and systemd daemon-reload as
one installation transaction. If directory fsync or daemon-reload fails after
publication, it removes the incomplete unit, syncs the directory, and retries
daemon-reload when necessary. Rollback failures are surfaced explicitly.
Regression tests cover both post-publication failure points; hosted CI is
pending.


## Prefix manager log-file safety

PrefixManager opens its log file with O_NOFOLLOW, validates the opened file
using fstat, and applies private permissions through the descriptor. This
avoids following a symlink swapped between a path check and a normal file
open. Descriptor cleanup and non-regular-file rejection are regression-tested;
hosted CI is pending.


## ApplicationRunner log descriptor ownership

ApplicationRunner closes the raw log descriptor if fdopen fails after secure
relative creation in the pinned log directory. The regression test verifies
both the directory and file descriptors are closed and no incomplete log
file remains. Hosted CI is pending.


On fdopen failure, ApplicationRunner closes the file descriptor and removes
the newly created log entry relative to the still-pinned directory descriptor,
so cleanup does not re-resolve a potentially replaced parent path.


## ServiceManager state publication rollback

ServiceManager now restores the prior state-file contents if directory fsync
fails after atomic replacement, or removes the newly published file when no
prior state existed. Restoration is itself file- and directory-synced; a
rollback failure is reported alongside the original error. Regression tests
cover both cases. Hosted CI pending.

Lifecycle integration tests also verify that create removes its newly
installed backend unit when state publication fails to sync, while delete
restores the prior definition and service state.


## Service-state persistence note (2026-11-15)

The service-state JSON writer must append a real newline (`file.write("\\n")`) after serialization. A literal backslash followed by `n` would make the state file invalid JSON and break subsequent service operations. Regression coverage and CI verification should be retained for this persistence path.
