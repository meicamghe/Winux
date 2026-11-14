from winux.runtime.manager import RuntimeManager


def check_runtime(runtime_manager=None):
    print("Winux System Diagnostics")
    print("-" * 35)

    try:
        manager = runtime_manager or RuntimeManager()
        name = manager.get_default_name()
        runtime = manager.get(name)

        if not runtime.is_available():
            print(f"[FAIL] Runtime '{name}' is not available.")
            return False

        print(f"[OK] Runtime: {name}")

        try:
            print(f"[OK] Version: {runtime.version()}")
        except Exception as error:
            print(f"[FAIL] Runtime version check failed: {error}")
            return False

        return True

    except Exception as error:
        print(f"[FAIL] Runtime check failed: {error}")
        return False
