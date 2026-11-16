# Prefix Backup and Restore — Security Contract

## Status

Design contract for the first implementation. The backup format is versioned and
must be treated as untrusted input during restore. A successful restore means
that the prefix structure and Winux metadata were restored; it does not prove
that every application inside the prefix is compatible or launchable.

## User-facing operations

The intended commands are:

    winux prefix backup <name> --output <archive.tar.gz>
    winux prefix restore <archive.tar.gz> --name <new-name>

Backup must refuse to overwrite an existing output unless an explicit future
overwrite option is added. Restore always requires a new, validated prefix
name and refuses to replace an existing prefix. The first implementation will
not offer in-place restore or destructive overwrite.

## Archive format

- Use a gzip-compressed tar archive with a top-level format manifest.
- The manifest has a format identifier and version, original prefix name,
  architecture, runtime binding, and a list of included prefix payload paths.
- Preserve .winux-prefix.json and Wine registry/state files as ordinary data.
- Do not include Winux manager logs, external application caches, or data
  outside the prefix directory.
- Do not follow filesystem symlinks while creating the archive.
- Wine's conventional absolute dosdevices/z: host-root link is omitted.
  Other symlinks must be relative and resolve lexically within the prefix;
  unsafe or unsupported links make backup fail closed.
- Special files (sockets, FIFOs, block/character devices) are not valid payload.

## Restore validation and extraction

Treat every archive as hostile, even when it was created by Winux.

Before writing anything:
1. Validate the manifest, supported format version, metadata types, prefix
   architecture, and runtime name.
2. Reject absolute member paths, empty/dot/parent traversal components,
   duplicate normalized paths, paths outside the single payload root, and
   unexpected top-level entries.
3. Reject hard links, devices, FIFOs, sockets, and unsupported tar member types.
4. Validate symlink targets as relative and ensure their normalized target
   remains within the staging prefix. Never follow an archive symlink while
   extracting later members.
5. Enforce reasonable member-count and uncompressed-size limits.

Extract manually into a newly created mode-0700 staging directory beneath the
managed prefix root. Create regular files with exclusive creation and restrictive
permissions; create directories explicitly; create validated symlinks only
after regular files and directories have been materialized. Do not use
unfiltered tarfile.extractall().

After extraction:
- Validate the real, non-symlink drive_c directory.
- Validate Wine prefix structure with the runtime named in the manifest.
- Validate the restored metadata against the requested destination name and
  the manifest's architecture/runtime.
- Require the referenced runtime to be registered and available. Do not silently
  substitute the default runtime.
- Ensure no extracted path escaped the staging root.

Only after all checks pass, atomically rename the staging directory to the final
prefix name. The final destination must not exist. On any failure, remove only
the staging directory created by this restore operation and leave existing
prefixes untouched.

## Runtime portability and limitations

A backup preserves the source runtime binding; it does not bundle Wine or
guarantee that another Wine version can safely open the prefix. The first
implementation requires the same runtime identifier to be installed on the
restore host and validates the prefix through that runtime. Cross-runtime
migration is a separate feature with its own conversion and compatibility
checks.

Prefix backups may contain application data, credentials, tokens, and private
documents. Keep archives private (0600), warn users to store them securely, and
never print file contents or secrets in logs. Do not run Wine or Windows
applications during backup or restore.

## Required tests

- Round-trip backup/restore preserving files, metadata, architecture, and
  runtime binding.
- Existing destination refusal and no-overwrite behavior.
- Corrupt/truncated archives and malformed/missing manifests.
- Absolute paths, parent traversal, duplicate normalized paths, unexpected roots.
- Symlink escape, absolute symlink, symlink-parent extraction attacks, and
  safe internal relative symlinks.
- Hard links and special files.
- Member-count and expanded-size limits.
- Runtime missing/unavailable and runtime validation failure.
- Cleanup after extraction/validation failure; atomic publication only on success.
- CLI argument validation and explicit destination naming.

## Non-goals for the first version

- In-place restore or overwrite.
- Runtime conversion/migration.
- Cloud backup, encryption/key management, incremental snapshots, or automatic
  scheduling.
- Guaranteeing application-level compatibility after restore.
