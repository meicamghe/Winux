# Prefix Backup / Restore — Implementation Status

**Status date:** 2026-11-17  
**Canonical security contract:** [PREFIX-BACKUP-RESTORE-DESIGN.md](PREFIX-BACKUP-RESTORE-DESIGN.md)  
**Restore plan:** [PREFIX-RESTORE-IMPLEMENTATION-PLAN.md](PREFIX-RESTORE-IMPLEMENTATION-PLAN.md)

This document distinguishes implemented backup/restore code from validation still in progress. Passing CI validates only the tested code paths and fixtures; it does not establish compatibility with arbitrary Windows applications or end-user workflows.

## Implemented foundations

### Shared prefix-operation lock

Implemented in `src/winux/core/prefix_lock.py`.

- Canonical lock directory: `~/.local/share/winux/locks/`.
- One advisory exclusive lock per validated prefix name, including non-blocking acquisition.
- Private directory/file permissions; symlink lock files are rejected.
- Prefix creation/deletion, installer operations, application uninstall, and backup participate in the shared lock.
- Dedicated tests cover contention, permissions, invalid names, and symlink lock files.

The lock coordinates Winux-managed operations only. It does not exclude unmanaged Wine processes.

### Read-only prefix filesystem scanner

Implemented in `src/winux/core/prefix_filesystem.py` as `scan_prefix_tree()`.

- Descriptor-relative traversal, no-follow path opening, pinned root descriptor, inode/device/type checks, and Linux mount-ID checks.
- Rejects unexpected symlinks, hardlinks, special files, setuid/setgid objects, nested mount boundaries, unsafe paths, Unicode-normalization collisions, and mutations detected during inventory.
- Recognizes observed Wine device layouts: `c: -> ../drive_c`, optional `z: -> /`, and a contiguous serial mapping beginning at `com1` (observed variants include `com1`–`com4` and `com1`–`com32`). Gaps and unexpected targets remain rejected.
- Does not resolve or traverse Z: or COM targets; records logical mappings only.
- Excludes root `.winux-prefix.json` after validating it as a single-link regular file.
- Limits: 250,000 files, 100,000 directories, 20 GiB per file, 100 GiB aggregate regular-file bytes, 4,096 UTF-8 bytes per path, and 255 bytes per component.

The scanner is an inventory/validation primitive, not a copy or restore mechanism. Mount-boundary checks depend on Linux `/proc/self/fdinfo` mount IDs and fail closed when unavailable; do not claim non-Linux portability.

### Conservative Wine process inspection

Implemented in `src/winux/core/wine_processes.py`.

- Reads Linux `/proc` and returns `busy`, `clear`, or `unknown`.
- A matching same-UID process with `WINEPREFIX` is busy.
- Ambiguous Wine processes or unreadable candidate environments are handled conservatively.
- Does not kill or signal processes.

**Important limitation:** this is an advisory snapshot, not race-free proof of quiescence. A process can change its environment or start after inspection; processes under other UIDs are outside its scope. A `clear` result means only that no blocker was observed in that snapshot.

### Internal streaming backup writer

Implemented in `src/winux/core/prefix_backup.py`.

- Acquires the shared prefix lock non-blocking.
- Rejects `busy` and `unknown` process snapshots and requires explicit operator confirmation that Wine applications are closed.
- Uses the scanner's inventory, then opens files relative to pinned directory descriptors with no-follow semantics.
- Revalidates file identity and relevant metadata (device, inode, type, link count, size, and timestamps) while streaming; aborts on detected changes.
- Produces a versioned bounded manifest and USTAR payload; SHA-256 covers the complete tar payload.
- Uses private temporary output, fsync, and atomic no-overwrite publication.
- No process is terminated. The source prefix is not intentionally modified.

The process snapshot plus operator confirmation is still not a kernel-enforced exclusion against unmanaged Wine launches. The writer is an internal API; no public backup CLI is enabled.

### Strict archive inspector

Implemented in `src/winux/core/prefix_archive.py`.

