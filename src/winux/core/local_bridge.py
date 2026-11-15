"""Security policy primitives for Winux's local browser/desktop bridge."""

import hmac
import ipaddress
import math
from urllib.parse import urlsplit


class LocalBridgePolicy:
    """Validate the network boundary before an application adapter dispatches."""

    def __init__(
        self,
        bind_address="127.0.0.1",
        port=0,
        allowed_origins=(),
        auth_token=None,
        allow_missing_origin=False,
        max_body_bytes=1024 * 1024,
        request_timeout=10,
        max_concurrency=8,
    ):
        if not isinstance(bind_address, str) or not bind_address:
            raise ValueError("Bind address must be an explicit loopback IP")
        try:
            address = ipaddress.ip_address(bind_address)
        except ValueError as error:
            raise ValueError(
                "Bind address must be an explicit loopback IP"
            ) from error
        if not address.is_loopback:
            raise ValueError("LocalBridge may bind only to loopback addresses")

        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 0 <= port <= 65535
        ):
            raise ValueError("Port must be an integer between 0 and 65535")

        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes <= 0
        ):
            raise ValueError("Maximum body size must be a positive integer")

        if (
            isinstance(request_timeout, bool)
            or not isinstance(request_timeout, (int, float))
            or not math.isfinite(request_timeout)
            or request_timeout <= 0
        ):
            raise ValueError("Request timeout must be finite and positive")

        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency <= 0
        ):
            raise ValueError("Maximum concurrency must be a positive integer")

        if auth_token is not None and (
            not isinstance(auth_token, str) or not auth_token
        ):
            raise ValueError("Authentication token must be a non-empty string")

        if not isinstance(allow_missing_origin, bool):
            raise ValueError("allow_missing_origin must be a boolean")

        self.bind_address = address.compressed
        self.port = port
        if isinstance(allowed_origins, str):
            raise ValueError("allowed_origins must be a collection of origins")
        self.allowed_origins = frozenset(
            self.normalize_origin(origin) for origin in allowed_origins
        )
        self.auth_token = auth_token
        self.allow_missing_origin = allow_missing_origin
        self.max_body_bytes = max_body_bytes
        self.request_timeout = float(request_timeout)
        self.max_concurrency = max_concurrency

    @staticmethod
    def normalize_origin(origin):
        """Return a canonical HTTP(S) origin; reject paths and wildcards."""
        if not isinstance(origin, str) or not origin or origin == "null":
            raise ValueError("Origin must be an explicit HTTP(S) origin")

        try:
            parsed = urlsplit(origin)
            scheme = parsed.scheme.lower()
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise ValueError("Invalid Origin") from error

        if (
            scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise ValueError("Origin must contain only scheme, host, and port")

        hostname = hostname.lower()
        try:
            ip = ipaddress.ip_address(hostname)
            hostname = ip.compressed
            if ip.version == 6:
                hostname = f"[{hostname}]"
        except ValueError:
            try:
                hostname = hostname.encode("idna").decode("ascii")
            except UnicodeError as error:
                raise ValueError("Invalid Origin hostname") from error

        default_port = 80 if scheme == "http" else 443
        authority = hostname
        if port is not None and port != default_port:
            authority = f"{authority}:{port}"

        return f"{scheme}://{authority}"

    def validate_host(self, host_header, actual_port=None):
        """Require Host to identify this exact loopback listener."""
        if not isinstance(host_header, str) or not host_header:
            return False

        try:
            parsed = urlsplit(f"//{host_header}")
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return False

        if (
            not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return False

        expected_port = self.port if actual_port is None else actual_port
        if port != expected_port:
            return False

        try:
            host_ip = ipaddress.ip_address(hostname)
        except ValueError:
            return False

        return (
            host_ip.is_loopback
            and host_ip.compressed == self.bind_address
        )

    def validate_origin(self, origin):
        if origin is None:
            return self.allow_missing_origin

        try:
            normalized = self.normalize_origin(origin)
        except ValueError:
            return False

        return normalized in self.allowed_origins

    def authenticate(self, supplied_token):
        """Use constant-time comparison when a token is configured."""
        if self.auth_token is None:
            return True
        if not isinstance(supplied_token, str):
            return False
        return hmac.compare_digest(
            self.auth_token.encode("utf-8"),
            supplied_token.encode("utf-8"),
        )

    def validate_content_length(self, value):
        """Parse a bounded Content-Length without accepting signs or junk."""
        if value is None:
            return 0
        if not isinstance(value, str) or not value.isascii() or not value.isdigit():
            raise ValueError("Invalid Content-Length")
        length = int(value)
        if length > self.max_body_bytes:
            raise ValueError("Request body exceeds configured maximum size")
        return length
