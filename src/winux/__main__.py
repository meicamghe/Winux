import argparse
import json
import sys
from pathlib import Path

from winux import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="winux",
        description="Winux Compatibility Engine"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"Winux Alpha {__version__}"
    )

    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="Check system compatibility")

    prefix_parser = commands.add_parser("prefix", help="Manage prefixes")
    prefix_commands = prefix_parser.add_subparsers(
        dest="prefix_command",
        required=True
    )

    create_parser = prefix_commands.add_parser("create")
    create_parser.add_argument("name")
    create_parser.add_argument(
        "--arch",
        choices=("x86", "x64"),
        default="x64",
        help="Prefix architecture (default: x64)"
    )

    prefix_commands.add_parser("list")

    delete_parser = prefix_commands.add_parser("delete")
    delete_parser.add_argument("name")
    delete_parser.add_argument("--yes", action="store_true")

    info_parser = prefix_commands.add_parser("info")
    info_parser.add_argument("name")

    install_parser = commands.add_parser(
        "install",
        help="Install a Windows application"
    )
    install_parser.add_argument("file", nargs="?")
    install_parser.add_argument(
        "--manifest",
        help="JSON manifest for batch installation"
    )
    install_parser.add_argument("--prefix", required=True)
    install_parser.add_argument(
        "--installer-arg",
        action="append",
        default=[],
        help="Argument passed to the Windows installer; repeat to add more arguments",
    )
    install_parser.add_argument(
        "--verification-profile",
        help="JSON file containing post-installation verification checks"
    )
    install_parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Installation timeout in seconds (default: 3600)"
    )

    history_parser = commands.add_parser(
        "history",
        help="Show installation history"
    )
    history_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of records (default: 20)"
    )

    commands.add_parser(
        "stats",
        help="Show installation statistics"
    )

    app_parser = commands.add_parser(
        "app",
        help="Manage installed Windows applications"
    )
    app_commands = app_parser.add_subparsers(
        dest="app_command",
        required=True
    )

    app_list_parser = app_commands.add_parser(
        "list",
        help="List installed applications"
    )
    app_list_parser.add_argument("--prefix", required=True)

    app_search_parser = app_commands.add_parser(
        "search",
        help="Search installed applications"
    )
    app_search_parser.add_argument("--prefix", required=True)
    app_search_parser.add_argument("query")

    app_export_parser = app_commands.add_parser(
        "export",
        help="Export installed applications"
    )
    app_export_parser.add_argument("--prefix", required=True)
    app_export_parser.add_argument("--output", required=True)
    app_export_parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Export format (default: json)"
    )

    app_info_parser = app_commands.add_parser(
        "info",
        help="Show installed application details"
    )
    app_info_parser.add_argument("--prefix", required=True)
    app_info_parser.add_argument("application_id")

    app_run_parser = app_commands.add_parser(
        "run",
        help="Run an installed Windows application"
    )
    app_run_parser.add_argument("--prefix", required=True)
    app_run_parser.add_argument("application_id")
    app_run_parser.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="Arguments passed to the Windows application (use -- before arguments)",
    )

    app_uninstall_parser = app_commands.add_parser(
        "uninstall",
        help="Uninstall an installed Windows application"
    )
    app_uninstall_parser.add_argument("--prefix", required=True)
    app_uninstall_parser.add_argument("application_id")
    app_uninstall_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Uninstallation timeout in seconds (default: 300)"
    )
    app_uninstall_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive uninstall confirmation",
    )

    process_parser = commands.add_parser(
        "process",
        help="Manage running Windows applications",
    )
    process_commands = process_parser.add_subparsers(
        dest="process_command",
        required=True,
    )

    process_list_parser = process_commands.add_parser(
        "list",
        help="List tracked processes",
    )
    process_list_parser.add_argument(
        "--running-only",
        action="store_true",
    )

    process_info_parser = process_commands.add_parser(
        "info",
        help="Show process details",
    )
    process_info_parser.add_argument("process_id")

    process_stop_parser = process_commands.add_parser(
        "stop",
        help="Stop a tracked process",
    )
    process_stop_parser.add_argument("process_id")
    process_stop_parser.add_argument(
        "--timeout", type=float, default=5,
    )
    process_stop_parser.add_argument(
        "--force", action="store_true",
    )

    process_commands.add_parser(
        "cleanup",
        help="Remove inactive process records",
    )


    service_parser = commands.add_parser(
        "service",
        help="Manage background Windows applications",
    )
    service_commands = service_parser.add_subparsers(
        dest="service_command",
        required=True,
    )

    create_service_parser = service_commands.add_parser(
        "create",
        help="Create a managed service definition",
    )
    create_service_parser.add_argument("--name", required=True)
    create_service_parser.add_argument("--prefix", required=True)
    create_service_parser.add_argument("--application", required=True)
    create_service_parser.add_argument(
        "--restart",
        choices=("no", "on-failure", "always"),
        default="on-failure",
    )

    service_commands.add_parser("list", help="List managed services")

    for action in (
        "status", "start", "stop", "restart",
        "enable", "disable", "delete",
    ):
        action_parser = service_commands.add_parser(
            action,
            help=f"{action.title()} a managed service",
        )
        action_parser.add_argument("service_id")

    args = parser.parse_args()

    try:
        if args.command == "doctor":
            from winux.platform.runtime import check_runtime
            if not check_runtime():
                sys.exit(1)

        elif args.command == "prefix":
            from winux.core.prefix import PrefixManager
            manager = PrefixManager()

            if args.prefix_command == "create":
                path = manager.create(
                    args.name,
                    architecture=args.arch
                )
                print(f"[OK] Prefix created: {path}")
                print(f"Architecture: {manager.get_architecture(args.name)}")

            elif args.prefix_command == "list":
                prefixes = manager.list()
                print("\n".join(prefixes) if prefixes else "No prefixes found.")

            elif args.prefix_command == "delete":
                if not args.yes:
                    answer = input(
                        f"Delete prefix '{args.name}' permanently? [y/N]: "
                    )
                    if answer.strip().lower() != "y":
                        print("Deletion cancelled.")
                        return

                manager.delete(args.name, confirm=True)
                print(f"[OK] Prefix deleted: {args.name}")

            elif args.prefix_command == "info":
                path = manager.get_path(args.name)
                print(f"Name: {args.name}")
                print(f"Architecture: {manager.get_architecture(args.name)}")
                print(f"Path: {path}")

        elif args.command == "app":
            from winux.core.applications import ApplicationManager
            manager = ApplicationManager()

            if args.app_command == "list":
                applications = manager.list(args.prefix)

                if not applications:
                    print("No installed applications found.")
                    return

                for app in applications:
                    print("-" * 50)
                    print(f"Name:       {app.get('DisplayName') or 'Unknown'}")
                    print(f"Version:    {app.get('DisplayVersion') or 'Unknown'}")
                    print(f"Publisher:  {app.get('Publisher') or 'Unknown'}")
                    print(f"Executable: {app.get('executable_path') or 'Not found'}")
                    print(f"Launch status: {app.get('executable_status', 'unknown')}")
                    print(f"Registry ID: {app.get('registry_id')}")

            elif args.app_command == "search":
                applications = manager.search(args.prefix, args.query)

                if not applications:
                    print("No matching applications found.")
                    return

                for app in applications:
                    print("-" * 50)
                    print(f"Name:        {app.get('DisplayName') or 'Unknown'}")
                    print(f"Version:     {app.get('DisplayVersion') or 'Unknown'}")
                    print(f"Publisher:   {app.get('Publisher') or 'Unknown'}")
                    print(f"Registry ID: {app.get('registry_id')}")

            elif args.app_command == "export":
                result = manager.export(
                    args.prefix,
                    args.output,
                    args.format
                )

                print("[OK] Applications exported.")
                print(f"Prefix: {result['prefix']}")
                print(f"Format: {result['format']}")
                print(f"Count:  {result['count']}")
                print(f"File:   {result['path']}")

            elif args.app_command == "info":
                app = manager.info(args.prefix, args.application_id)

                print("Application Information")
                print("-" * 40)
                print(f"Name:             {app.get('DisplayName') or 'Unknown'}")
                print(f"Version:          {app.get('DisplayVersion') or 'Unknown'}")
                print(f"Publisher:        {app.get('Publisher') or 'Unknown'}")
                print(f"Registry ID:      {app.get('registry_id')}")
                print(f"Registry Key:     {app.get('registry_key')}")
                print(f"Executable:       {app.get('executable_path') or 'Not found'}")
                print(f"Launch status:    {app.get('executable_status', 'unknown')}")
                print(f"Install Location: {app.get('install_path') or 'Not found'}")
                print(f"Uninstall:        {app.get('UninstallString') or 'Not available'}")
                print(f"Website:          {app.get('URLInfoAbout') or 'Not available'}")

            elif args.app_command == "run":
                from winux.core.runner import ApplicationRunner

                application_arguments = args.arguments
                if application_arguments[:1] == ["--"]:
                    application_arguments = application_arguments[1:]

                result = ApplicationRunner().run(
                    args.prefix,
                    args.application_id,
                    args=application_arguments,
                )

                print("[OK] Application started.")
                print(f"Application: {result['application']}")
                print(f"PID:         {result['pid']}")
                if result.get("process_id"):
                    print(f"Process ID:  {result['process_id']}")
                if result.get("process_registration_error"):
                    print(
                        "[WARNING] Process tracking unavailable: "
                        f"{result['process_registration_error']}"
                    )
                print(f"Executable:  {result['executable']}")
                print(f"Log:         {result['log']}")

            elif args.app_command == "uninstall":
                application = manager.info(args.prefix, args.application_id)
                application_name = (
                    application.get("DisplayName") or args.application_id
                )
                if not args.yes:
                    answer = input(
                        f"Uninstall '{application_name}' from prefix "
                        f"'{args.prefix}'? [y/N]: "
                    )
                    if answer.strip().casefold() != "y":
                        print("Uninstallation cancelled.")
                        return

                result = manager.uninstall(
                    args.prefix,
                    args.application_id,
                    timeout=args.timeout
                )

                print("[OK] Application uninstalled.")
                print(f"Application: {result['application']}")
                print(f"Prefix:      {result['prefix']}")

        elif args.command == "process":
            from winux.core.processes import ProcessManager
            manager = ProcessManager()

            if args.process_command == "list":
                records = manager.list(
                    include_inactive=not args.running_only
                )

                if not records:
                    print("No tracked processes found.")
                    return

                for record in records:
                    print("-" * 60)
                    print(f"ID:          {record.get('id')}")
                    print(f"PID:         {record.get('pid')}")
                    print(f"Application: {record.get('application')}")
                    print(f"Prefix:      {record.get('prefix')}")
                    print(f"Runtime:     {record.get('runtime')}")
                    print(f"Status:      {record.get('status')}")

            elif args.process_command == "info":
                record = manager.get(args.process_id)

                print("Process Information")
                print("-" * 40)
                for key in (
                    "id", "pid", "status", "application",
                    "prefix", "runtime", "executable",
                    "command", "log", "started_at", "uid",
                ):
                    label = key.replace("_", " ").title()
                    print(f"{label}: {record.get(key)}")

            elif args.process_command == "stop":
                result = manager.stop(
                    args.process_id,
                    timeout=args.timeout,
                    force=args.force,
                )

                if result["stopped"]:
                    print(f"[OK] Process stopped: {result['pid']}")
                    if result.get("forced"):
                        print("Termination: forced (SIGKILL)")
                else:
                    print(
                        f"[WARNING] Process not stopped "
                        f"(PID: {result.get('pid')}, "
                        f"status: {result['status']})"
                    )

            elif args.process_command == "cleanup":
                result = manager.cleanup()
                print("[OK] Process records cleaned.")
                print(f"Removed:   {result['removed']}")
                print(f"Remaining: {result['remaining']}")

        elif args.command == "service":
            from winux.core.services import ServiceManager
            manager = ServiceManager()

            if args.service_command == "create":
                record = manager.create(
                    name=args.name,
                    prefix_name=args.prefix,
                    application_id=args.application,
                    restart=args.restart,
                )
                print("[OK] Service definition created.")
                print(f"Name:        {record['name']}")
                print(f"Service ID:  {record['id']}")
                print(f"Prefix:      {record['prefix']}")
                print(f"Application: {record['application']}")
                print(f"Restart:     {record['restart']}")
                print("State:       inactive (not started or enabled)")

            elif args.service_command == "list":
                records = manager.list()
                if not records:
                    print("No managed services found.")
                    return

                for record in records:
                    status = record.get("status", {})
                    print("-" * 60)
                    print(f"Name:        {record.get('name')}")
                    print(f"Service ID:  {record.get('id')}")
                    print(f"Application: {record.get('application')}")
                    print(f"Prefix:      {record.get('prefix')}")
                    print(
                        f"Active:      {status.get('active_state', 'unknown')}"
                    )
                    print(
                        f"Enabled:     {status.get('unit_file_state', 'unknown')}"
                    )

            elif args.service_command == "status":
                record = manager.get(args.service_id)
                status = record.get("status", {})
                print("Service Status")
                print("-" * 40)
                print(f"Name:        {record.get('name')}")
                print(f"Service ID:  {record.get('id')}")
                print(f"Application: {record.get('application')}")
                print(f"Prefix:      {record.get('prefix')}")
                print(f"Load state:  {status.get('load_state', 'unknown')}")
                print(f"Active:      {status.get('active_state', 'unknown')}")
                print(f"Sub-state:   {status.get('sub_state', 'unknown')}")
                print(
                    f"Enabled:     {status.get('unit_file_state', 'unknown')}"
                )

            elif args.service_command in (
                "start", "stop", "restart", "enable", "disable"
            ):
                result = getattr(
                    manager, args.service_command
                )(args.service_id)

                print(
                    f"[OK] Service {args.service_command} command completed."
                )
                print(f"Name:        {result.get('name')}")
                print(f"Service ID:  {result.get('id')}")

                status = result.get("status", {})
                print(
                    f"Active:      {status.get('active_state', 'unknown')}"
                )
                print(
                    f"Enabled:     {status.get('unit_file_state', 'unknown')}"
                )

                if args.service_command == "disable":
                    print(
                        "Note: disabling does not stop a running service."
                    )

            elif args.service_command == "delete":
                record = manager.delete(args.service_id)
                print(f"[OK] Service deleted: {record['name']}")
                print(f"Service ID: {record['id']}")

        elif args.command == "install":
            from winux.core.installer import Installer

            if args.manifest:
                if args.installer_arg:
                    raise ValueError(
                        "Use installer_args inside the manifest, not --installer-arg"
                    )

                if args.file:
                    raise ValueError(
                        "Use either an installer file or --manifest, not both"
                    )

                if args.verification_profile:
                    raise ValueError(
                        "--verification-profile cannot be used with --manifest; "
                        "define profiles inside the manifest instead"
                    )

                installer = Installer()

                print(f"Manifest: {args.manifest}")
                print(f"Target prefix: {args.prefix}")
                print("Starting batch installation...")

                result = installer.install_batch(
                    manifest_file=args.manifest,
                    prefix_name=args.prefix
                )

                for item in result["results"]:
                    status = "OK" if item["success"] else "FAILED"
                    print(f"[{status}] {item['file']}")

                    if not item["success"]:
                        print(f"  Error: {item['error']}")

                print("-" * 50)
                print(f"Total:      {result['total']}")
                print(f"Successful: {result['successful']}")
                print(f"Failed:     {result['failed']}")

                if not result["success"]:
                    raise RuntimeError("One or more installations failed")

            else:
                if not args.file:
                    raise ValueError(
                        "Provide an installer file or use --manifest"
                    )

                verification_profile = None

                if args.verification_profile:
                    profile_path = Path(
                        args.verification_profile
                    ).expanduser()

                    if profile_path.is_symlink():
                        raise ValueError(
                            "Verification profile must not be a symbolic link"
                        )

                    if not profile_path.is_file():
                        raise FileNotFoundError(
                            f"Verification profile not found: {profile_path}"
                        )

                    try:
                        with profile_path.open(
                            "r", encoding="utf-8"
                        ) as file:
                            verification_profile = json.load(file)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"Invalid verification profile JSON: {error}"
                        ) from error

                installer = Installer()

                if verification_profile is not None:
                    installer.verification_manager.validate_profile(
                        verification_profile
                    )

                print(f"Installer: {args.file}")
                print(f"Target prefix: {args.prefix}")
                print("Starting installation...")

                result = installer.install(
                    installer_file=args.file,
                    prefix_name=args.prefix,
                    timeout=args.timeout,
                    verification_profile=verification_profile,
                    installer_args=args.installer_arg,
                )

                print("[OK] Installer process completed.")
                print(f"Process status: {result['process_status']}")
                print(
                    f"Verification status: {result['verification_status']}"
                )
                print(
                    f"Verification details: {result['verification_details']}"
                )
                print(f"Install ID: {result['install_id']}")
                print(f"Log file: {result['log']}")

        elif args.command == "history":
            from winux.core.installer import Installer
            records = Installer().history(limit=args.limit)

            if not records:
                print("No installation history found.")
                return

            for record in records:
                print("-" * 60)
                print(f"ID:        {record['install_id']}")
                print(f"Date:      {record['started']}")
                print(f"Installer: {record['installer']}")
                print(f"Type:      {record['type']}")
                print(f"Prefix:    {record['prefix']}")
                print(f"Status:    {record['status']}")
                print(
                    f"Verification: {record['verification_status']}"
                )
                print(
                    f"Verification details: {record['verification_details']}"
                )
                print(f"Log:       {record['log']}")

        elif args.command == "stats":
            from winux.core.installer import Installer
            counts = Installer().stats()

            print("Winux Installation Statistics")
            print("-" * 35)
            print(f"Total installations: {counts['total']}")
            print(f"Successful:           {counts['success']}")
            print(f"Failed:               {counts['failed']}")
            print(f"Timeout:              {counts['timeout']}")
            print(f"Unknown:              {counts['unknown']}")
            print(f"Success rate:         {counts['success_rate']}%")
            print(f"Verified:             {counts['verified']}")
            print(
                f"Verification pending: {counts['verification_pending']}"
            )
            print(
                f"Verification failed:  {counts['verification_failed']}"
            )
            print(
                f"Verification unknown: {counts['verification_unknown']}"
            )

    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
