# Prefix Backup / Restore — Implementation Status

**Status date:** 2026-11-17  
**Canonical security contract:** [PREFIX-BACKUP-RESTORE-DESIGN.md](PREFIX-BACKUP-RESTORE-DESIGN.md)  
**Purpose:** This file records implemented facts and supersedes any earlier status statements in the design document that say the shared lock or filesystem scanner is still missing.

## Implemented foundations

### Shared prefix-operation lock

Implemented in `src/winux/core/prefix_lock.py`.

- Canonical lock directory: `~/.local/share/winux/locks/`.
- One advisory exclusive lock per validated prefix name.
- Supports non-blocking acquisition for operations such as backup.
- Lock directory and files use private permissions; symlink lock files are rejected.
- Prefix creation and deletion, installer operations, and application uninstall participate in the shared lock.
- Dedicated tests cover contention, permissions, invalid names, and symlink lock files.

The lock coordinates Winux-managed operations only. It does **not** prove that an unmanaged Wine process is not using the prefix. A backup implementation must separately establish quiescence and must never kill Wine processes automatically.

### Read-only prefix filesystem scanner

Implemented in `src/winux/core/prefix_filesystem.py` as `scan_prefix_tree()`.

- Opens the absolute prefix path component-by-component with no-follow semantics and pins the root descriptor.
- Uses descriptor-relative traversal, `O_NOFOLLOW`, `fstat`, inode/device/type comparisons, and Linux mount IDs.
- Rejects unexpected symlinks, hard-linked files, special files, setuid/setgid objects, nested mount boundaries, path traversal/drive-prefixed/backslash paths, Unicode-normalization collisions, and mutations detected during inventory.
- Recognizes only the observed Wine `dosdevices` layout: `c: -> ../drive_c`, optional `z: -> /`, and either all or none of `com1`–`com32 -> /dev/ttyS0`–`/dev/ttyS31`.
- Does not resolve or traverse the Z: or COM targets. It records logical mappings only.
- Excludes the root `.winux-prefix.json` from the inventory after validating that it is a single-link regular file.
- Current scanner ceilings: 250,000 files, 100,000 directories, 20 GiB per file, 100 GiB aggregate regular-file bytes, 4,096 UTF-8 bytes per path, and 255 bytes per component.

The scanner is an inventory/validation primitive only. It does **not** stream or copy file contents, calculate payload hashes, create archives, or restore prefixes. Its inventory metadata is not a substitute for re-opening each file and revalidating the pinned identity while a future writer streams bytes.

The scanner's mount-boundary check currently depends on Linux `/proc/self/fdinfo/<fd>` mount IDs and fails closed when the mount ID cannot be read. Do not claim portability to non-Linux platforms.

## CI evidence for PR #49

All four workflows for head commit `173b21bd56489cdf68624e2ec7809674b0722097` completed successfully before merge:

| Workflow | Run ID | Result |
|---|---:|---|
| Winux CI | 44027903563 | success |
| Real Windows Installer Integration | 44027903658 | success |
| WineHQ Stable 11 Integration | 44027903578 | success |
| Real Windows MSI Installer Integration | 44027903592 | success |

The Winux CI run executed the shared-lock and filesystem-scanner test steps, the x86/x64 WoW64 matrix, real Wine x86/x64 execution, services tests, and packaging smoke test. The real-installer workflows exercised their defined synthetic x86/x64 EXE/MSI fixtures. These results validate those CI fixtures and code paths; they do not prove arbitrary Windows application compatibility or any end-user workflow.

PR #49 was squash-merged to `main` as `cd0898711ae9557ffb39f3a057548bf11d4c44bb`.

## Remaining backup/restore gates

Backup and restore remain **unimplemented and unavailable**. Do not add user-facing CLI commands until the relevant stages are complete.

1. **Quiescence detection:** after acquiring the non-blocking shared lock, independently detect managed and unmanaged Wine processes using the target prefix. Fail closed if the process state cannot be established. Never terminate processes.
2. **Streaming backup writer:** traverse from pinned descriptors; reopen every file relative to its pinned parent with no-follow flags; compare device, inode, type, link count, size, and relevant timestamps; enforce byte/file/path limits while reading; abort and discard output if any object changes.
3. **Archive construction:** write to a private temporary file; use a versioned manifest and exact outer-member allow-list; reject duplicate members and unsupported tar types/PAX/sparse metadata; hash the compressed payload; fsync and atomically publish without overwriting an existing output.
4. **Archive inspector:** validate bounded manifest parsing, exact members, payload digest, tar headers, duplicate normalized paths, codec errors, and observed resource ceilings without extracting or running Wine.
5. **Adversarial tests:** include races, path replacement, malformed/truncated archives, digest mismatch, archive bombs, duplicate paths/keys, sparse and special entries, and output-path attacks.
6. **Restore (separate milestone):** strict staging under the managed root, exclusive no-follow file creation, fresh metadata, fixed-policy drive-link reconstruction, runtime validation, fsync, and atomic publication. Destination must not exist.
7. **Process and Wine integration:** run disposable-prefix integration on supported Wine versions and report it separately from unit/fixture tests.

## Required semantics

- Backup must be read-only with respect to the source prefix.
- Backup obtains the shared prefix lock non-blocking and separately proves quiescence.
- Z: and COM aliases are omitted from archive payloads; Z: restoration is opt-in because it exposes the destination host root. COM restoration is opt-in.
- Unknown symlinks and unsupported filesystem objects fail the backup; they are never silently skipped.
- Restore never overwrites an existing prefix and never trusts archive ownership, permissions, links, or source metadata.
- Migration is backup plus restore. Keep the source untouched until the destination's application workflows have been independently verified.
- Report archive integrity, prefix structure, runtime availability, application execution, and workflow compatibility as separate evidence states.
