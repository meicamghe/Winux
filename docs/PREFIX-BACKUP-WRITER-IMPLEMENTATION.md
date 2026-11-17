# Prefix Backup Writer Implementation Status

**Status:** internal writer only. No public CLI, archive inspector, or restore exists.

The writer emits a versioned binary container with a tar payload and bounded JSON manifest. It requires explicit offline operator confirmation, a non-blocking shared Winux prefix lock, and an advisory Wine process scan returning clear. It reopens files relative to a pinned prefix root descriptor, checks device/inode/type/mode/link count/size/mtime/ctime against scanner inventory, hashes bytes while streaming, rechecks file metadata after EOF, fsyncs temporary output, and atomically publishes without overwriting an existing destination.

Wine drive links are not copied as host symlinks: dosdevices is represented as an empty directory and logical mappings are stored in the manifest. The source metadata file is not included.

**Safety boundary:** /proc inspection is a snapshot and cannot prevent an external Wine client starting after the scan. Explicit confirmation is an operator assertion, not race-free exclusion. This API must not be described as unattended-safe and must not be exposed in the CLI yet. No process is killed or signalled.

Archive inspection, hostile-input tests, restore, CLI integration, and real Wine backup/restore integration remain future milestones. Current CI tests cover descriptor-relative opening and replacement detection, not all possible concurrent directory mutations or restore compatibility.
