# Application discovery and launch-target diagnostics

Winux currently inventories installed applications from the Windows uninstall
registry keys. The `DisplayIcon` value is only a hint: it may identify an icon,
DLL, or other resource rather than the program entry point.

## Launch-target status

Each inventory record exposes:

| Status | Meaning |
|---|---|
| `ready` | `DisplayIcon` resolves to an existing `.exe` inside the prefix |
| `not_registered` | No `DisplayIcon` value is registered |
| `invalid_registry_path` | The value cannot be safely mapped inside the prefix |
| `resource_not_executable` | The value points to a non-`.exe` resource |
| `executable_missing` | The value names an `.exe`, but that file is absent |

These statuses are diagnostic, not compatibility claims. In particular,
`ready` confirms only that a candidate file exists; it does not prove that
the executable is the application's primary entry point or that it runs.

## Next discovery sources

Add sources incrementally and keep each candidate independently validated:

1. Wine-generated desktop launchers, with strict prefix matching and safe
   parsing of the executable command.
2. Windows Start Menu shortcuts, after a tested Shell Link parser is available.
3. Windows App Paths registry entries, with explicit handling of default
   registry values and per-user versus machine scope.

Do not recursively select an arbitrary `.exe` from an install directory:
large applications commonly contain helpers, updaters, crash handlers, and
uninstallers. Ambiguous candidates must remain unresolved instead of guessing.

## Validation boundary

Unit tests cover path containment and status classification. Hosted CI does
not launch Wine applications. Real x86/x64 launch validation remains a
separate integration test on supported Wine/WoW64 builds.
