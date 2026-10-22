import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from caldova.fixtures import MAX_BYTES, expected_markers, payload, validate_run_id
from caldova.server import EntraVerifier, build_server


class PayloadTests(unittest.TestCase):
    def test_exact_size_and_markers(self):
        for size in (1024, 32768, 262144, MAX_BYTES):
            text = payload(size, "test-run")
            self.assertEqual(len(text.encode()), size)
            self.assertEqual(len(expected_markers(size, "test-run")), 3)
            self.assertEqual(text, payload(size, "test-run"))
            self.assertNotEqual(text, payload(size, "different-run"))

    def test_bounds(self):
        for size in (0, 1023, MAX_BYTES + 1):
            with self.assertRaises(ValueError):
                payload(size, "run")
        for name in ("", "../escape", "a" * 65):
            with self.assertRaises(ValueError):
                validate_run_id(name)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_tools_and_app_metadata(self):
        server = build_server(local=True)
        tools = await server.list_tools()
        self.assertEqual(len(tools), 26)
        widget = next(tool for tool in tools if tool.name == "show_table")
        self.assertEqual(widget.meta["ui"]["resourceUri"], "ui://caldova/table")
        resources = await server.list_resources()
        self.assertEqual(str(resources[0].uri), "ui://caldova/table")


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scopes_audience_issuer_and_expiry(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = EntraVerifier("test-tenant", "test-audience")
        base = {
            "iss": verifier.issuer, "aud": "test-audience", "sub": "test-subject",
            "exp": int(time.time()) + 300, "azp": "test-client", "scp": "Mcp.Access",
        }
        with patch.object(verifier.keys, "get_signing_key_from_jwt",
                          return_value=SimpleNamespace(key=key.public_key())):
            for change, accepted in (
                ({}, True), ({"scp": "", "roles": ["Mcp.Invoke"]}, True),
                ({"scp": ""}, False), ({"aud": "another-api"}, False),
                ({"iss": "https://untrusted.example"}, False), ({"exp": 1}, False),
            ):
                result = await verifier.verify_token(jwt.encode({**base, **change}, key, algorithm="RS256"))
                self.assertEqual(result is not None, accepted)


if __name__ == "__main__":
    unittest.main()
