"""Discover and select platform service backends."""

import logging
from importlib.metadata import entry_points

from winux.core.service_contracts import ServiceBackend
from winux.platform.service_backend import SystemdUserBackend


class ServiceBackendManager:
    """Register and discover implementations of the service backend contract."""

    ENTRY_POINT_GROUP = "winux.service_backends"

    def __init__(self, default_backend="systemd", discover=True):
        self._backends = {}
        self._default_backend = default_backend
        self._plugin_errors = []
        self.logger = logging.getLogger("winux.platform.service_backends")

        self.register("systemd", SystemdUserBackend)

        if discover:
            self.discover()

        if default_backend not in self._backends:
            raise ValueError(f"Unknown default service backend: {default_backend}")

    def register(self, name, backend_factory):
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("Service backend must have a valid name")
        if name in self._backends:
            raise ValueError(f"Service backend already registered: {name}")

        if isinstance(backend_factory, ServiceBackend):
            self._backends[name] = backend_factory
            return

        if callable(backend_factory):
            self._backends[name] = backend_factory
            return

        if not isinstance(backend_factory, ServiceBackend):
            raise TypeError(
                f"Service backend '{name}' does not implement the Winux service contract"
            )
        self._backends[name] = backend_factory

    def _record_plugin_error(self, plugin_name, stage, error):
        record = {
            "plugin": str(plugin_name),
            "stage": stage,
            "error": f"{type(error).__name__}: {error}",
        }
        self._plugin_errors.append(record)
        self.logger.warning(
            "Service backend plugin '%s' failed during %s: %s",
            plugin_name,
            stage,
            record["error"],
        )

    def discover(self):
        """Load third-party service backends registered as Python entry points."""
        try:
            discovered = entry_points(group=self.ENTRY_POINT_GROUP)
        except Exception as error:
            self._record_plugin_error("<entry-point-discovery>", "discovery", error)
            return

        for entry_point in discovered:
            name = getattr(entry_point, "name", "<unknown>")
            try:
                factory = entry_point.load()
            except Exception as error:
                self._record_plugin_error(name, "load", error)
                continue

            try:
                self.register(name, factory)
            except Exception as error:
                self._record_plugin_error(name, "registration", error)

    def get(self, name=None):
        if name is None:
            name = self._default_backend
        if not isinstance(name, str) or not name:
            raise ValueError(f"Invalid service backend name: {name!r}")
        try:
            backend = self._backends[name]
        except KeyError:
            raise ValueError(f"Unknown service backend: {name}") from None

        if not isinstance(backend, ServiceBackend):
            if not callable(backend):
                raise TypeError(
                    f"Service backend '{name}' is neither a backend nor a factory"
                )
            backend = backend()
            if not isinstance(backend, ServiceBackend):
                raise TypeError(
                    f"Service backend '{name}' does not implement the Winux service contract"
                )
            self._backends[name] = backend

        return backend

    def set_default(self, name):
        self.get(name)
        self._default_backend = name

    def get_default_name(self):
        return self._default_backend

    def list(self):
        return {
            name: {
                "default": name == self._default_backend,
                "backend": (
                    getattr(backend, "__name__", type(backend).__name__)
                    if callable(backend)
                    else type(backend).__name__
                ),
                "loaded": isinstance(backend, ServiceBackend),
            }
            for name, backend in self._backends.items()
        }

    def plugin_errors(self):
        return [error.copy() for error in self._plugin_errors]
