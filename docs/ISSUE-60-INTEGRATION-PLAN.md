# Issue #60 integration plan

This is a review plan for PRs #55–#59. It does not merge, close, retarget, or rewrite any PR.

## Verified baseline

- Live base: `main` at `688c82bafcd12b20cbf28949c9fe98b2703919f8`.
- PR heads are independent descendants of that base. Their exact SHAs and current CI runs are recorded in issue #60.
- Each head currently has successful Winux CI, WineHQ Stable 11 integration, real EXE installer integration, and real MSI installer integration.
- Runtime policy for any follow-up is WineHQ Stable 11.0 only, package version `11.0.0.0~noble-1`.

## File overlap

| PR | Main implementation paths | Shared workflow paths |
|---|---|---|
| #55 secure restore | `prefix_archive.py`, `prefix_filesystem.py`, `prefix_restore.py`, restore tests and smoke script | all four workflows |
| #56 host diagnostics | `platform/distribution.py`, `platform/runtime.py`, diagnostics tests | all four workflows |
| #57 read-only inspection CLI | `__main__.py`, CLI tests | installer, MSI installer, WineHQ 11 workflows |
| #58 backup writer hardening | `prefix_backup.py`, backup adversarial tests | installer, MSI installer, WineHQ 11 workflows |
| #59 Wine 11 baseline | none beyond workflow configuration | all four workflows |

The shared paths are `.github/workflows/ci.yml`, `.github/workflows/real-installers.yml`, `.github/workflows/real-msi-installers.yml`, and `.github/workflows/winehq-stable-11.yml`. Treat their changes as one conflict-prone integration area: preserve the exact Wine package pin and every feature-specific test invocation when reviewing each delta.

## Suggested sequence after explicit merge approval

1. **#59 Wine 11 baseline.** Establish the exact WineHQ package/version policy first.
2. **#58 backup writer hardening.** Keep exclusive temporary creation, descriptor-relative write/hash/publish/cleanup, and parent-swap adversarial tests.
3. **#55 secure restore.** Integrate restore atop the hardened backup foundation; preserve the scanner and archive descriptor identity checks, private staging, safe metadata regeneration, and atomic no-replace publication.
4. **#57 read-only inspection CLI.** Review after archive validation changes are settled; inspection must never extract or mutate the prefix or archive.
5. **#56 host diagnostics.** Independent feature; its workflow edits should be refreshed onto the final CI set and host discovery must remain observational only.

This order is advisory. For every PR, review changes against the then-current base, carry only the intended feature delta, and re-run its focused tests plus all applicable workflows on the resulting exact candidate SHA. Do not apply whole-branch merges blindly: the heads contain overlapping Wine workflow updates and may differ from a post-integration base. Keep all original PRs open unless the user separately directs otherwise.

## Safety gates retained

- Public Backup and Restore entry points stay disabled until the operational quiescence, interface, and end-to-end safety gates are explicitly satisfied.
- Process inspection is advisory and cannot prove that another Wine process will not start after inspection.
- Restore continues to fail closed on unsafe archive members, path and inode changes, destination races, unsupported atomic publication, and cleanup failures.
- Wine 9 and Wine 10 must not appear in workflows, tests, docs, installers, or acceptance criteria.
