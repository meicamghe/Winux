import sys
import unittest
from unittest.mock import Mock, patch

from winux import service_runner


SERVICE_ID = "a" * 32


class ServiceRunnerTests(unittest.TestCase):
    def test_rejects_missing_service_id(self):
        with patch.object(sys, "argv", ["service_runner.py"]):
            result = service_runner.main()

        self.assertEqual(result, 2)

    def test_rejects_invalid_service_id(self):
        with patch.object(
            sys, "argv", ["service_runner.py", "invalid-id"]
        ):
            result = service_runner.main()

        self.assertEqual(result, 2)

    def test_refuses_to_run_as_root(self):
        with (
            patch.object(
                sys, "argv", ["service_runner.py", SERVICE_ID]
            ),
            patch.object(service_runner.os, "geteuid", return_value=0),
            patch(
                "winux.core.services.ServiceManager"
            ) as manager_class,
            patch(
                "winux.core.runner.ApplicationRunner"
            ) as runner_class,
        ):
            result = service_runner.main()

        self.assertEqual(result, 1)
        manager_class.assert_not_called()
        runner_class.assert_not_called()

    def test_runs_service_in_foreground(self):
        definition = {
            "id": SERVICE_ID,
            "prefix": "office-prefix",
            "application_id": "emwat",
        }

        manager = Mock()
        manager.get_definition.return_value = definition

        runner = Mock()
        runner.run_foreground.return_value = 17

        with (
            patch.object(
                sys, "argv", ["service_runner.py", SERVICE_ID]
            ),
            patch.object(service_runner.os, "geteuid", return_value=1000),
            patch(
                "winux.core.services.ServiceManager",
                return_value=manager,
            ),
            patch(
                "winux.core.runner.ApplicationRunner",
                return_value=runner,
            ),
        ):
            result = service_runner.main()

        self.assertEqual(result, 17)
        manager.get_definition.assert_called_once_with(SERVICE_ID)
        runner.run_foreground.assert_called_once_with(
            "office-prefix",
            "emwat",
        )


if __name__ == "__main__":
    unittest.main()
