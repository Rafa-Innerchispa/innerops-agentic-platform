"""Real WebSocket + HTTP transport against a local FAKE Switch server.

These tests are transport integration tests, NOT a live Switch certification.
"""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.parse import urlsplit, parse_qs

try:
    from websockets.asyncio.server import serve as ws_serve
except ImportError:
    ws_serve = None

from inneros_incident_room.switch_event import SwitchConfig, serve


class FakeSwitchHTTP(BaseHTTPRequestHandler):
    posts: list[dict] = []

    def do_POST(self):
        payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path != "/agents/agent-demo/message":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer mock-secret":
            self.send_error(401)
            return
        FakeSwitchHTTP.posts.append(json.loads(payload))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass


@unittest.skipUnless(ws_serve is not None, "pip install -e .[switch] for socket test")
class EndToEndFakeSwitchTests(unittest.TestCase):
    def test_real_transport_fake_server_approval_and_rejection(self):
        async def scenario():
            with TemporaryDirectory() as d:
                FakeSwitchHTTP.posts = []
                http = ThreadingHTTPServer(("127.0.0.1", 0), FakeSwitchHTTP)
                thread = Thread(target=http.serve_forever, daemon=True)
                thread.start()
                room = "!demo:localhost"
                operator = "@switch-user-ab12:localhost"
                cfg = SwitchConfig("http://127.0.0.1:%s" % http.server_port,
                                   "agent-demo", "mock-secret", room, operator,
                                   Path(d) / "state.json")
                pong_seen = asyncio.Event()
                incoming: list[str] = []
                next_seq = [1]

                async def wait_replies(count, timeout=4.0):
                    async def ready():
                        while len(FakeSwitchHTTP.posts) < count:
                            await asyncio.sleep(0.02)
                    await asyncio.wait_for(ready(), timeout)

                async def ws_handler(websocket):
                    self.assertEqual(websocket.request.headers["Authorization"], "Bearer mock-secret")
                    q = parse_qs(urlsplit(websocket.request.path).query)
                    self.assertEqual(q["rooms"], [room])
                    self.assertRegex(q["connection_id"][0], r"[0-9a-f-]{36}")
                    await websocket.send(json.dumps({
                        "event":"connection_state", "data":{
                            "agent_id":"agent-demo", "rooms":[room],
                            "generation":1, "cursor":0,
                        },
                    }))
                    await websocket.send(json.dumps({"type":"ping"}))
                    pong=json.loads(await asyncio.wait_for(websocket.recv(),2))
                    self.assertEqual(pong["type"],"pong")
                    pong_seen.set()

                    async def send(body, sender=operator, addressed=True):
                        seq = next_seq[0]; next_seq[0]+=1
                        await websocket.send(json.dumps({
                            "event":"message", "id":seq,
                            "data":{"type":"message", "room_id":room,
                                    "payload":{"addressed":addressed, "sender":sender,
                                               "message_id":"msg"+str(seq),"body":body}}
                        }))
                        incoming.append(body)
                    await send("!incident")
                    await wait_replies(1)
                    action=re.search(r"!approve ([\w-]+)",FakeSwitchHTTP.posts[-1]["content"])
                    self.assertIsNotNone(action)
                    await send("!deny "+action.group(1))
                    await wait_replies(2)
                    self.assertIn("DENIED",FakeSwitchHTTP.posts[-1]["content"])
                    await send("!incident")
                    await wait_replies(3)
                    next_action=re.search(r"!approve ([\w-]+)",FakeSwitchHTTP.posts[-1]["content"])
                    await send("!approve "+next_action.group(1), sender="@switch-user-unauthorized:localhost")
                    await wait_replies(4)
                    self.assertIn("BLOCKED",FakeSwitchHTTP.posts[-1]["content"])
                    await send("!approve "+next_action.group(1))
                    await wait_replies(5)
                    self.assertIn("verified_simulation",FakeSwitchHTTP.posts[-1]["content"])
                    self.assertIn("digest_valid=True",FakeSwitchHTTP.posts[-1]["content"])
                    await asyncio.sleep(0.1)

                try:
                    async with ws_serve(ws_handler,"127.0.0.1",0) as web:
                        sockport=web.sockets[0].getsockname()[1]
                        # Transport URL shares the same port for HTTP and WS in REAL Switch.
                        # Fake tests use distinct ports, so redirect websocket URL only.
                        from inneros_incident_room import switch_event
                        original=switch_event.ConnectionState.ws_url
                        def remap(self):
                            u=original(self)
                            return u.replace(f"127.0.0.1:{http.server_port}",f"127.0.0.1:{sockport}")
                        from unittest.mock import patch
                        with patch.object(switch_event.ConnectionState,"ws_url",remap):
                            client=asyncio.create_task(serve(cfg))
                            await asyncio.wait_for(pong_seen.wait(),4)
                            await asyncio.wait_for(ws_client_done(client),9)
                            client.cancel()
                            try:
                                await client
                            except asyncio.CancelledError:
                                pass
                finally:
                    http.shutdown()
                    http.server_close()
                    thread.join(2)
                self.assertEqual(len(FakeSwitchHTTP.posts),5)
                self.assertEqual([x["room_id"] for x in FakeSwitchHTTP.posts],[room]*5)
                self.assertTrue(cfg.state_path.exists())
                state=json.loads(cfg.state_path.read_text())
                self.assertGreaterEqual(state["cursor"],5)
                self.assertEqual(state["policy_snapshot"]["state"]["synthetic-camera-a"],"healthy")

        async def ws_client_done(client):
            while len(FakeSwitchHTTP.posts)<5:
                if client.done():
                    raise AssertionError("Switch client exited before finishing fake E2E")
                await asyncio.sleep(0.02)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()