- Non-extracting USTAR inspection; it does not run Wine or materialize archive contents.
- Validates tar checksums, allowed entry types, canonical paths, inventory correspondence, manifest schema/duplicate JSON keys, complete payload digest, size/resource ceilings, and exact archive termination.
- Rejects traversal, backslash paths, symlinks/hardlinks, special or unsupported entries, malformed/truncated data, digest mismatch, duplicate keys/entries, and trailing bytes.
- The writer-to-inspector integration test uses a disposable synthetic prefix.

## CI evidence for PR #52

PR #52 was squash-merged to `main` as `688861212d465ec255fb5e1b5de4e3e9919d5550`. All four required workflows completed successfully on head `dea077cbe0ea2015c3db3a3ad0f80a9fc752d6cb` before merge:

| Workflow | Run ID | Result |
|---|---:|---|
| Winux CI | 44039314463 | success |
| Real Windows Installer Integration | 44039314480 | success |
| Real Windows MSI Installer Integration | 44039314434 | success |
| WineHQ Stable 11 Integration | 44039314637 | success |

The Winux CI run included the writer/inspector integration and hostile archive tests, x86/x64 matrix, real Wine execution, services tests, and packaging. The real-installer and WineHQ workflows exercised their defined x86/x64 EXE/MSI and PE fixtures. These results validate those fixtures and code paths only; they do not prove arbitrary Windows application compatibility or the EMWAT/Office workflow.

## Remaining work

### Internal secure restore — implemented; real-Wine validation pending

Implemented in `src/winux/core/prefix_restore.py` on PR #55.

- Opens the backup with no-follow, nonblocking semantics and pins its file identity.
- Validates the archive through a duplicate of that already-open file descriptor, then rewinds and consumes the same open file description; it rechecks file identity and hashes the payload again while extracting.
- Holds the destination's shared prefix lock from staging through publication and rejects any existing destination.
- Creates a private staging directory under the managed prefix base on the same filesystem.
- Extracts USTAR entries manually with descriptor-relative, no-follow, exclusive file creation; does not use generic tar extraction.
- Enforces inventory correspondence, payload digest, exact termination, and file/directory type constraints during extraction.
- Sanitizes permissions, writes fresh metadata, selects the currently installed local runtime, recreates only `dosdevices/c: -> ../drive_c`, and omits Z: and COM aliases by default.
- Validates the staged prefix with the local runtime and filesystem scanner, fsyncs it, and publishes atomically with Linux `renameat2(RENAME_NOREPLACE)`; fails closed if unavailable.
- Cleans up its private staging tree on failure and never replaces an existing destination.
- Synthetic tests are now wired into the `test-runtime` CI job.

**Validation status on 2026-11-17:** PR #55's first real integration run confirmed Wine 9 could create, back up, inspect, and restore a real 1.3 GB WoW64 prefix, but launching the restored x86 smoke executable aborted with `free(): invalid pointer`. WineHQ 11 reached backup but its actual COM1–COM4 device layout was rejected by the earlier all-or-none COM1–COM32 scanner rule. The scanner was updated to accept contiguous COM1..N layouts while rejecting gaps, and the integration script now runs x86/x64 controls in the original source prefix before testing the restored prefix. Those fixes require a fresh CI run; do not mark real-Wine restore as passing yet.

PR #55's first validation results:
| Workflow | Run ID | Result |
|---|---:|---|
| Winux CI | 44061905578 | failure: Wine 9 post-restore x86 launch |
| WineHQ Stable 11 | 44061905473 | failure: old COM mapping validation |
| Real Windows Installer Integration | 44061905574 | success |
| Real Windows MSI Installer Integration | 44061905563 | success |

The EXE/MSI workflows exercised disposable x86/x64 fixtures. They do not prove arbitrary Windows application compatibility.

### Public backup CLI — not enabled

Keep backup internal until the process/quiescence limitation is addressed to an explicitly accepted safety level, the API contract is stable, and end-to-end disposable-prefix testing is complete. Never describe a `clear` process snapshot as proof that a prefix is idle.

### Migration and compatibility

Migration remains backup plus restore. Keep the source untouched until the destination's application workflows are independently verified. Report archive integrity, prefix structure, runtime availability, application execution, and workflow compatibility as separate evidence states.
