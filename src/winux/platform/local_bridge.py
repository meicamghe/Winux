"""HTTP server transport for Winux's local browser/desktop bridge."""

import logging
import math
from dataclasses import dataclass, field
import socket
import time
import uuid
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit

from winux.core.local_bridge import LocalBridgePolicy


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, server_address, handler_class, semaphore, bridge):
        self._semaphore = semaphore
        self._bridge = bridge
        super().__init__(server_address, handler_class)

    def process_request(self, request, client_address):
        if self._bridge._closing or not self._semaphore.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 14\r\n"
                    b"Connection: close\r\n\r\n"
                    b"Bridge is busy"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return

        with self._bridge._active_condition:
            self._bridge._active_requests += 1

        try:
            super().process_request(request, client_address)
        except Exception:
            self._semaphore.release()
            with self._bridge._active_condition:
                self._bridge._active_requests -= 1
                self._bridge._active_condition.notify_all()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._semaphore.release()
            with self._bridge._active_condition:
                self._bridge._active_requests -= 1
                self._bridge._active_condition.notify_all()


class LocalBridge:
    """Serve explicit application routes on a strictly loopback listener.

    Authentication, Host, Origin, and body-size decisions are delegated to
    LocalBridgePolicy. Application-specific routes own payload semantics.
    """

    def __init__(
        self,
        routes,
        policy=None,
        allowed_headers=("content-type", "authorization"),
    ):
        self.policy = policy if policy is not None else LocalBridgePolicy()
        if not isinstance(self.policy, LocalBridgePolicy):
            raise TypeError("policy must be a LocalBridgePolicy instance")

        self.routes = self._validate_routes(routes)
        if isinstance(allowed_headers, (str, bytes)):
            raise ValueError("Allowed headers must be a collection of names")
        self.allowed_headers = frozenset(
            self._validate_header_name(item) for item in allowed_headers
        )
        self._semaphore = threading.BoundedSemaphore(
            self.policy.max_concurrency
        )
        self._lock = threading.RLock()
        self._active_condition = threading.Condition()
        self._active_requests = 0
        self._closing = False
        self._server = None
        self._thread = None
        self.logger = logging.getLogger("winux.local_bridge")

    @staticmethod
    def _validate_header_name(value):
        if not isinstance(value, str) or not value or not value.isascii():
            raise ValueError("HTTP header names must be non-empty ASCII strings")
        if any(
            not (char.isalnum() or char in "!#$%&'*+-.^_`|~")
            for char in value
        ):
            raise ValueError("Invalid HTTP header name")
        return value.lower()

    @staticmethod
    def _validate_routes(routes):
        if not hasattr(routes, "items"):
            raise TypeError("Routes must map (method, path) pairs to handlers")

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
            if not method.isascii() or not method.isalpha():
                raise ValueError(f"Invalid route method: {method}")
            if (
                not path.startswith("/")
                or "?" in path
                or "#" in path
                or any(
                    ord(char) < 0x21 or ord(char) == 0x7F or char == "\\"
                    for char in path
                )
            ):
                raise ValueError(f"Invalid route path: {path}")
            if not callable(handler):
                raise TypeError(
                    f"Route handler for {method} {path} is not callable"
                )
            if (method, path) in validated:
                raise ValueError(f"Duplicate route: {method} {path}")
            validated[(method, path)] = handler

        return validated

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
                raise RuntimeError("Local bridge is still shutting down")

            server_type = _ThreadingHTTPServer
            if ":" in self.policy.bind_address:
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
                    self.connection.settimeout(bridge.policy.request_timeout)

                def log_message(self, _format_string, *_args):
                    # The request line can contain sensitive query parameters.
                    return

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

                def handle_expect_100(self):
                    self.send_error(417, "Expect header is not supported")
                    return False

                def _send(
                    self, status, body=b"", headers=None, origin=None,
                    allow_preflight=False,
                ):
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    if not isinstance(body, bytes):
                        status = 500
                        body = b"Internal server error"
                        headers = {"Content-Type": "text/plain; charset=utf-8"}

                    safe_headers = {}
                    try:
                        for name, value in dict(headers or {}).items():
                            if not isinstance(name, str) or not isinstance(value, str):
                                raise ValueError("Response headers must be strings")
                            bridge._validate_header_name(name)
                            if any(
                                (ord(char) < 0x20 and char != "\t")
                                or ord(char) == 0x7F
                                for char in value
                            ):
                                raise ValueError("Invalid response header")
                            reserved = {
                                "content-length",
                                "connection",
                                "access-control-allow-origin",
                                "access-control-allow-credentials",
                                "vary",
                                "x-winux-request-id",
                            }
                            if not allow_preflight:
                                reserved.update({
                                    "access-control-allow-methods",
                                    "access-control-allow-headers",
                                })
                            if name.lower() in reserved:
                                continue
                            safe_headers[name] = value
                    except (TypeError, ValueError):
                        status = 500
                        body = b"Internal server error"
                        safe_headers = {
                            "Content-Type": "text/plain; charset=utf-8"
                        }

                    self.send_response(status)
                    for name, value in safe_headers.items():
                        self.send_header(name, value)
                    if origin is not None:
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Vary", "Origin")
                    request_id = getattr(self, "_bridge_request_id", None)
                    if request_id is not None:
                        self.send_header("X-Winux-Request-ID", request_id)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if self.command != "HEAD":
                        try:
                            self.wfile.write(body)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            pass
                    self.close_connection = True
                    if request_id is not None:
                        elapsed_ms = (
                            time.monotonic() - self._bridge_started_at
                        ) * 1000
                        bridge.logger.info(
                            "request_id=%s method=%s path=%s status=%d duration_ms=%.2f",
                            request_id,
                            self.command,
                            getattr(self, "_bridge_path", "-"),
                            status,
                            elapsed_ms,
                        )

                def _reject(self, status, message, origin=None):
                    self._send(
                        status,
                        message,
                        {"Content-Type": "text/plain; charset=utf-8"},
                        origin,
                    )

                def _dispatch(self):
                    self._bridge_request_id = uuid.uuid4().hex
                    self._bridge_started_at = time.monotonic()
                    with bridge._lock:
                        if bridge._closing:
                            self._reject(503, "Bridge is shutting down")
                            return

                    if self.request_version != "HTTP/1.1":
                        self._reject(505, "HTTP/1.1 is required")
                        return

                    actual_port = bridge.address[1]
                    host_values = self.headers.get_all("Host", [])
                    if len(host_values) != 1 or not bridge.policy.validate_host(
                        host_values[0] if host_values else None,
                        actual_port=actual_port,
                    ):
                        self._reject(400, "Invalid Host header")
                        return

                    origin_values = self.headers.get_all("Origin", [])
                    if len(origin_values) > 1:
                        self._reject(403, "Origin is not allowed")
                        return
                    origin = origin_values[0] if origin_values else None
                    if not bridge.policy.validate_origin(origin):
                        self._reject(403, "Origin is not allowed")
                        return

                    try:
                        parsed = urlsplit(self.path)
                    except ValueError:
                        self._reject(400, "Invalid request target", origin)
                        return
                    self._bridge_path = parsed.path
                    if (
                        parsed.scheme
                        or parsed.netloc
                        or not parsed.path.startswith("/")
                    ):
                        self._reject(400, "Invalid request target", origin)
                        return

                    # Preflight is a policy check, not an application action.
                    # Browsers do not send the actual request's auth token here.
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
                            or not requested_headers.issubset(
                                bridge.allowed_headers
                            )
                        ):
                            self._reject(
                                403,
                                "Preflight request is not allowed",
                                origin,
                            )
                            return
                        self._send(
                            204,
                            headers={
                                "Access-Control-Allow-Methods": requested_method,
                                "Access-Control-Allow-Headers": ", ".join(
                                    sorted(requested_headers)
                                ),
                            },
                            origin=origin,
                            allow_preflight=True,
                        )
                        return

                    transfer_encodings = self.headers.get_all(
                        "Transfer-Encoding", []
                    )
                    if transfer_encodings:
                        self._reject(400, "Transfer-Encoding is not supported", origin)
                        return

                    content_lengths = self.headers.get_all("Content-Length", [])
                    if len(content_lengths) > 1:
                        self._reject(400, "Invalid Content-Length", origin)
                        return

                    try:
                        body_length = bridge.policy.validate_content_length(
                            content_lengths[0] if content_lengths else None
                        )
                    except ValueError as error:
                        status = 413 if "exceeds configured maximum" in str(error) else 400
                        self._reject(status, str(error), origin)
                        return

                    if bridge.policy.auth_token is not None:
                        authorization_values = self.headers.get_all(
                            "Authorization", []
                        )
                        authorization = (
                            authorization_values[0]
                            if len(authorization_values) == 1
                            else ""
                        )
                        scheme, separator, token = authorization.partition(" ")
                        supplied_token = (
                            token if separator and scheme.lower() == "bearer" else None
                        )
                        if not bridge.policy.authenticate(supplied_token):
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

                    handler = bridge.routes.get((self.command, parsed.path))
                    if handler is None:
                        self._reject(404, "Route not found", origin)
                        return

                    request = LocalBridgeRequest(
                        method=self.command,
                        path=parsed.path,
                        query=parsed.query,
                        headers=dict(self.headers.items()),
                        body=body,
                        client_address=self.client_address,
                        request_id=self._bridge_request_id,
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
                        self._send(
                            response.status,
                            response.body,
                            response.headers,
                            origin,
                        )
                    except Exception:
                        bridge.logger.error(
                            "LocalBridge route failed request_id=%s: %s %s",
                            self._bridge_request_id,
                            self.command,
                            parsed.path,
                        )
                        self._send(
                            500,
                            b"Internal server error",
                            {"Content-Type": "text/plain; charset=utf-8"},
                            origin,
                        )

            server = server_type(
                (self.policy.bind_address, self.policy.port),
                RequestHandler,
                self._semaphore,
                self,
            )
            self._server = server
            self._closing = False
            self._thread = threading.Thread(
                target=server.serve_forever,
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

        stop_deadline = time.monotonic() + float(timeout)

        with self._lock:
            server = self._server
            thread = self._thread
            if server is None:
                return True
            self._closing = True

        if thread is not None and thread.is_alive():
            server.shutdown()
        server.server_close()

        with self._active_condition:
            while self._active_requests:
                remaining = stop_deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._active_condition.wait(timeout=remaining)

        if thread is not None:
            thread.join(
                timeout=max(0.0, stop_deadline - time.monotonic())
            )

        stopped = (
            (thread is None or not thread.is_alive())
            and self._active_requests == 0
        )
        if stopped:
            with self._lock:
                self._server = None
                self._thread = None
        return stopped


@dataclass(frozen=True)
class LocalBridgeRequest:
    method: str
    path: str
    query: str
    headers: dict
    body: bytes
    client_address: tuple
    request_id: str = ""


@dataclass(frozen=True)
class LocalBridgeResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
