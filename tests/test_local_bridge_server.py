import http.client
import socket
import threading
import time
import unittest

from winux.core.local_bridge import LocalBridgePolicy
from winux.platform.local_bridge import (
    LocalBridge,
    LocalBridgeRequest,
    LocalBridgeResponse,
)


class LocalBridgeServerTests(unittest.TestCase):
    def make_bridge(self, **kwargs):
        policy = kwargs.pop(
            "policy",
            LocalBridgePolicy(allow_missing_origin=True),
        )
        routes = kwargs.pop(
            "routes",
            {
                ("GET", "/health"): lambda request: LocalBridgeResponse(
                    body=b"ok",
                    headers={"Content-Type": "text/plain"},
                ),
                ("POST", "/echo"): lambda request: LocalBridgeResponse(
                    body=request.body,
                ),
            },
        )
        bridge = LocalBridge(routes=routes, policy=policy, **kwargs)
        bridge.start()
        self.addCleanup(bridge.shutdown)
        return bridge

    def request(self, bridge, method="GET", path="/health", headers=None, body=None):
        host, port = bridge.address[:2]
        host_header = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        request_headers = {"Host": host_header}
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection(host, port, timeout=2)
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        result = (response.status, response.read(), dict(response.getheaders()))
        connection.close()
        return result

    def test_serves_explicit_loopback_route(self):
        bridge = self.make_bridge()
        status, body, headers = self.request(bridge)

        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        self.assertEqual(headers["Content-Type"], "text/plain")

    def test_ipv6_loopback_listener_when_available(self):
        try:
            bridge = LocalBridge(
                routes={
                    ("GET", "/health"): lambda request: LocalBridgeResponse(
                        body=b"ipv6"
                    )
                },
                policy=LocalBridgePolicy(
                    bind_address="::1",
                    allow_missing_origin=True,
                ),
            )
            bridge.start()
        except OSError as error:
            self.skipTest(f"IPv6 loopback is unavailable: {error}")

        self.addCleanup(bridge.shutdown)
        status, body, _ = self.request(bridge)

        self.assertEqual(status, 200)
        self.assertEqual(body, b"ipv6")

    def test_rejects_invalid_host_and_port_before_dispatch(self):
        called = []
        bridge = self.make_bridge(
            routes={
                ("GET", "/health"): lambda request: (
                    called.append(True) or LocalBridgeResponse(body=b"ok")
                )
            }
        )
        status, body, _ = self.request(
            bridge,
            headers={"Host": "127.0.0.1:1"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(body, b"Invalid Host header")
        self.assertEqual(called, [])

    def test_rejects_unlisted_origin_without_dispatch(self):
        called = []
        policy = LocalBridgePolicy(
            allowed_origins=("http://localhost:3000",),
        )
        bridge = self.make_bridge(
            policy=policy,
            routes={
                ("GET", "/health"): lambda request: (
                    called.append(True) or LocalBridgeResponse(body=b"ok")
                )
            },
        )
        status, body, _ = self.request(
            bridge,
            headers={"Origin": "http://localhost.evil:3000"},
        )

        self.assertEqual(status, 403)
        self.assertEqual(body, b"Origin is not allowed")
        self.assertEqual(called, [])

    def test_adds_cors_header_only_for_exact_allowed_origin(self):
        origin = "http://localhost:3000"
        bridge = self.make_bridge(
            policy=LocalBridgePolicy(allowed_origins=(origin,)),
        )
        status, _, headers = self.request(
            bridge,
            headers={"Origin": origin},
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
        self.assertEqual(headers["Vary"], "Origin")

    def test_rejects_missing_origin_when_not_explicitly_allowed(self):
        bridge = self.make_bridge(policy=LocalBridgePolicy())
        status, _, _ = self.request(bridge)

        self.assertEqual(status, 403)

    def test_rejects_oversized_body_before_dispatch(self):
        called = []
        policy = LocalBridgePolicy(
            allow_missing_origin=True,
            max_body_bytes=3,
        )
        bridge = self.make_bridge(
            policy=policy,
            routes={
                ("POST", "/echo"): lambda request: (
                    called.append(request.body) or LocalBridgeResponse()
                )
            },
        )
        status, body, _ = self.request(
            bridge,
            method="POST",
            path="/echo",
            body=b"four",
        )

        self.assertEqual(status, 413)
        self.assertIn(b"maximum size", body)
        self.assertEqual(called, [])

    def test_rejects_transfer_encoding(self):
        bridge = self.make_bridge()
        status, body, _ = self.request(
            bridge,
            method="POST",
            path="/echo",
            headers={"Transfer-Encoding": "chunked"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(body, b"Transfer-Encoding is not supported")

    def test_authentication_requires_bearer_token(self):
        policy = LocalBridgePolicy(
            allow_missing_origin=True,
            auth_token="per-session-secret",
        )
        bridge = self.make_bridge(policy=policy)
        status, body, _ = self.request(bridge)

        self.assertEqual(status, 401)
        self.assertEqual(body, b"Authentication required")

        status, body, _ = self.request(
            bridge,
            headers={"Authorization": "Bearer per-session-secret"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")

    def test_authentication_rejects_wrong_token(self):
        policy = LocalBridgePolicy(
            allow_missing_origin=True,
            auth_token="per-session-secret",
        )
        bridge = self.make_bridge(policy=policy)
        status, _, _ = self.request(
            bridge,
            headers={"Authorization": "Bearer wrong"},
        )

        self.assertEqual(status, 401)

    def test_unknown_route_is_not_dispatched(self):
        bridge = self.make_bridge()
        status, body, _ = self.request(bridge, path="/arbitrary-command")

        self.assertEqual(status, 404)
        self.assertEqual(body, b"Route not found")

    def test_preflight_does_not_require_bearer_token(self):
        origin = "http://localhost:3000"
        policy = LocalBridgePolicy(
            allowed_origins=(origin,),
            auth_token="per-session-secret",
        )
        bridge = self.make_bridge(policy=policy)
        status, _, headers = self.request(
            bridge,
            method="OPTIONS",
            path="/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
        self.assertEqual(headers["Access-Control-Allow-Methods"], "GET")

    def test_preflight_rejects_unlisted_headers(self):
        origin = "http://localhost:3000"
        policy = LocalBridgePolicy(allowed_origins=(origin,))
        bridge = self.make_bridge(policy=policy)
        status, _, _ = self.request(
            bridge,
            method="OPTIONS",
            path="/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-evil",
            },
        )

        self.assertEqual(status, 403)

    def test_handler_exception_does_not_leak_details(self):
        def fail(_request):
            raise RuntimeError("secret document contents")

        bridge = self.make_bridge(routes={("GET", "/health"): fail})
        status, body, _ = self.request(bridge)

        self.assertEqual(status, 500)
        self.assertEqual(body, b"Internal server error")
        self.assertNotIn(b"secret document contents", body)

    def test_response_headers_reject_line_break_injection(self):
        bridge = self.make_bridge(
            routes={
                ("GET", "/health"): lambda request: LocalBridgeResponse(
                    headers={"X-Test": "safe\r\nInjected: yes"}
                )
            }
        )
        status, body, _ = self.request(bridge)

        self.assertEqual(status, 500)
        self.assertEqual(body, b"Internal server error")

    def test_shutdown_stops_accepting_requests(self):
        bridge = self.make_bridge()
        self.assertTrue(bridge.is_running)
        self.assertTrue(bridge.shutdown(timeout=1))
        self.assertFalse(bridge.is_running)
        self.assertTrue(bridge.shutdown(timeout=1))

    def test_shutdown_reports_inflight_handler_and_waits_for_drain(self):
        entered = threading.Event()
        release = threading.Event()

        def wait_for_release(_request):
            entered.set()
            release.wait(timeout=2)
            return LocalBridgeResponse(body=b"finished")

        bridge = self.make_bridge(
            routes={("GET", "/health"): wait_for_release}
        )
        result = {}
        client = threading.Thread(
            target=lambda: result.update(
                response=self.request(bridge)
            ),
            daemon=True,
        )
        client.start()
        self.assertTrue(entered.wait(timeout=1))

        started = time.monotonic()
        self.assertFalse(bridge.shutdown(timeout=0.05))
        self.assertLess(time.monotonic() - started, 1)

        release.set()
        client.join(timeout=1)
        self.assertFalse(client.is_alive())
        self.assertTrue(bridge.shutdown(timeout=1))
        self.assertEqual(result["response"][0], 200)

    def test_max_concurrency_rejects_excess_connections(self):
        entered = threading.Event()
        release = threading.Event()

        def hold_request(_request):
            entered.set()
            release.wait(timeout=2)
            return LocalBridgeResponse(body=b"released")

        policy = LocalBridgePolicy(
            allow_missing_origin=True,
            max_concurrency=1,
        )
        bridge = self.make_bridge(
            policy=policy,
            routes={("GET", "/health"): hold_request},
        )
        first_result = {}
        first = threading.Thread(
            target=lambda: first_result.update(
                response=self.request(bridge)
            ),
            daemon=True,
        )
        first.start()
        self.assertTrue(entered.wait(timeout=1))

        status, body, _ = self.request(bridge)
        self.assertEqual(status, 503)
        self.assertEqual(body, b"Bridge is busy")

        release.set()
        first.join(timeout=1)
        self.assertFalse(first.is_alive())
        self.assertEqual(first_result["response"][0], 200)

    def test_shutdown_waits_for_active_request_to_drain(self):
        entered = threading.Event()
        release = threading.Event()
        result = {}

        def slow_route(_request):
            entered.set()
            release.wait(timeout=3)
            return LocalBridgeResponse(body=b"finished")

        bridge = self.make_bridge(
            routes={("GET", "/slow"): slow_route},
        )

        def send_request():
            result["response"] = self.request(bridge, path="/slow")

        worker = threading.Thread(target=send_request)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        self.assertFalse(bridge.shutdown(timeout=0.1))
        release.set()
        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result["response"][0], 200)
        self.assertTrue(bridge.shutdown(timeout=1))

    def test_rejects_new_requests_when_concurrency_limit_is_reached(self):
        entered = threading.Event()
        release = threading.Event()
        results = {}

        def slow_route(_request):
            entered.set()
            release.wait(timeout=3)
            return LocalBridgeResponse(body=b"finished")

        policy = LocalBridgePolicy(
            allow_missing_origin=True,
            max_concurrency=1,
            request_timeout=3,
        )
        bridge = self.make_bridge(
            policy=policy,
            routes={("GET", "/slow"): slow_route},
        )

        def first_request():
            results["first"] = self.request(bridge, path="/slow")

        worker = threading.Thread(target=first_request)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        second = self.request(bridge, path="/slow")
        release.set()
        worker.join(timeout=3)

        self.assertEqual(second[0], 503)
        self.assertEqual(results["first"][0], 200)
        self.assertFalse(worker.is_alive())

    def test_rejects_duplicate_content_length_headers(self):
        bridge = self.make_bridge()
        port = bridge.address[1]
        request = (
            f"POST /echo HTTP/1.1\\r\\n"
            f"Host: 127.0.0.1:{port}\\r\\n"
            "Content-Length: 0\\r\\n"
            "Content-Length: 0\\r\\n"
            "Connection: close\\r\\n\\r\\n"
        ).encode("ascii")
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(request)
            response = client.recv(2048)

        self.assertIn(b"400 Bad Request", response)
        self.assertIn(b"Invalid Content-Length", response)

    def test_slow_request_body_times_out(self):
        policy = LocalBridgePolicy(
            allow_missing_origin=True,
            max_body_bytes=8,
            request_timeout=0.1,
        )
        bridge = self.make_bridge(policy=policy)
        port = bridge.address[1]
        request = (
            f"POST /echo HTTP/1.1\\r\\n"
            f"Host: 127.0.0.1:{port}\\r\\n"
            "Content-Length: 4\\r\\n"
            "Connection: close\\r\\n\\r\\n"
            "x"
        ).encode("ascii")
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(request)
            time.sleep(0.25)
            response = client.recv(2048)

        self.assertIn(b"408 Request Timeout", response)
        self.assertIn(b"Request body timed out", response)

    def test_port_conflict_is_reported(self):
        first = self.make_bridge()
        port = first.address[1]
        second = LocalBridge(
            routes={},
            policy=LocalBridgePolicy(port=port, allow_missing_origin=True),
        )

        with self.assertRaises(OSError):
            second.start()


if __name__ == "__main__":
    unittest.main()
