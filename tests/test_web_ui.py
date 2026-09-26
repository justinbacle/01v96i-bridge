"""Tests for the web layer: routes, snapshots, and pushing state to clients."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.server import WebUI  # noqa: E402
from yamaha01v96i import encoder, parse  # noqa: E402
from yamaha01v96i.state import ConsoleState  # noqa: E402


class FakeSocket:
    """Stands in for a connected phone."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, payload):
        if self.fail:
            raise ConnectionError("phone went away")
        self.sent.append(json.loads(payload))


class WebUITest(unittest.TestCase):
    def setUp(self):
        self.state = ConsoleState()
        self.commands = []
        self.ui = WebUI(self.state, on_command=self.commands.append)
        self.client = self.ui.app.test_client()

    def test_serves_the_page_and_its_assets(self):
        for path in ("/", "/app.js", "/style.css"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_state_endpoint_reflects_the_console(self):
        self.state.apply(parse(encoder.channel_fader_db(0, -6.0)))
        body = self.client.get("/api/state").get_json()
        self.assertEqual(len(body["channels"]), 1)
        self.assertAlmostEqual(body["channels"][0]["fader_db"], -6.0, delta=0.2)

    def test_broadcast_reaches_every_client(self):
        first, second = FakeSocket(), FakeSocket()
        self.ui._clients.update({first, second})
        self.state.apply(parse(encoder.channel_fader_db(0, 0.0)))
        self.ui.broadcast_state()
        for sock in (first, second):
            self.assertEqual(sock.sent[0]["type"], "state")
            self.assertEqual(len(sock.sent[0]["state"]["channels"]), 1)

    def test_a_client_that_disappears_is_dropped(self):
        good, gone = FakeSocket(), FakeSocket(fail=True)
        self.ui._clients.update({good, gone})
        self.ui.broadcast_state()
        self.assertIn(good, self.ui._clients)
        self.assertNotIn(gone, self.ui._clients)
        self.assertEqual(len(good.sent), 1)

    def test_broadcast_with_no_clients_is_harmless(self):
        self.ui.broadcast_state()

    def test_commands_are_forwarded(self):
        self.ui._handle_command(json.dumps({"action": "fader", "channel": 0}))
        self.assertEqual(self.commands, [{"action": "fader", "channel": 0}])

    def test_unparseable_commands_are_ignored(self):
        self.ui._handle_command("not json")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
