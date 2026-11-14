from importlib.metadata import entry_points

from winux.runtime.wine import WineRuntime


class RuntimeManager:
    """Discover, register and select compatibility runtimes."""

    ENTRY_POINT_GROUP = "winux.runtimes"
    REQUIRED_METHODS = (
        "is_available",
        "version",
        "validate_prefix",
        "create_prefix",
        "run",
        "install",
        "query_registry",
        "uninstall",
    )

    def __init__(self, default_runtime="wine", discover=True):
        self._runtimes = {}
        self._default_runtime = default_runtime

        self.register(WineRuntime())

        if discover:
            self.discover()

        if default_runtime not in self._runtimes:
            raise ValueError(f"Unknown default runtime: {default_runtime}")

    def register(self, runtime):
        name = getattr(runtime, "name", None)

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Runtime must have a valid name")

        if name != name.strip():
            raise ValueError("Runtime name cannot contain surrounding whitespace")

        missing = [
            method
            for method in self.REQUIRED_METHODS
            if not callable(getattr(runtime, method, None))
        ]
        if missing:
            raise TypeError(
                f"Runtime '{name}' is missing required methods: "
                + ", ".join(missing)
            )

        if name in self._runtimes:
            raise ValueError(f"Runtime already registered: {name}")

        self._runtimes[name] = runtime

    def discover(self):
        """Load third-party runtimes registered as Python entry points."""
        try:
            discovered = entry_points(group=self.ENTRY_POINT_GROUP)
        except Exception:
            return

        for entry_point in discovered:
            try:
                runtime_factory = entry_point.load()
                runtime = runtime_factory() if callable(runtime_factory) else runtime_factory
                self.register(runtime)
            except Exception:
                continue

    def get(self, name=None):
        name = name or self._default_runtime

        try:
            return self._runtimes[name]
        except KeyError:
            raise ValueError(f"Unknown runtime: {name}") from None

    def set_default(self, name):
        runtime = self.get(name)

        if not runtime.is_available():
            raise RuntimeError(f"Runtime is not available: {name}")

        self._default_runtime = name

    def get_default_name(self):
        return self._default_runtime

    def list(self):
        return {
            name: {
                "available": runtime.is_available(),
                "default": name == self._default_runtime,
            }
            for name, runtime in self._runtimes.items()
        }
