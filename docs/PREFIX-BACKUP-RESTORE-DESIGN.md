# Prefix Backup, Restore, and Migration — Security Design

**Status:** Design proposal; implementation must follow this contract.  
**Scope:** Winux-managed Wine prefixes under `~/.local/share/winux/prefixes/`.  
**Compatibility target:** x86 and x64 Windows applications in Winux's current `win64` WoW64 prefix model.

## 1. Goals and non-goals

### Goals

- Create a portable, verifiable backup of one validated Winux prefix.
- Restore a backup into a new Winux-managed prefix without overwriting existing data.
- Support moving a prefix between Linux hosts while making host-specific Wine links safe.
- Preserve prefix identity metadata, selected runtime identity, architecture, and a content manifest.
- Reject malformed, hostile, oversized, or incompatible archives before publishing restored data.
- Keep backup and restore operations non-root and fail safely without partially replacing a live prefix.

### Non-goals for the first implementation

- Synchronizing a live prefix while Wine processes are modifying it.
- Converting between Wine prefix architectures or Wine implementations.
- Guaranteeing application compatibility after moving to another host.
- Backing up host-level Wine packages, GPU drivers, fonts, CUPS, kernel modules, or other external dependencies.
- Encrypting backups or managing encryption keys.
- Importing arbitrary untrusted Wine directories as if they were validated Winux prefixes.

## 2. Existing prefix contract

The current PrefixManager stores managed prefixes below:

```
~/.local/share/winux/prefixes/<name>/
```

A usable prefix has a real, non-symlink `drive_c/`, a runtime-valid Wine registry (including `system.reg` for Wine), and optional `.winux-prefix.json` metadata. Current Winux metadata format version is 1 and records the name, `win64` architecture, runtime name, and format version.

Winux accepts both x86 and x64 application workflows through its current `win64` WoW64 prefix model. A backup must record the prefix architecture as `win64`; the architecture of an individual installed application is not a substitute for prefix architecture.

Wine prefixes commonly contain symlinks under `dosdevices/`. In particular, `c:` represents the prefix's C: drive and `z:` commonly exposes the host root filesystem. These links are not ordinary portable application data. Blindly following or restoring them can archive host files or expose a different host after migration.

## 3. Archive format

Use a versioned container with a small JSON manifest and a compressed tar payload. The exact compression codec is an implementation detail recorded in the manifest; the first implementation should use a standard-library codec to avoid an extra runtime dependency.

Logical layout:

```
winux-prefix-backup/
├── manifest.json
└── prefix.tar.<codec>
```

The outer container must not itself be extracted to an arbitrary path. Read its members through a streaming reader and require exactly the expected top-level member names. Reject duplicate names, absolute names, traversal components, unexpected members, links, and non-regular outer members.

### Manifest fields

Required fields:

- `format`: fixed identifier `winux-prefix-backup`.
- `format_version`: positive supported integer; reject unknown major versions.
- `created_at`: UTC RFC 3339 timestamp.
- `prefix`: original name, architecture (`win64`), and Winux prefix metadata version.
- `runtime`: runtime identifier and captured runtime version string (may be unknown, but must be explicit).
- `host`: OS/platform and machine architecture for diagnostics only; never use it to construct filesystem paths.
- `payload`: exact member name, codec, uncompressed byte count, regular-file count, directory count, normalized symlink count, and SHA-256 of the compressed payload bytes.

All strings and numbers must be type-checked. Booleans must not pass integer validation. Reject NUL characters, invalid names, unreasonable string lengths, negative counts, and unsupported versions. The manifest is untrusted input during restore. It is not an authorization source and cannot relax hard limits.

The payload digest must be checked before the restore is published. The manifest itself is not a cryptographic signature; SHA-256 detects accidental corruption, not malicious replacement by an attacker who can rewrite both members.

## 4. Backup safety contract

### 4.1 Prefix selection and quiescence

- Resolve the requested prefix through PrefixManager's normal validation path; do not accept arbitrary user-supplied directory paths as managed prefixes.
- Acquire the same per-prefix operation lock used by other prefix lifecycle operations, or introduce one shared lock contract before implementing backup.
- Refuse backup when Winux can positively determine that the prefix is in use by a managed process or Wine process. Do not kill processes automatically.
- If reliable process detection is unavailable, report that the snapshot cannot be proven quiescent and require an explicit, documented unsafe-snapshot override only if a later product decision approves it. The safe default is refusal.
- Never run Wine or backup commands as root.

### 4.2 Filesystem traversal

