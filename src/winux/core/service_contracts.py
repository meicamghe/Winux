"""Platform-neutral contract for Winux-managed service backends."""

import re
from typing import Protocol, Sequence, runtime_checkable


SERVICE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
SERVICE_RESTART_POLICIES = frozenset({"no", "on-failure", "always"})


@runtime_checkable
class ServiceBackend(Protocol):
    """Operations required by the service manager from a platform backend."""

    def install(
        self,
        service_id: str,
        command: Sequence[str],
        description: str,
        restart: str = "on-failure",
    ) -> str | None: ...

    def unit_exists(self, service_id: str) -> bool: ...

    def reload(self) -> object: ...

    def start(self, service_id: str) -> object: ...

    def stop(self, service_id: str) -> object: ...

    def restart(self, service_id: str) -> object: ...

    def enable(self, service_id: str) -> object: ...

    def disable(self, service_id: str) -> object: ...

    def status(self, service_id: str) -> dict[str, str]: ...

    def remove(self, service_id: str) -> bool: ...
