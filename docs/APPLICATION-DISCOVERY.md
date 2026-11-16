# Application discovery and launch-target diagnostics

Winux inventories installed applications from Windows uninstall registry keys
and registered Windows App Paths entries. It also discovers Wine-generated
desktop launchers for a selected prefix.

## Uninstall registry inventory

The uninstall registry remains the primary source for application identity,
version, publisher, install location, and uninstall command. `DisplayIcon` is
only a hint: it may identify an icon, DLL, or other resource rather than the
program entry point.

## Windows App Paths

Winux queries machine-wide, 32-bit-view, and per-user App Paths roots. It
interprets each registration's default value as a candidate executable and
accepts it only when the value maps to an existing `.exe` within the selected
prefix. Identical executable targets are deduplicated against uninstall
inventory records.

The App Paths parser is separate from uninstall registry parsing because the
default registry value has different semantics. Missing files, non-EXE
resources, paths outside the prefix, and invalid drive paths are not exposed
as launch targets.

## Launch-target status

Inventory records expose a diagnostic `executable_status`:

| Status | Meaning |
|---|---|
| `ready` | A registered candidate resolves to an existing `.exe` inside the prefix |
| `not_registered` | No `DisplayIcon` launch candidate is registered |
| `invalid_registry_path` | The registered path cannot be safely mapped inside the prefix |
| `resource_not_executable` | The registered value points to a non-`.exe` resource |
| `executable_missing` | The registered value names an `.exe`, but that file is absent |

These statuses are diagnostic, not compatibility claims. `ready` confirms
only that a candidate file exists; it does not prove that the executable is
the application's primary entry point or that it runs.

## Wine desktop launchers

Winux parses the `Exec` field of Wine-generated desktop entries without
executing the command. It extracts the declared `WINEPREFIX` and compares its
resolved path exactly with the requested prefix; substring matches are not
accepted. Symlinked source entries and malformed launchers are ignored.

Desktop integration uses the same exact-prefix validation. If a destination
already exists and differs from the source, Winux refuses to overwrite it.
This protects unrelated user-owned desktop entries.

## Remaining discovery work

1. Parse Windows Start Menu `.lnk` files using a tested Shell Link parser.
2. Improve candidate association where App Paths registrations and uninstall
   records refer to the same product under different names.
3. Add real Wine/WoW64 integration tests for x86 and x64 launchers and
   installers on supported distributions.

Do not recursively select an arbitrary `.exe` from an install directory:
large applications commonly contain helpers, updaters, crash handlers, and
uninstallers. Ambiguous candidates must remain unresolved instead of guessing.

## Validation boundary

Hosted CI covers parsing, path containment, status classification, launcher
prefix matching, and safe desktop-file collision handling. Hosted CI does not
launch Wine applications or create real Windows prefixes. Real x86/x64
runtime compatibility remains a separate integration requirement.

## Windows Start Menu shortcuts

The Shell Link parser reads the local target from a validated LinkInfo block.
Discovery considers machine-wide and per-user Start Menu folders and accepts
only an existing .exe whose resolved path remains inside the selected
prefix's drive_c. Symlinked shortcut files, malformed links, relative-only
links, network targets, IDList-only links, missing targets, and paths outside
the prefix are ignored rather than guessed.

The discovery API currently returns shortcut candidates separately; merging
these candidates into the primary application inventory and associating them
with uninstall/App Paths records remains follow-up work.

## Updated verification

- PR #6 added the conservative Shell Link parser and Start Menu discovery.
  Its Run 274 passed core, runtime, services, and package checks.
- The PR also exposed and fixed a pre-existing desktop Exec parsing issue:
  quoted WINEPREFIX values are now parsed with POSIX shell quoting rules.
