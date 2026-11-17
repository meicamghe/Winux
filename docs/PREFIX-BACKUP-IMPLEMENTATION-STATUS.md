# Prefix Backup / Restore — Implementation Status

**Status date:** 2026-11-17  
**Canonical security contract:** [PREFIX-BACKUP-RESTORE-DESIGN.md](PREFIX-BACKUP-RESTORE-DESIGN.md)  
**Restore plan:** [PREFIX-RESTORE-IMPLEMENTATION-PLAN.md](PREFIX-RESTORE-IMPLEMENTATION-PLAN.md)

This document distinguishes implemented backup foundations from the still-unimplemented restore path. Passing CI validates the tested code paths and fixtures; it does not establish compatibility with arbitrary Windows applications or end-user workflows.

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
- Recognizes the observed Wine device layout: `c: -> ../drive_c`, optional `z: -> /`, and all-or-none `com1`–`com32` mappings.
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

### Restore — not implemented

There is no restore API or CLI yet. The implementation must follow `PREFIX-RESTORE-IMPLEMENTATION-PLAN.md` and the canonical security design. Required gates include:

1. Open and inspect the same archive file descriptor with no-follow semantics; do not trust a pathname between validation and use.
2. Hold the destination prefix's shared lock from staging through publication; reject an existing destination.
3. Stage privately under the managed prefix root on the same filesystem.
4. Recreate files and directories manually with descriptor-relative, exclusive, no-follow operations; never use generic unsafe archive extraction.
5. Apply safe modes and current-user ownership; ignore archive ownership and permissions.
6. Recreate only the validated C: mapping by default. Do not restore Z: or COM aliases by default; Z: can expose the host root.
7. Generate fresh `.winux-prefix.json` metadata; never restore archived metadata as authoritative.
8. Select and validate an installed local runtime rather than trusting archive runtime metadata.
9. Run the prefix scanner against the staged tree, fsync files/directories, then publish atomically without replacement. Fail closed if safe no-replace publication is unavailable.
10. Clean up staging safely on every failure and guarantee no partial destination publication.

Adversarial restore tests must cover traversal, links/special entries, malformed/truncated archives, digest/checksum failures, duplicate entries, existing destinations, symlink/race attacks, fresh metadata, drive mappings, and x86/x64 prefixes. Do not expose Restore in the CLI until these gates pass.

### Public backup CLI — not enabled

Keep backup internal until the process/quiescence limitation is addressed to an explicitly accepted safety level, the API contract is stable, and end-to-end disposable-prefix testing is complete. Never describe a `clear` process snapshot as proof that a prefix is idle.

### Migration and compatibility

Migration remains backup plus restore. Keep the source untouched until the destination's application workflows are independently verified. Report archive integrity, prefix structure, runtime availability, application execution, and workflow compatibility as separate evidence states.