- Traverse with no-follow semantics. Never recurse through a symlink.
- Open regular files without following symlinks; verify opened descriptors with `fstat` and compare device/inode metadata with the directory entry to detect replacement races.
- Reject sockets, FIFOs, block devices, character devices, and other special filesystem objects.
- Reject hard-linked regular files (`st_nlink > 1`) in the initial implementation. Supporting hardlinks requires a separately specified, safe in-archive hardlink model.
- Reject mount points or filesystem boundaries beneath the prefix by default; do not accidentally include separately mounted host data.
- Reject files that change while being read (size, inode, mtime/ctime checks where available); abort and discard the incomplete archive.
- Normalize archive member paths to POSIX relative paths. Reject absolute paths, empty path components where ambiguous, `.`, `..`, backslashes used as separators, NUL, and duplicate normalized paths.
- Do not follow directory symlinks, even when their target remains inside the prefix.

### 4.3 Wine drive symlinks

The first implementation must not serialize arbitrary symlinks.

- Recognize only the expected Wine drive aliases directly under `dosdevices/`.
- Validate the C: alias by resolving it without following outside the pinned prefix and confirming it points exactly to this prefix's real `drive_c`. Store it as a logical drive mapping, not as an arbitrary host path.
- Recognize the Z: alias only as the conventional host-root mapping. Do not traverse it or serialize its absolute target. Record that a host-root mapping existed, then reconstruct it according to an explicit restore policy. Default restore behavior should recreate Wine's conventional Z: mapping to the destination host root, with this behavior clearly disclosed to the user.
- Any other symlink, unexpected target, symlinked `dosdevices` directory, or ambiguous mapping causes backup refusal in version 1.
- Restore creates the validated C: and Z: aliases itself; it never trusts symlink targets from archive entries.
- If the actual Wine prefix layout on supported Wine builds differs from these assumptions, add a fixture from a real disposable prefix and revise this contract before enabling backup. Do not weaken validation to make an unknown link pass.

## 5. Resource and archive limits

Define documented, configurable hard ceilings for:

- compressed archive size;
- total uncompressed regular-file bytes;
- individual file size;
- number of files and directories;
- number of accepted drive mappings;
- manifest size;
- maximum path length and component length;
- decompression ratio and processing time where the codec permits meaningful enforcement.

Enforce limits while streaming, not only from manifest declarations or archive headers. Abort immediately when a ceiling is exceeded. Detect truncated streams, checksum errors, duplicate members, and decompression failures. Never allocate memory proportional to the declared uncompressed size; stream data to staging files.

The default limits must be conservative but practical for Office-sized prefixes and must be configurable without allowing an unbounded value accidentally. The final numeric defaults should be selected from test fixtures and documented before implementation.

## 6. Restore and migration safety contract

### 6.1 Destination

- Restore only to a validated Winux prefix name under PrefixManager's managed root.
- Destination must not exist; never overwrite or merge into an existing prefix in version 1.
- Validate the managed root and every existing path component against symlinks before and after directory creation.
- Do not accept a destination filesystem path from the archive or manifest.
- Require the selected runtime to be installed and available. Preserve the recorded runtime identifier in metadata; if unavailable, fail unless the user explicitly selects an installed compatible runtime. Record any override in metadata and restore report.
- Require explicit confirmation at the CLI before publishing a restored prefix. A future GUI must provide the same confirmation and clear destination details.

### 6.2 Validation before extraction

- Validate outer container structure and manifest schema first.
- Verify payload digest before extraction.
- Inspect every tar header before writing any member.
- Accept only regular files and directories plus the separately defined logical Wine drive mappings. Reject symbolic links, hardlinks, devices, FIFOs, sparse-file extensions, unknown PAX keys, duplicate paths, and unsupported metadata.
- Reject absolute paths, traversal, drive-prefixed paths, backslashes, NULs, and paths whose normalized destination escapes the staging root.
- Enforce member count, per-file, aggregate size, and path limits using observed stream bytes.
- Do not trust archive ownership, uid/gid, permissions, timestamps, ACLs, xattrs, capabilities, or setuid/setgid bits. Restore files as the current user with conservative modes; directories must not become world-writable. Preserve only the minimum executable bit needed by the original file and ensure the resulting permissions are no more permissive than the source policy.
- Create files with exclusive creation and no-follow semantics. Never open a pre-existing path for writing.

### 6.3 Staging and atomic publication

