"""Internal foreground entry point for Winux-managed services."""

import os
import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: service_runner.py <service-id>", file=sys.stderr)
        return 2

    service_id = sys.argv[1]

    if not re.fullmatch(r"[a-f0-9]{32}", service_id):
        print("Invalid service ID", file=sys.stderr)
        return 2

    if os.geteuid() == 0:
        print(
            "Refusing to run Windows applications as root",
            file=sys.stderr,
        )
        return 1

    # Running this file directly puts src/winux on sys.path.
    # Add src so the winux package can be imported reliably.
    source_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(source_root))

    from winux.core.runner import ApplicationRunner
    from winux.core.services import ServiceManager

    manager = ServiceManager()
    record = manager.get_definition(service_id)

    runner = ApplicationRunner()
    return runner.run_foreground(
        record["prefix"],
        record["application_id"],
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"[Winux service error] {error}", file=sys.stderr)
        raise SystemExit(1)
