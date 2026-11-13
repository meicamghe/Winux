import shutil
import subprocess

def check_wine():
    print("Winux System Diagnostics")
    print("-" * 35)

    wine = shutil.which("wine")

    if not wine:
        print("[FAIL] Wine is not installed.")
        return

    print(f"[OK] Wine found: {wine}")

    try:
        result = subprocess.run(
            [wine, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        print(f"[OK] Version: {result.stdout.strip()}")
    except Exception as error:
        print(f"[FAIL] Wine check failed: {error}")
