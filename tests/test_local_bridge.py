import unittest

from winux.core.local_bridge import LocalBridgePolicy


class LocalBridgePolicyTests(unittest.TestCase):
    def test_accepts_explicit_ipv4_and_ipv6_loopback(self):
        self.assertEqual(
            LocalBridgePolicy(bind_address="127.0.0.1").bind_address,
            "127.0.0.1",
        )
        self.assertEqual(
            LocalBridgePolicy(bind_address="::1").bind_address,
            "::1",
        )

    def test_rejects_non_loopback_and_hostname_bind_addresses(self):
        for address in ("0.0.0.0", "::", "192.168.1.10", "localhost", ""):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    LocalBridgePolicy(bind_address=address)

    def test_rejects_invalid_port_and_limits(self):
        for port in (-1, 65536, True, "1984"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    LocalBridgePolicy(port=port)

        for kwargs in (
            {"max_body_bytes": 0},
            {"max_body_bytes": True},
            {"request_timeout": 0},
            {"request_timeout": float("inf")},
            {"max_concurrency": 0},
            {"max_concurrency": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    LocalBridgePolicy(**kwargs)

    def test_normalizes_exact_origins(self):
        policy = LocalBridgePolicy(
            allowed_origins=("HTTPS://Portal.Example.COM:443/",)
        )
        self.assertTrue(policy.validate_origin("https://portal.example.com"))
        self.assertFalse(policy.validate_origin("https://portal.example.com.evil"))
        self.assertFalse(policy.validate_origin("https://portal.example.com:444"))

    def test_origin_rejects_paths_credentials_wildcards_and_null(self):
        for origin in (
            "*",
            "null",
            "file://portal.example.com",
            "https://user:pass@portal.example.com",
            "https://portal.example.com/path",
            "https://portal.example.com?x=1",
            "https://portal.example.com#fragment",
        ):
            with self.subTest(origin=origin):
                with self.assertRaises(ValueError):
                    LocalBridgePolicy.normalize_origin(origin)

    def test_missing_origin_is_denied_by_default(self):
        policy = LocalBridgePolicy()
        self.assertFalse(policy.validate_origin(None))

    def test_missing_origin_requires_explicit_non_browser_policy(self):
        policy = LocalBridgePolicy(allow_missing_origin=True)
        self.assertTrue(policy.validate_origin(None))

    def test_host_must_match_exact_loopback_listener_and_port(self):
        policy = LocalBridgePolicy(bind_address="127.0.0.1", port=1984)
        self.assertTrue(policy.validate_host("127.0.0.1:1984"))
        self.assertFalse(policy.validate_host("localhost:1984"))
        self.assertFalse(policy.validate_host("127.0.0.1:1985"))
        self.assertFalse(policy.validate_host("192.168.1.10:1984"))
        self.assertFalse(policy.validate_host("127.0.0.1"))
        self.assertFalse(policy.validate_host("127.0.0.1:1984.evil"))

    def test_ipv6_host_is_bracketed_and_exact(self):
        policy = LocalBridgePolicy(bind_address="::1", port=1984)
        self.assertTrue(policy.validate_host("[::1]:1984"))
        self.assertFalse(policy.validate_host("::1:1984"))
        self.assertFalse(policy.validate_host("[::1]:1985"))

    def test_authentication_uses_configured_token(self):
        policy = LocalBridgePolicy(auth_token="per-session-secret")
        self.assertTrue(policy.authenticate("per-session-secret"))
        self.assertFalse(policy.authenticate("wrong"))
        self.assertFalse(policy.authenticate(None))

    def test_authentication_can_be_disabled_explicitly(self):
        policy = LocalBridgePolicy()
        self.assertTrue(policy.authenticate(None))

    def test_content_length_is_bounded_and_strict(self):
        policy = LocalBridgePolicy(max_body_bytes=16)
        self.assertEqual(policy.validate_content_length(None), 0)
        self.assertEqual(policy.validate_content_length("16"), 16)
        for value in ("17", "-1", "+1", "1.0", " 1", "1x", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    policy.validate_content_length(value)


if __name__ == "__main__":
    unittest.main()
