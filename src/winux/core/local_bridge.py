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

import http.server
import ipaddress
import logging
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BridgeRequest:
    method: str
    path: str
    target: str
    headers: object
    body: bytes
    client_address: tuple
    request_id: str


@dataclass
class BridgeResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class _BoundedHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, handler, policy):
        self.policy = policy
        self._slots = threading.BoundedSemaphore(policy.max_concurrency)
        self._active_condition = threading.Condition()
        self._active = 0
        self._stopping = False
        self.address_family = (
            socket.AF_INET6 if ":" in policy.bind_address else socket.AF_INET
        )
        super().__init__(address, handler, bind_and_activate=True)

    def process_request(self, request, client_address):
        if self._stopping or not self._slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return

        with self._active_condition:
            self._active += 1

        try:
            super().process_request(request, client_address)
        except Exception:
            with self._active_condition:
                self._active -= 1
                self._active_condition.notify_all()
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._active_condition:
                self._active -= 1
                self._active_condition.notify_all()
            self._slots.release()

    def wait_for_handlers(self, timeout):
        deadline = time.monotonic() + timeout
        with self._active_condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._active_condition.wait(remaining)
        return True


class LocalBridge:
    """Small bounded HTTP transport; application behavior lives in routes."""

    def __init__(
        self,
        policy,
        routes=None,
        allowed_methods=("GET", "POST"),
        allowed_headers=("authorization", "content-type"),
    ):
        if not isinstance(policy, LocalBridgePolicy):
            raise TypeError("policy must be a LocalBridgePolicy")

        self.policy = policy
        self.routes = {}
        for key, handler in (routes or {}).items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not isinstance(key[0], str)
                or not isinstance(key[1], str)
                or not key[1].startswith("/")
                or "?" in key[1]
                or "#" in key[1]
                or not callable(handler)
            ):
                raise ValueError("Routes must map (METHOD, /path) to callables")
            method = key[0].upper()
            if method in {"OPTIONS", "CONNECT", "TRACE"}:
                raise ValueError("Route method is reserved or unsupported")
            self.routes[(method, key[1])] = handler

        self.allowed_methods = frozenset(
            method.upper() for method in allowed_methods
        )
        self.allowed_headers = frozenset(
            header.lower() for header in allowed_headers
        )
        self.logger = logging.getLogger("winux.local_bridge")
        self._server = None
        self._thread = None

    @property
    def address(self):
        if self._server is None:
            return None
        return self._server.server_address

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running:
            raise RuntimeError("LocalBridge is already running")

        handler_type = self._make_handler()
        try:
            server = _BoundedHTTPServer(
                (self.policy.bind_address, self.policy.port),
                handler_type,
                self.policy,
            )
        except OSError as error:
            raise OSError(
                f"Unable to bind LocalBridge to "
                f"{self.policy.bind_address}:{self.policy.port}: {error}"
            ) from error

        server.timeout = self.policy.request_timeout
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="winux-local-bridge",
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()
        return self.address

    def shutdown(self, timeout=5):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Shutdown timeout must be finite and positive")

        if self._server is None:
            return True

        server = self._server
        thread = self._thread
        server._stopping = True
        server.shutdown()
        server.server_close()

        if thread is not None:
            thread.join(timeout)

        remaining = max(0, timeout)
        drained = server.wait_for_handlers(remaining)
        self._server = None
        self._thread = None

        if thread is not None and thread.is_alive():
            raise TimeoutError("LocalBridge listener did not stop in time")
        if not drained:
            raise TimeoutError("LocalBridge handlers did not drain in time")
        return True

    def _make_handler(self):
        bridge = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(bridge.policy.request_timeout)

            def log_message(self, _format, *args):
                # Request details and headers are intentionally not logged.
                return

            def handle_expect_100(self):
                self.send_error(417, "Expect header is not supported")
                return False

            def _send(self, status, body=b"", headers=None, origin=None):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                if not isinstance(body, bytes):
                    status = 500
                    body = b"Internal Server Error"
                    headers = {}
                headers = dict(headers or {})
                forbidden = {"content-length", "transfer-encoding", "connection"}
                safe_headers = {}
                for name, value in headers.items():
                    if (
                        not isinstance(name, str)
                        or not isinstance(value, (str, int))
                        or name.lower() in forbidden
                        or any(ch in str(name) + str(value) for ch in "\r\n")
                    ):
                        continue
                    safe_headers[name] = str(value)

                self.send_response(status)
                for name, value in safe_headers.items():
                    self.send_header(name, value)
                if origin is not None and bridge.policy.validate_origin(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                self.close_connection = True

            def _reject(self, status, message):
                self._send(status, message)

            def _dispatch(self):
                started = time.monotonic()
                request_id = uuid.uuid4().hex
                origin = self.headers.get("Origin")

                if not bridge.policy.validate_host(
                    self.headers.get("Host"),
                    actual_port=bridge.address[1],
                ):
                    self._reject(400, "Invalid Host")
                    return

                if not bridge.policy.validate_origin(origin):
                    self._reject(403, "Origin is not allowed")
                    return

                if self.headers.get("Transfer-Encoding") is not None:
                    self._reject(400, "Transfer-Encoding is not supported")
                    return

                try:
                    lengths = self.headers.get_all("Content-Length") or []
                    if len(lengths) > 1:
                        raise ValueError("Multiple Content-Length headers")
                    length = bridge.policy.validate_content_length(
                        lengths[0] if lengths else None
                    )
                except ValueError:
                    self._reject(413, "Invalid or oversized request body")
                    return

                if self.command == "OPTIONS":
                    requested_method = self.headers.get(
                        "Access-Control-Request-Method", ""
                    ).upper()
                    requested_headers = {
                        item.strip().lower()
                        for item in self.headers.get(
                            "Access-Control-Request-Headers", ""
                        ).split(",")
                        if item.strip()
                    }
                    if (
                        origin is None
                        or requested_method not in bridge.allowed_methods
                        or not requested_headers.issubset(
                            bridge.allowed_headers
                        )
                    ):
                        self._reject(403, "Preflight is not allowed")
                        return
                    self._send(
                        204,
                        headers={
                            "Access-Control-Allow-Methods": ", ".join(
                                sorted(bridge.allowed_methods)
                            ),
                            "Access-Control-Allow-Headers": ", ".join(
                                sorted(bridge.allowed_headers)
                            ),
                        },
                        origin=origin,
                    )
                    return

                authorization = self.headers.get("Authorization", "")
                token = None
                if authorization.startswith("Bearer "):
                    token = authorization[7:]
                if not bridge.policy.authenticate(token):
                    self._reject(401, "Authentication required")
                    return

                try:
                    body = self.rfile.read(length) if length else b""
                except (OSError, TimeoutError):
                    self._reject(408, "Request body timed out")
                    return
                if len(body) != length:
                    self._reject(400, "Incomplete request body")
                    return

                try:
                    target = self.path
                    parsed = urlsplit(target)
                    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                        self._reject(400, "Invalid request target")
                        return
                    route = bridge.routes.get((self.command, parsed.path))
                    if route is None:
                        self._reject(404, "Not Found")
                        return

                    request = BridgeRequest(
                        method=self.command,
                        path=parsed.path,
                        target=target,
                        headers=self.headers,
                        body=body,
                        client_address=self.client_address,
                        request_id=request_id,
                    )
                    response = route(request)
                    if not isinstance(response, BridgeResponse):
                        raise TypeError("Route must return BridgeResponse")
                    self._send(
                        response.status,
                        response.body,
                        response.headers,
                        origin=origin,
                    )
                except Exception:
                    bridge.logger.exception(
                        "LocalBridge route failed (request_id=%s, path=%s)",
                        request_id,
                        parsed.path,
                    )
                    self._send(500, "Internal Server Error", origin=origin)
                finally:
                    bridge.logger.debug(
                        "LocalBridge request completed "
                        "(request_id=%s, method=%s, status=%s, duration=%.3f)",
                        request_id,
                        self.command,
                        getattr(self, "_last_status", "handled"),
                        time.monotonic() - started,
                    )

            do_GET = _dispatch
            do_POST = _dispatch
            do_PUT = _dispatch
            do_PATCH = _dispatch
            do_DELETE = _dispatch
            do_HEAD = _dispatch
            do_OPTIONS = _dispatch

        return Handler
