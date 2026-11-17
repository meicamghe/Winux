# Prefix Restore Implementation and Validation

The internal restore implementation is in `src/winux/core/prefix_restore.py`. It consumes only output from the strict non-extracting archive inspector and does not call tarfile extraction. The safeguards below are implemented; synthetic adversarial tests and real Wine 10/11 x86/x64 restore validation have passed.

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

## Current validation gates

- [x] Synthetic success, existing-destination protection, digest failure, symlink archive rejection, unavailable local runtime, and runtime-validation cleanup tests.
- [x] Synthetic restore tests added to the `test-runtime` CI workflow.
- [x] Adversarial restore coverage rejects traversal, symlinks, hardlinks, special entries, duplicate members, and truncated tar payloads before staging; injected extraction and publication failures verify staging cleanup.
- [x] Pass real WineHQ Stable 10.0 backup/restore followed by x86 and x64 execution. CI pins the exact WineHQ 10.0 package set and verifies the installed version.
- [x] Pass real WineHQ Stable 11.0 backup/restore followed by x86 and x64 execution. CI pins the exact WineHQ 11.0 package set and verifies the installed version.
- [x] Pass all EXE/MSI integration workflows on the validated PR head.

No public restore CLI is enabled yet. The current validation gates are green, but keep restore internal until the public API contract and operational safety requirements are explicitly reviewed.