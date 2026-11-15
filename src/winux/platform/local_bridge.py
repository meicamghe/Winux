"""Secure loopback HTTP transport for application-specific adapters."""

import ipaddress
import logging
import math
import socket
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LocalBridgeRequest:
    method: str
    path: str
    query: str
    headers: dict
    body: bytes
    client_address: tuple


@dataclass(frozen=True)
class LocalBridgeResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False


class LocalBridge:
    """Run explicitly registered HTTP routes on a loopback-only listener.

    Route handlers receive a LocalBridgeRequest and return a
    LocalBridgeResponse. The transport deliberately knows nothing about
    application-specific query commands or payload schemas.
    """

    def __init__(
        self,
        routes,
        host="127.0.0.1",
        port=0,
        allowed_origins=(),
        authenticate=None,
        allow_originless=True,
        allowed_headers=("content-type", "authorization"),
        max_body_bytes=1024 * 1024,
        request_timeout=5.0,
        max_concurrency=8,
    ):
        try:
            address = ipaddress.ip_address(host)
        except (TypeError, ValueError) as error:
            raise ValueError("Bridge host must be a loopback IP address") from error
        if not address.is_loopback:
            raise ValueError("Bridge host must be a loopback IP address")

        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 0 <= port <= 65535
        ):
            raise ValueError("Bridge port must be an integer from 0 to 65535")

        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes <= 0
        ):
            raise ValueError("Maximum request body size must be a positive integer")

        if (
            isinstance(request_timeout, bool)
            or not isinstance(request_timeout, (int, float))
            or not math.isfinite(request_timeout)
            or request_timeout <= 0
        ):
            raise ValueError("Request timeout must be a finite positive number")

        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency <= 0
        ):
            raise ValueError("Maximum concurrency must be a positive integer")

        if not isinstance(allow_originless, bool):
            raise ValueError("allow_originless must be a boolean")

        if authenticate is not None and not callable(authenticate):
            raise TypeError("Authentication hook must be callable")

        self.host = str(address)
        self.port = port
        self.allowed_origins = self._validate_origins(allowed_origins)
        self.allow_originless = allow_originless
        self.allowed_headers = frozenset(
            self._validate_header_name(item) for item in allowed_headers
        )
        self.max_body_bytes = max_body_bytes
        self.request_timeout = float(request_timeout)
        self.authenticate = authenticate
        self.routes = self._validate_routes(routes)
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._lock = threading.RLock()
        self._closing = False
        self._server = None
        self._thread = None
        self.logger = logging.getLogger("winux.local_bridge")

    @staticmethod
    def _validate_header_name(value):
        if not isinstance(value, str) or not value:
            raise ValueError("HTTP header names must be non-empty strings")
        if any(
            not (char.isalnum() or char in "!#$%&'*+-.^_`|~")
            for char in value
        ):
            raise ValueError("Invalid HTTP header name")
        return value.lower()

    @classmethod
    def _validate_origins(cls, origins):
        if isinstance(origins, (str, bytes)):
            raise ValueError("Allowed origins must be a collection of exact origins")
        try:
            values = tuple(origins)
        except TypeError as error:
            raise ValueError("Allowed origins must be iterable") from error

        validated = set()
        for origin in values:
            if not isinstance(origin, str) or not origin:
                raise ValueError("Allowed origins must be non-empty strings")
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Invalid browser origin: {origin}")
            hostname = parsed.hostname
            if not hostname:
                raise ValueError(f"Invalid browser origin: {origin}")
            if hostname.lower() != "localhost":
                try:
                    if not ipaddress.ip_address(hostname).is_loopback:
                        raise ValueError(
                            "Browser origins must use loopback hosts"
                        )
                except ValueError as error:
                    if str(error) == "Browser origins must use loopback hosts":
                        raise
                    raise ValueError(
                        "Browser origins must use loopback hosts"
                    ) from error
            try:
                parsed.port
            except ValueError as error:
                raise ValueError(f"Invalid browser origin: {origin}") from error
            if parsed.geturl() != origin:
                raise ValueError(f"Origin must use its exact canonical form: {origin}")
            validated.add(origin)

        return frozenset(validated)

    @staticmethod
    def _validate_routes(routes):
        if not hasattr(routes, "items"):
            raise TypeError("Routes must be a mapping of (method, path) to handlers")
        validated = {}
        for key, handler in routes.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not isinstance(key[0], str)
                or not isinstance(key[1], str)
            ):
                raise ValueError("Route keys must be (method, path) tuples")
            method, path = key
            method = method.upper()
            if not method.isalpha():
                raise ValueError(f"Invalid route method: {method}")
            if not path.startswith("/") or "?" in path or "#" in path:
                raise ValueError(f"Invalid route path: {path}")
            if not callable(handler):
                raise TypeError(f"Route handler for {method} {path} is not callable")
            route = (method, path)
            if route in validated:
                raise ValueError(f"Duplicate route: {method} {path}")
            validated[route] = handler
        return validated

    @staticmethod
    def _host_header_is_loopback(value, port):
        if not isinstance(value, str) or not value:
            return False
        parsed = urlsplit("//" + value)
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.path or parsed.query or parsed.fragment:
            return False
        try:
            host_port = parsed.port
        except ValueError:
            return False
        hostname = parsed.hostname
        if host_port != port or not hostname:
            return False
        if hostname.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False

    @property
    def address(self):
        if self._server is None:
            return None
        return self._server.server_address

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.is_running:
                raise RuntimeError("Local bridge is already running")
            if self._server is not None:
                raise RuntimeError("Local bridge has already been shut down")
            self._closing = False
            server_type = _ThreadingHTTPServer
            if ":" in self.host:
                server_type = type(
                    "IPv6ThreadingHTTPServer",
                    (_ThreadingHTTPServer,),
                    {"address_family": socket.AF_INET6},
                )
            bridge = self

            class RequestHandler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"

                def setup(self):
                    super().setup()
                    self.connection.settimeout(bridge.request_timeout)

                def log_message(self, format_string, *args):
                    bridge.logger.info("LocalBridge: %s", format_string % args)

                def do_GET(self):
                    self._dispatch()

                def do_HEAD(self):
                    self._dispatch()

                def do_POST(self):
                    self._dispatch()

                def do_PUT(self):
                    self._dispatch()

                def do_PATCH(self):
                    self._dispatch()

                def do_DELETE(self):
                    self._dispatch()

                def do_OPTIONS(self):
                    self._dispatch()

                def _send(self, response, origin=None, head_only=False):
                    body = response.body
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    if not isinstance(body, bytes):
                        body = b""
                        response = LocalBridgeResponse(
                            status=500,
                            body=b"Invalid adapter response",
                        )

                    self.send_response(response.status)
                    response_headers = dict(response.headers)
                    for key in tuple(response_headers):
                        if key.lower() in {
                            "content-length",
                            "connection",
                            "access-control-allow-origin",
                            "access-control-allow-credentials",
                            "access-control-allow-methods",
                            "access-control-allow-headers",
                        }:
                            response_headers.pop(key)

                    for key, value in response_headers.items():
                        self.send_header(key, str(value))

                    if origin is not None:
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Vary", "Origin")

                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if not head_only:
                        try:
                            self.wfile.write(body)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    self.close_connection = True

                def _reject(self, status, message, origin=None):
                    self._send(
                        LocalBridgeResponse(
                            status=status,
                            body=message.encode("utf-8"),
                            headers={"Content-Type": "text/plain; charset=utf-8"},
                        ),
                        origin=origin,
                        head_only=self.command == "HEAD",
                    )

                def _dispatch(self):
                    if not bridge._slots.acquire(blocking=False):
                        self._reject(503, "Bridge is busy")
                        return

                    try:
                        with bridge._lock:
                            if bridge._closing:
                                self._reject(503, "Bridge is shutting down")
                                return

                        server_port = bridge.address[1]
                        if not bridge._host_header_is_loopback(
                            self.headers.get("Host"), server_port
                        ):
                            self._reject(400, "Invalid Host header")
                            return

                        origin = self.headers.get("Origin")
                        if origin is None:
                            if not bridge.allow_originless:
                                self._reject(403, "Origin is required")
                                return
                        elif origin not in bridge.allowed_origins:
                            self._reject(403, "Origin is not allowed")
                            return

                        if self.headers.get("Transfer-Encoding") is not None:
                            self._reject(400, "Transfer-Encoding is not supported", origin)
                            return

                        length_value = self.headers.get("Content-Length", "0")
                        if not length_value.isdigit():
                            self._reject(400, "Invalid Content-Length", origin)
                            return
                        body_length = int(length_value)
                        if body_length > bridge.max_body_bytes:
                            self._reject(413, "Request body is too large", origin)
                            return

                        if bridge.authenticate is not None:
                            try:
                                authenticated = bridge.authenticate(dict(self.headers))
                            except Exception:
                                bridge.logger.exception("LocalBridge authentication hook failed")
                                authenticated = False
                            if not authenticated:
                                self._reject(401, "Authentication required", origin)
                                return

                        try:
                            body = self.rfile.read(body_length)
                        except (TimeoutError, OSError):
                            self._reject(408, "Request body timed out", origin)
                            return
                        if len(body) != body_length:
                            self._reject(400, "Incomplete request body", origin)
                            return

                        parsed = urlsplit(self.path)
                        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                            self._reject(400, "Invalid request target", origin)
                            return

                        if self.command == "OPTIONS" and origin is not None:
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
                            route_methods = {
                                method for method, path in bridge.routes
                                if path == parsed.path
                            }
                            if (
                                requested_method not in route_methods
                                or not requested_headers.issubset(bridge.allowed_headers)
                            ):
                                self._reject(403, "Preflight request is not allowed", origin)
                                return
                            self._send(
                                LocalBridgeResponse(
                                    status=204,
                                    headers={
                                        "Access-Control-Allow-Methods": requested_method,
                                        "Access-Control-Allow-Headers": ", ".join(
                                            sorted(requested_headers)
                                        ),
                                    },
                                ),
                                origin=origin,
                            )
                            return

                        handler = bridge.routes.get((self.command, parsed.path))
                        if handler is None:
                            self._reject(404, "Route not found", origin)
                            return

                        request = LocalBridgeRequest(
                            method=self.command,
                            path=parsed.path,
                            query=parsed.query,
                            headers=dict(self.headers),
                            body=body,
                            client_address=self.client_address,
                        )
                        try:
                            response = handler(request)
                            if not isinstance(response, LocalBridgeResponse):
                                raise TypeError(
                                    "Route handlers must return LocalBridgeResponse"
                                )
                            if (
                                isinstance(response.status, bool)
                                or not isinstance(response.status, int)
                                or not 100 <= response.status <= 599
                            ):
                                raise ValueError("Invalid HTTP response status")
                        except Exception:
                            bridge.logger.exception(
                                "LocalBridge route handler failed: %s %s",
                                self.command,
                                parsed.path,
                            )
                            response = LocalBridgeResponse(
                                status=500,
                                body=b"Internal server error",
                                headers={"Content-Type": "text/plain; charset=utf-8"},
                            )
                        self._send(
                            response,
                            origin=origin,
                            head_only=self.command == "HEAD",
                        )
                    finally:
                        bridge._slots.release()

            self._server = server_type((self.host, self.port), RequestHandler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                kwargs={"poll_interval": 0.05},
                name="winux-local-bridge",
                daemon=True,
            )
            self._thread.start()
        return self.address

    def shutdown(self, timeout=5.0):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("Shutdown timeout must be finite and non-negative")

        with self._lock:
            server = self._server
            thread = self._thread
            if server is None:
                return True
            self._closing = True

        if thread is not None and thread.is_alive():
            server.shutdown()
            thread.join(timeout=float(timeout))
        server.server_close()

        stopped = thread is None or not thread.is_alive()
        with self._lock:
            self._server = None
            self._thread = None
        return stopped
