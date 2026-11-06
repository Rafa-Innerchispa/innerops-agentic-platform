from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("register_agent", ROOT / "scripts/register_agent.py")
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class MockRegistration(BaseHTTPRequestHandler):
    received=None
    def do_POST(self):
        self.__class__.received = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/agents" or self.headers.get("Authorization")!="Bearer fake-registration-token":
            self.send_error(401)
            return
        payload=json.dumps({"id":"new_agent_7", "api_key":"fake-api-key"}).encode()
        self.send_response(201)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self,*args): pass


class RegistrationTests(unittest.TestCase):
    def test_http_lan_rejected_to_protect_bearer(self):
        self.assertFalse(mod.valid_switch_url("http://192.168.1.5:8000"))
        self.assertTrue(mod.valid_switch_url("http://127.0.0.1:8000"))
        self.assertTrue(mod.valid_switch_url("https://test.example"))

    def test_one_time_registration_and_no_secret_stdout(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),MockRegistration)
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with TemporaryDirectory() as d:
                dest=Path(d)/"agent.json"
                result=mod.register(f"http://127.0.0.1:{server.server_port}",
                                    "fake-registration-token","inneros-incident-triage",dest)
                self.assertEqual(result["agent_id"],"new_agent_7")
                self.assertNotIn("fake-api-key",json.dumps(result))
                self.assertEqual(json.loads(dest.read_text())["api_key"],"fake-api-key")
                self.assertEqual(MockRegistration.received["integration_profile"]["connection_model"],"always_on")
                with self.assertRaises(FileExistsError):
                    mod.register(f"http://127.0.0.1:{server.server_port}",
                                 "fake-registration-token","inneros-incident-triage",dest)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_registration_requires_key(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                mod.register("http://127.0.0.1:9999","","demo",Path(d)/"secret.json")


if __name__ == "__main__": unittest.main()