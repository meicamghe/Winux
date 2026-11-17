import unittest
from unittest.mock import patch

from winux.platform.distribution import (
    detect_distribution,
    detect_host_environment,
    detect_init_system,
    detect_package_managers,
)


class DistributionDetectionTests(unittest.TestCase):
    def test_distribution_fields_are_normalized(self):
        result = detect_distribution({
            "ID": "Ubuntu",
            "ID_LIKE": "debian",
            "PRETTY_NAME": "Ubuntu 24.04.1 LTS",
            "VERSION_ID": "24.04",
        })
        self.assertEqual(result, {
            "id": "ubuntu",
            "id_like": "debian",
            "name": "Ubuntu 24.04.1 LTS",
            "version_id": "24.04",
        })

    def test_missing_os_release_returns_safe_unknown_values(self):
        with patch(
            "winux.platform.distribution.platform.freedesktop_os_release",
            side_effect=OSError("missing os-release"),
        ):
            result = detect_distribution()
        self.assertEqual(result["id"], "unknown")
        self.assertEqual(result["name"], "Unknown Linux")

    def test_package_managers_are_detected_without_running_commands(self):
        available = {"apt-get", "systemd"}
        result = detect_package_managers(
            command_lookup=lambda command: "/usr/bin/" + command
            if command in available else None
        )
        self.assertEqual(result, ["apt"])

    def test_package_manager_lookup_errors_are_ignored(self):
        result = detect_package_managers(
            command_lookup=lambda _command: (_ for _ in ()).throw(OSError("PATH unavailable"))
        )
        self.assertEqual(result, [])

    def test_init_system_aliases_are_normalized(self):
        self.assertEqual(detect_init_system("/usr/lib/systemd/systemd"), "systemd")
        self.assertEqual(detect_init_system("/sbin/openrc-init"), "openrc")
        self.assertEqual(detect_init_system("/usr/bin/s6-svscan"), "s6")
        self.assertEqual(detect_init_system("/usr/bin/tini"), "container-init")

    def test_unknown_pid1_is_reported_by_name(self):
        self.assertEqual(detect_init_system("/usr/local/bin/custom-init"), "custom-init")

    def test_host_environment_is_read_only_metadata(self):
        with (
            patch("winux.platform.distribution.detect_distribution", return_value={"id": "ubuntu"}),
            patch("winux.platform.distribution.detect_package_managers", return_value=["apt"]),
            patch("winux.platform.distribution.detect_init_system", return_value="systemd"),
        ):
            self.assertEqual(detect_host_environment(), {
                "distribution": {"id": "ubuntu"},
                "package_managers": ["apt"],
                "init_system": "systemd",
            })


if __name__ == "__main__":
    unittest.main()
