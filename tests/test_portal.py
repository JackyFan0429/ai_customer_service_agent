"""Exercise the actual HTTP handler with byte streams, without opening a port."""

import io
import json
import unittest
from types import SimpleNamespace

from support_agent.desk.service import DeskService
from support_agent.desk.storage import Database
from support_agent.portal import PortalApplication, make_handler


class SocketStream:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, *args):
        return self.input

    def sendall(self, value):
        self.output.extend(value)


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.handler = make_handler(PortalApplication(DeskService(self.db, seed_tickets=False)))
        self.handler.log_message = lambda *args: None
        self.cookie = self.csrf = ""

    def request(self, path, method="GET", payload=None, *, csrf=True, headers=None):
        data = json.dumps(payload or {}).encode() if method != "GET" else b""
        fields = {"Host": "127.0.0.1:8080", "Content-Type": "application/json", "Content-Length": str(len(data))}
        if self.cookie:
            fields["Cookie"] = self.cookie
        if self.csrf and csrf:
            fields["X-CSRF-Token"] = self.csrf
        fields.update(headers or {})
        raw = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
        sock = SocketStream(raw.encode() + data)
        self.handler(sock, ("127.0.0.1", 10000), SimpleNamespace(server_name="localhost", server_port=8080))
        head, body = bytes(sock.output).split(b"\r\n\r\n", 1)
        lines = head.decode().split("\r\n")
        status = int(lines[0].split()[1])
        response_headers = dict(line.split(": ", 1) for line in lines[1:])
        return status, json.loads(body) if response_headers["Content-Type"].startswith("application/json") else body, response_headers

    def login(self, email="admin@lumen.test"):
        status, body, headers = self.request("/api/auth/login", "POST", {"email": email, "password": "Demo123!"})
        self.assertEqual(200, status)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = body["csrf"]
        return headers

    def test_anonymous_api_denied_but_static_page_and_health_work(self):
        self.assertEqual(401, self.request("/api/account")[0])
        self.assertEqual(200, self.request("/api/health")[0])
        status, body, headers = self.request("/")
        self.assertEqual(200, status)
        self.assertIn(b"app.js", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(404, self.request("/../runtime/lumen_desk.db")[0])
        self.assertEqual(404, self.request("/data/source_profile.json")[0])

    def test_session_cookie_csrf_and_origin_checks(self):
        headers = self.login()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        route = "/api/admin/settings"
        self.assertEqual(403, self.request(route, "PATCH", {"reply_mode": "auto"}, csrf=False)[0])
        self.assertEqual(403, self.request(route, "PATCH", {"reply_mode": "auto"}, headers={"Origin": "https://evil.example"})[0])
        self.assertEqual("auto", self.db.settings()["reply_mode"])
        self.assertEqual(200, self.request(route, "PATCH", {"reply_mode": "auto"})[0])
        self.assertEqual(200, self.request("/api/auth/logout", "POST")[0])
        self.assertEqual(401, self.request("/api/bootstrap")[0])

    def test_personal_cannot_access_admin_routes(self):
        self.login("alice@lumen.test")
        for path in ["/api/admin/dashboard", "/api/admin/users/4", "/api/admin/knowledge", "/api/admin/learning"]:
            self.assertEqual(403, self.request(path)[0], path)
        status, body, _ = self.request("/api/account")
        self.assertEqual(200, status)
        self.assertEqual("alice@lumen.test", body["user"]["email"])
        self.assertNotIn("password_hash", json.dumps(body))

    def test_wrong_content_type_and_oversized_body_are_rejected(self):
        self.login()
        self.assertEqual(415, self.request("/api/tickets", "POST", headers={"Content-Type": "text/plain"})[0])
        self.assertEqual(413, self.request("/api/tickets", "POST", headers={"Content-Length": "65537"})[0])


if __name__ == "__main__":
    unittest.main()
