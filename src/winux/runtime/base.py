from abc import ABC, abstractmethod
from pathlib import Path


class Runtime(ABC):
    """Abstract interface for Windows application compatibility runtimes."""

    @abstractmethod
    def is_available(self):
        raise NotImplementedError

    @abstractmethod
    def version(self):
        raise NotImplementedError

    @abstractmethod
    def validate_prefix(self, prefix_path: Path) -> bool:
        raise NotImplementedError

    @abstractmethod
    def create_prefix(self, prefix_path: Path, architecture: str):
        raise NotImplementedError

    @abstractmethod
    def run(self, prefix_path: Path, executable: Path, args=None, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def install(self, prefix_path: Path, installer: Path, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def query_registry(self, prefix_path: Path, key: str, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def uninstall(self, prefix_path: Path, command, **kwargs):
        raise NotImplementedError
