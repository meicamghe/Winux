# Prefix Restore Implementation Plan

Restore consumes only output from the strict non-extracting archive inspector. It does not call tarfile extraction.

1. Validate the target prefix name, destination absence, installed runtime availability and archive inspection before creating the destination.
2. Acquire the target shared prefix lock non-blocking and hold it through staging and publication.
3. Create a private 0700 staging directory under the managed prefix base using descriptor-relative mkdir operations; require the same filesystem as the publication parent.
4. Re-open the archive with O_NOFOLLOW, pin its device/inode/size/timestamps, and revalidate while streaming. Never trust a stale inspection result.
5. Parse strict USTAR headers again. Create parent directories relative to pinned directory descriptors with O_DIRECTORY|O_NOFOLLOW; create files with O_CREAT|O_EXCL|O_NOFOLLOW and mode 0600.
6. Enforce per-file and aggregate limits while streaming; verify the payload digest, path uniqueness, padding, end markers and exact manifest inventory.
7. Apply sanitized mode bits only after writing. Never restore uid/gid, ACLs, xattrs, capabilities, links, devices, FIFOs, sockets or sparse extents.
8. Reconstruct only dosdevices/c: -> ../drive_c. Do not restore Z: or COM aliases by default.
9. Write fresh .winux-prefix.json with the new prefix name and a currently installed runtime. Archive runtime metadata is informational only.
10. Validate staged prefix with scan_prefix_tree and runtime.validate_prefix; fsync files and directories bottom-up.
11. Atomically publish staging to the final name with no-overwrite semantics and fsync the managed prefix base.
12. On failure, remove only the staging tree created by this operation using descriptor-relative no-follow cleanup. Never alter an existing destination.

This is a plan, not a restore implementation. No restore API or CLI is enabled until adversarial race tests, failure-cleanup tests and disposable real-Wine x86/x64 integration tests pass.