- Extract into a newly created private staging directory on the same filesystem as the final prefix root, mode 0700.
- Pin the staging root with a directory file descriptor. Perform descendant creation relative to that descriptor with no-follow flags where available.
- Do not expose the staging directory as a valid prefix or list it as an installed prefix.
- Rebuild validated Wine drive aliases only after all regular files have been extracted and validated.
- Write fresh `.winux-prefix.json` metadata; do not blindly trust or copy the archive's original metadata file. Preserve the source prefix name separately as provenance if the destination name differs.
- Run runtime prefix validation against the staged prefix. Validation must not initialize or modify the prefix unless a separately documented step requires it.
- Fsync files and directories as appropriate, then atomically rename the staging directory to the final destination. Staging and destination must share a filesystem so publication is atomic.
- If any step fails, remove only the staging directory created by this operation, using no-follow traversal. Never recursively delete a path that has been replaced by a symlink.
- If publication succeeds but a durability operation fails, attempt a safe rollback and report both errors if rollback also fails.

### 6.4 Migration semantics

A migration is backup plus restore, not an in-place move. Keep the source prefix intact until the restored destination has been validated and the user has verified application workflows. Do not offer automatic source deletion in the first release.

## 7. Runtime and application compatibility reporting

A restored prefix can be structurally valid while applications fail because Wine versions, libraries, fonts, graphics drivers, COM/OLE behavior, printers, services, and host integrations differ.

The restore report must distinguish:

1. **Archive integrity:** digest and archive structure validated.
2. **Prefix structure:** registry and required directory checks passed.
3. **Runtime availability:** selected runtime exists on this host.
4. **Application execution:** not tested by restore.
5. **Application workflow compatibility:** not tested by restore.

Never label a prefix or its applications as fully compatible solely because restore succeeded. Preserve source runtime version as provenance and report source/destination runtime differences.

## 8. CLI/API proposal

Names are provisional and must be aligned with the current CLI parser before implementation:

```bash
winux prefix backup <name> --output <archive>
winux prefix restore <archive> --name <new-name>
winux prefix inspect-backup <archive>
```

- Backup should be read-only with respect to prefix contents.
- Restore must fail if the destination exists.
- `inspect-backup` must not extract files or run Wine.
- No implicit overwrite, source deletion, runtime installation, or process termination.
- JSON output should include structured evidence states and all warnings.

## 9. Required test matrix

### Archive parsing and integrity

- Valid archive round trip with nested files, Unicode names, spaces, and large streamed files.
- Corrupted digest, truncated archive, invalid compression stream, malformed JSON, unknown format version.
- Duplicate outer members, duplicate normalized tar paths, duplicate manifest keys if the parser exposes them.
- Declared size/count smaller or larger than observed data.
- Oversized manifest, path, file, aggregate payload, member count, and decompression ratio.
- Unsupported PAX metadata, sparse files, hardlinks, symlinks, devices, FIFOs, sockets.

### Path and symlink attacks

- `../`, absolute paths, Windows drive-prefixed names, backslashes, NUL, repeated separators, Unicode normalization collisions.
- Symlinked destination root, parent, destination name, staging directory, and path replacement between validation and write.
- Archive symlink followed by child member (must reject).
- `dosdevices/c:` pointing outside prefix, `dosdevices/z:` targeting an unexpected path, unknown drive aliases, symlinked `dosdevices`.
- Confirm no test can read or archive a sentinel file outside the fixture prefix through a symlink.

### Transaction and recovery

- Destination already exists; no byte is changed.
- Failure during extraction, fsync, metadata write, runtime validation, drive-link creation, and final rename.
- Cleanup never follows symlinks and never removes a path not created by the operation.
- Crash-like incomplete staging is not discovered as a managed prefix.
- Atomic publication and same-filesystem requirement.
- Source prefix remains unchanged after backup and migration failure.

### Compatibility and portability

- x86 and x64 application payloads inside a `win64` WoW64 prefix.
- Runtime metadata absent (legacy prefix), malformed, unknown, or unavailable.
- Same runtime version, newer/older runtime, explicit runtime override.
- Real disposable prefixes from each supported Wine packaging family; record exact Wine versions.
- Cross-host restore verifies that Z: points to the destination host root, never the source host root.

## 10. Implementation sequence

1. Add this design and review the actual symlink layout from disposable prefixes on supported Wine versions.
2. Introduce a shared prefix-operation lock and safe filesystem traversal helpers, with focused unit tests.
3. Implement read-only backup writer and archive inspector; do not add restore in the same change.
4. Add backup round-trip and adversarial archive tests.
5. Implement staged restore with strict member allow-list, fresh metadata, drive-link reconstruction, and atomic publication.
6. Add runtime compatibility reporting and CLI confirmation.
7. Add hosted CI fixtures for archive/path logic. Real Wine prefix integration must run on a Wine-enabled runner and be reported separately from unit tests.
8. Update README, architecture, handoff, and maturity map only after behavior and tests are verified.

## 11. Release gate

Do not expose backup/restore as stable functionality until all adversarial path, symlink, resource-limit, and rollback tests pass. If the supported Wine prefix symlink layout is not established empirically, keep backup/restore disabled rather than guessing.
