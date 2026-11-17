# Prefix Quiescence and Streaming Backup Writer Design

**Status:** design only; the process inspector in this branch is advisory and must not be treated as a backup authorization gate.

## 1. Process inspection primitive

`src/winux/core/wine_processes.py` provides a read-only Linux `/proc` snapshot:

- A process whose readable environment contains a `WINEPREFIX` matching the requested prefix is reported as a blocker, even if its executable name is not recognizable as Wine.
- Recognizable Wine loaders, wineserver processes, and PE-style `.exe` processes with no explicit `WINEPREFIX` are reported as blockers for the implicit `~/.wine` prefix and as unknown for other prefixes.
- An unreadable process table, unreadable candidate environment, duplicate `WINEPREFIX` entries, or ambiguous Wine process produces `unknown`.
- Processes owned by another UID are outside this inspection scope; managed prefixes are private to their owner.
- The function never signals, stops, or modifies a process.

### Why this is not proof of quiescence

Linux process environments are observations, not an immutable Wine process-to-prefix binding. A process can rewrite or scrub its environment; process identity and command names are not a complete Wine API; a new Wine client can start immediately after the scan; and this snapshot does not lock Wine's server socket against external clients. Therefore:

- `clear` means only “no blocker was observed in this snapshot”.
- It does not mean “no process can be using or start using this prefix”.
- The result must not yet authorize Backup or Restore.
- Any future backup workflow must fail closed on `busy` and `unknown`, acquire the shared Winux prefix lock non-blocking, and revalidate all preconditions immediately before reading.
- Never kill Wine or terminate an application automatically to make a backup proceed.

A stronger quiescence protocol must be proven against supported Wine versions and external launch races. If Wine does not expose a stable, non-destructive exclusion primitive for a prefix, the product must state that limitation and require the user to close all applications plus an explicit offline confirmation; even then, the guarantee must be described accurately.

## 2. Required backup writer architecture

The writer is a separate future component. It must accept only a validated scan result and a held exclusive prefix-operation lock, but it must not trust the scan result as a permanent authorization to read.

### 2.1 Preflight

1. Resolve the managed prefix name through PrefixManager and validate runtime metadata.
2. Acquire `prefix_operation_lock(name, blocking=False)`; fail if another Winux mutation is active.
3. Run the process inspection. Reject `busy` and `unknown`; do not kill processes.
4. Run `scan_prefix_tree()` and retain its deterministic inventory and logical drive mappings.
5. Create the destination temporary file exclusively, with no-follow semantics, mode 0600, in the destination directory. Reject symlinked destination components, an existing final path, and any destination located inside the source prefix.
6. Pin source directory descriptors. The source must never be modified.

### 2.2 Stream each regular file

For every inventory entry:

1. Resolve the parent only through already-pinned directory descriptors; never concatenate an untrusted archive path into a host filesystem path.
2. Open the basename relative to its pinned parent with `O_RDONLY | O_NOFOLLOW | O_CLOEXEC`.
3. Compare `fstat` identity and metadata with the inventory: device, inode, file type, link count, size, mode policy, mtime and ctime (nanosecond precision where available).
4. Stream in bounded chunks. Enforce maximum file bytes, total bytes, file count, directory count, path bytes, and archive output bytes during streaming—not only from the manifest.
5. Hash the exact payload bytes while streaming. Recheck the open descriptor metadata after EOF and compare it with the pre-read snapshot. If any identity or metadata changes, abort and discard the entire temporary archive.
6. Do not follow symlinks, preserve hardlinks, restore ownership, or copy ACLs, xattrs, capabilities, devices, sockets, FIFOs, or sparse extents.

The writer must define whether it archives logical file bytes or allocated extents. The safe initial format is logical regular-file bytes only; sparse files should be rejected or materialized only under strict logical-size ceilings.

### 2.3 Archive format

Use a versioned outer container with an exact member allow-list, for example:

- `manifest.json`: bounded UTF-8 JSON, strict schema, duplicate object keys rejected.
- `payload.tar`: deterministic tar stream containing only regular files and directories.

Reject duplicate outer members, extra members, duplicate normalized inner paths, absolute paths, dot-dot components, backslashes, drive prefixes, unsupported PAX/global headers, GNU sparse metadata, links, devices, FIFOs, and unknown tar types. Do not trust archive-provided ownership, permissions, timestamps, or path prefixes.

The manifest records format version, Winux metadata needed to reconstruct a new prefix, architecture, runtime identifier/version as informational data, file inventory, logical drive mappings, byte counts, and SHA-256 for the exact payload stream. Runtime presence and application compatibility are checked separately during restore; an archive must not claim either.

### 2.4 Publication and cleanup

- Enforce compressed and uncompressed ceilings while writing.
- Flush and fsync the temporary archive, then atomically publish with no-overwrite semantics.
- Fsync the destination directory after publication.
- On any error, close descriptors and unlink only the temporary file created by this operation.
- Never replace an existing backup. Never leave a partial archive at the final path.

## 3. Archive inspection before restore

An inspector must validate the outer container, exact member set, manifest schema and size, duplicate JSON keys, payload digest, tar headers, normalized path uniqueness, path and resource ceilings, and complete decompression. It must not extract files, create a Wine prefix, run Wine, or trust metadata from the archive.

## 4. Restore boundary

Restore is a later milestone and must not be coupled to the first writer implementation:

- Acquire the destination prefix lock and hold it from staging through publication.
- Require a destination that does not exist.
- Stage in a private 0700 directory on the same filesystem as the managed prefix root.
- Create directories and files descriptor-relatively with no-follow and exclusive-create flags.
- Reconstruct only the fixed Wine drive mappings allowed by policy; omit Z: and COM mappings by default.
- Write fresh `.winux-prefix.json` metadata; never restore the source metadata file.
- Apply safe default modes and current-user ownership only. Do not restore archive ownership, ACLs, xattrs, capabilities, or links.
- Validate the staged tree with the scanner, validate runtime availability and prefix structure, fsync, then atomically publish.
- Never overwrite an existing destination. On failure, remove only the staging tree created by this restore.

## 5. Acceptance criteria

No user-facing Backup/Restore command until all are true:

- Quiescence limitations are explicit and the selected gate is justified by Wine-version integration evidence.
- Writer uses pinned descriptors and detects replacement/mutation during streaming.
- All resource ceilings are enforced during decompression and writing.
- Archive inspector rejects malformed, ambiguous, duplicated, truncated, oversized, and hostile inputs without extraction.
- Adversarial race and path tests pass.
- Backup source remains byte-for-byte and metadata-for-metadata unchanged.
- Real Wine integration covers x86/x64 applications in disposable prefixes and is reported separately from unit tests.
