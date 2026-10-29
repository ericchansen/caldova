import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import server
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient


class TabTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_anonymous_denied_before_request_validation(self):
        for body in ({}, {"method": "tools/list"}, {"method": "resources/read", "uri": server.UI_URI}):
            self.assertEqual(self.client.post("/api/rpc", json=body).status_code, 401)

    def test_bad_token_denied(self):
        self.assertEqual(self.client.post("/api/rpc", headers={"Authorization": "Bearer not-a-jwt"},
                                          json={"method": "tools/list"}).status_code, 401)

    def test_sandbox_cannot_use_backend(self):
        with patch.object(server, "MODE", "sandbox"):
            self.assertEqual(self.client.post("/api/rpc").status_code, 404)
            self.assertEqual(self.client.get("/config").status_code, 404)
            self.assertEqual(self.client.get("/").status_code, 404)

    def test_host_cannot_serve_sandbox(self):
        self.assertEqual(self.client.get("/sandbox.html").status_code, 404)

    def test_sandbox_origin_comes_from_server_configuration(self):
        document = '<meta name="tab-host-origin" content="__TAB_HOST_ORIGIN__">'
        with patch.object(server, "MODE", "sandbox"), \
                patch.object(server, "HOST", "https://tab.example.invalid"), \
                patch.object(server.Path, "read_text", return_value=document):
            response = self.client.get("/sandbox.html", params={
                "csp": '{"resourceDomains":["https://esm.sh"],"connectDomains":[]}',
                "host": "https://untrusted.example.invalid",
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn('content="https://tab.example.invalid"', response.text)
        self.assertNotIn("untrusted.example.invalid", response.text)
        self.assertNotIn("__TAB_HOST_ORIGIN__", response.text)
        self.assertIn("connect-src 'none'", response.headers["content-security-policy"])

    def test_source_contract_preserved(self):
        result = {"contents": [{"uri": server.UI_URI, "mimeType": server.UI_MIME, "text": "<html>unaltered</html>",
                               "_meta": {"ui": {"csp": {"resourceDomains": ["https://esm.sh"], "connectDomains": []}}}}]}
        self.assertEqual(server.preserve_contract("resources/read", result), result)
        result["contents"][0]["mimeType"] = "text/html"
        with self.assertRaises(RuntimeError):
            server.preserve_contract("resources/read", result)

    def test_csp_rejects_expansion(self):
        for csp in (None, {}, {"resourceDomains": ["https://esm.sh; unsafe"]},
                    {"resourceDomains": ["https://esm.sh"], "connectDomains": ["https://example.com"]}):
            with self.assertRaises(ValueError):
                server.validate_csp(csp)

    def test_allowlist(self):
        for request in (
            {"method": "tools/call", "name": "send_email", "arguments": {}},
            {"method": "resources/read", "uri": "file:///etc/passwd"},
            {"method": "initialize"},
            {"method": "tools/call", "name": "show_table", "arguments": {"run_id": "bad"}},
            {"method": "tools/call", "name": "show_table", "arguments": {"run_id": "tab-test", "prompt": "bad"}},
        ):
            with self.assertRaises(HTTPException):
                server.Rpc(**request).hosted_fields()
        self.assertEqual(server.Rpc(method="tools/call", name="show_table", arguments={"run_id": "tab-test"}).hosted_fields(),
                         {"rpc_tool": "show_table", "rpc_arguments": {"run_id": "tab-test"}})

    def test_signed_user_claim_validation(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        good = {"aud": "tab-app", "iss": "https://login.microsoftonline.com/tenant/v2.0", "tid": "tenant",
                "ver": "2.0", "iat": now, "nbf": now, "exp": now + 300, "scp": "access_as_user",
                "oid": "00000000-0000-0000-0000-000000000001", "azp": next(iter(server.TEAMS_CLIENTS))}
        with patch.object(server, "TENANT", "tenant"), patch.object(server, "APP_ID", "tab-app"), \
                patch.object(server.JWK, "get_signing_key_from_jwt", return_value=SimpleNamespace(key=key.public_key())):
            self.assertEqual(server.verify_user(jwt.encode(good, key, algorithm="RS256"))["oid"], good["oid"])
            for change in ({"aud": "source-app"}, {"tid": "other"}, {"iss": "wrong"}, {"azp": "unknown"},
                           {"scp": "other"}, {"exp": now - 100}, {"ver": "1.0"}, {"nbf": now + 999}):
                with self.assertRaises(HTTPException):
                    server.verify_user(jwt.encode({**good, **change}, key, algorithm="RS256"))
            app_only = {k: v for k, v in good.items() if k != "scp"}
            app_only["roles"] = ["access_as_user"]
            with self.assertRaises(HTTPException):
                server.verify_user(jwt.encode(app_only, key, algorithm="RS256"))

    def test_success_and_failure_are_honest(self):
        headers = {"Authorization": "Bearer test"}
        result = {"structuredContent": {"run_id": "tab-test", "counter": 2}, "content": []}
        with patch.object(server, "verify_user", return_value={"oid": "test"}), \
                patch.object(server, "invoke_hosted", new=AsyncMock(return_value=(result, "response-test"))):
            response = self.client.post("/api/rpc", headers=headers, json={
                "method": "tools/call", "name": "show_table", "arguments": {"run_id": "tab-test"}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), result)
            self.assertTrue(response.headers["X-Request-ID"].startswith("tab-"))
        with patch.object(server, "verify_user", return_value={"oid": "test"}), \
                patch.object(server, "invoke_hosted", new=AsyncMock(side_effect=RuntimeError("upstream failed"))):
            response = self.client.post("/api/rpc", headers=headers, json={"method": "tools/list"})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("upstream failed", response.text)


if __name__ == "__main__":
    unittest.main()
