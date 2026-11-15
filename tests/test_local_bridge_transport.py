import http.client
import threading
import time
import unittest

from winux.core.local_bridge import (
    BridgeRequest,
    BridgeResponse,
    LocalBridge,
    LocalBridgePolicy,
)


class LocalBridgeTransportTests(unittest.TestCase):
    def setUp(self):
        self.policy = LocalBridgePolicy(
            bind_address="127.0.0.1",
            port=0,
            allowed_origins=("http://127.0.0.1:8080",),
            auth_token="test-token",
            max_body_bytes=32,
            request_timeout=2,
            max_concurrency=4,
        )
        self.bridge = LocalBridge(
            self.policy,
            routes={
                ("GET", "/health"): self.health,
                ("POST", "/echo"): self.echo,
            },
        )
        self.bridge.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        if self.bridge.is_running:
            self.bridge.shutdown(timeout=3)

    def connection(self):
        return http.client.HTTPConnection(
            "127.0.0.1",
            self.bridge.address[1],
            timeout=3,
        )

    def headers(self, **extra):
        return {
            "Host": f"127.0.0.1:{self.bridge.address[1]}",
            "Origin": "http://127.0.0.1:8080",
            "Authorization": "Bearer test-token",
            **extra,
        }

    @staticmethod
    def health(request):
        return BridgeResponse(
            status=200,
            headers={"Content-Type": "text/plain"},
            body=f"ok:{request.path}",
        )

    @staticmethod
    def echo(request):
        return BridgeResponse(
            status=200,
            headers={"Content-Type": "application/octet-stream"},
            body=request.body,
        )

    def request(self, method, path, body=None, headers=None):
        connection = self.connection()
        connection.request(
            method,
            path,
            body=body,
            headers=headers or self.headers(),
        )
        response = connection.getresponse()
        payload = response.read()
        result = response.status, dict(response.getheaders()), payload
        connection.close()
        return result

    def test_dispatches_exact_route_and_returns_cors_header(self):
        status, headers, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok:/health")
        self.assertEqual(
            headers.get("Access-Control-Allow-Origin"),
            "http://127.0.0.1:8080",
        )

    def test_unknown_route_is_not_found(self):
        status, _, _ = self.request("GET", "/unknown")
        self.assertEqual(status, 404)

    def test_rejects_unlisted_origin_before_dispatch(self):
        headers = self.headers()
        headers["Origin"] = "http://evil.example"
        status, _, _ = self.request("GET", "/health", headers=headers)
        self.assertEqual(status, 403)

    def test_rejects_wrong_host(self):
        headers = self.headers()
        headers["Host"] = "localhost:{}".format(self.bridge.address[1])
        status, _, _ = self.request("GET", "/health", headers=headers)
        self.assertEqual(status, 400)

    def test_requires_bearer_token_when_configured(self):
        headers = self.headers()
        headers.pop("Authorization")
        status, _, _ = self.request("GET", "/health", headers=headers)
        self.assertEqual(status, 401)

    def test_echoes_bounded_post_body(self):
        status, _, body = self.request("POST", "/echo", body=b"bridge-data")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"bridge-data")

    def test_rejects_oversized_body_before_route_dispatch(self):
        status, _, _ = self.request(
            "POST",
            "/echo",
            body=b"x" * 33,
        )
        self.assertEqual(status, 413)

    def test_preflight_requires_allowed_method_and_headers(self):
        headers = {
            "Host": f"127.0.0.1:{self.bridge.address[1]}",
            "Origin": "http://127.0.0.1:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        }
        status, response_headers, _ = self.request(
            "OPTIONS",
            "/echo",
            headers=headers,
        )
        self.assertEqual(status, 204)
        self.assertIn(
            "Access-Control-Allow-Origin",
            response_headers,
        )

    def test_preflight_rejects_unlisted_header(self):
        headers = {
            "Host": f"127.0.0.1:{self.bridge.address[1]}",
            "Origin": "http://127.0.0.1:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-unlisted",
        }
        status, _, _ = self.request("OPTIONS", "/echo", headers=headers)
        self.assertEqual(status, 403)

    def test_shutdown_stops_listener(self):
        self.assertTrue(self.bridge.is_running)
        self.assertTrue(self.bridge.shutdown(timeout=3))
        self.assertFalse(self.bridge.is_running)


class LocalBridgeConcurrencyTests(unittest.TestCase):
    def test_rejects_requests_when_concurrency_limit_is_reached(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_route(_request):
            entered.set()
            release.wait(timeout=3)
            return BridgeResponse(body=b"done")

        policy = LocalBridgePolicy(
            bind_address="127.0.0.1",
            port=0,
            allowed_origins=("http://127.0.0.1:8080",),
            max_concurrency=1,
            request_timeout=3,
        )
        bridge = LocalBridge(
            policy,
            routes={("GET", "/slow"): slow_route},
        )
        bridge.start()
        self.addCleanup(
            lambda: bridge.shutdown(timeout=4) if bridge.is_running else None
        )

        first_result = {}

        def first_request():
            connection = http.client.HTTPConnection(
                "127.0.0.1", bridge.address[1], timeout=4
            )
            connection.request(
                "GET",
                "/slow",
                headers={
                    "Host": f"127.0.0.1:{bridge.address[1]}",
                    "Origin": "http://127.0.0.1:8080",
                },
            )
            response = connection.getresponse()
            first_result["status"] = response.status
            first_result["body"] = response.read()
            connection.close()

        worker = threading.Thread(target=first_request)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        second = http.client.HTTPConnection(
            "127.0.0.1", bridge.address[1], timeout=2
        )
        second.request(
            "GET",
            "/slow",
            headers={
                "Host": f"127.0.0.1:{bridge.address[1]}",
                "Origin": "http://127.0.0.1:8080",
            },
        )
        response = second.getresponse()
        response.read()
        second.close()

        release.set()
        worker.join(timeout=3)

        self.assertEqual(response.status, 503)
        self.assertEqual(first_result.get("status"), 200)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
