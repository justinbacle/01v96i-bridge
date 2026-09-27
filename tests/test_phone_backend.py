"""Tests for the phone backend: commands to the console, state to the phones."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backends.phone import PhoneBackend, FADER_MIN_INTERVAL_S  # noqa: E402
from yamaha01v96i import encoder, events as ev, protocol, parse  # noqa: E402


class FakeOutport:
    """Records SysEx messages the backend wants to send."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(list(message.data))


class PhoneBackendTest(unittest.TestCase):
    def setUp(self):
        self.backend = PhoneBackend()
        self.outport = FakeOutport()
        self.backend.attach_outport(self.outport)

    def sent_events(self):
        return [parse(payload) for payload in self.outport.sent]

    def test_fader_command_reaches_the_console(self):
        raw = protocol.fader_raw(-6.0)
        self.backend.handle_command({"action": "fader", "channel": 5, "raw": raw})
        [event] = self.sent_events()
        self.assertEqual(event.channel, 5)
        self.assertAlmostEqual(event.db, -6.0, delta=0.2)

    def test_final_fader_command_is_never_throttled(self):
        for _ in range(10):
            self.backend.handle_command({"action": "fader", "channel": 0,
                                         "raw": 500, "final": True})
        self.assertEqual(len(self.outport.sent), 10)

    def test_fader_drag_is_throttled_to_the_latest_value(self):
        for raw in (100, 300, 500):
            self.backend.handle_command({"action": "fader", "channel": 0, "raw": raw})
        # All within one interval: only the first goes out; the rest are dropped
        # rather than queued, because a newer value always supersedes an older.
        self.assertEqual(len(self.outport.sent), 1)
        time.sleep(FADER_MIN_INTERVAL_S)
        self.backend.handle_command({"action": "fader", "channel": 0, "raw": 700})
        self.assertEqual(len(self.outport.sent), 2)
        self.assertAlmostEqual(self.sent_events()[-1].db,
                               protocol.fader_db(700), delta=0.2)

    def test_master_fader_command_reaches_the_console(self):
        raw = protocol.fader_raw(-6.0, unity_top=True)
        self.backend.handle_command({"action": "master_fader", "raw": raw})
        [event] = self.sent_events()
        self.assertIsInstance(event, ev.MasterFaderMoved)
        self.assertAlmostEqual(event.db, -6.0, delta=0.2)

    def test_mute_command_reaches_the_console(self):
        self.backend.handle_command({"action": "mute", "channel": 3, "muted": True})
        [event] = self.sent_events()
        self.assertEqual(event.channel, 3)
        self.assertTrue(event.muted)

    def test_master_mute_command_reaches_the_console(self):
        self.backend.handle_command({"action": "master_mute", "muted": True})
        [event] = self.sent_events()
        self.assertIsInstance(event, ev.MasterMuteChanged)
        self.assertTrue(event.muted)

    def test_aux_send_command_reaches_the_console(self):
        raw = protocol.fader_raw(-6.0, unity_top=True)
        self.backend.handle_command({"action": "aux_send", "aux": 4,
                                     "channel": 9, "raw": raw})
        [event] = self.sent_events()
        self.assertIsInstance(event, ev.AuxSendMoved)
        self.assertEqual(event.aux, 4)
        self.assertEqual(event.channel, 9)
        self.assertAlmostEqual(event.db, -6.0, delta=0.2)

    def test_aux_send_out_of_range_is_ignored(self):
        for aux in (0, 9, -1):
            self.backend.handle_command({"action": "aux_send", "aux": aux,
                                         "channel": 0, "raw": 500})
        self.assertEqual(self.outport.sent, [])

    def test_aux_master_fader_command_reaches_the_console(self):
        raw = protocol.fader_raw(-6.0, unity_top=True)
        self.backend.handle_command({"action": "aux_master_fader", "aux": 3,
                                     "raw": raw})
        [event] = self.sent_events()
        self.assertIsInstance(event, ev.AuxMasterMoved)
        self.assertEqual(event.aux, 3)
        self.assertAlmostEqual(event.db, -6.0, delta=0.2)

    def test_aux_on_command_reaches_the_console(self):
        self.backend.handle_command({"action": "aux_on", "aux": 5, "on": False})
        [event] = self.sent_events()
        self.assertIsInstance(event, ev.AuxOnChanged)
        self.assertEqual(event.aux, 5)
        self.assertFalse(event.on)

    def test_commands_without_an_outport_are_dropped(self):
        self.backend = PhoneBackend()  # no attach_outport
        self.backend.handle_command({"action": "fader", "channel": 0, "raw": 500})
        self.backend.handle_command({"action": "mute", "channel": 0, "muted": True})
        self.backend.handle_command({"action": "master_fader", "raw": 500})
        self.backend.handle_command({"action": "master_mute", "muted": True})
        self.backend.handle_command({"action": "aux_send", "aux": 1,
                                     "channel": 0, "raw": 500})

    def test_malformed_commands_are_ignored(self):
        for bad in (None, "string", [], {}, {"action": "fader"},
                    {"action": "fader", "channel": 0, "raw": "high"},
                    {"action": "fader", "channel": "one", "raw": 500},
                    {"action": "mute", "channel": 0, "muted": "yes"},
                    {"action": "master_fader", "raw": "top"},
                    {"action": "master_mute", "muted": 1},
                    {"action": "unknown", "channel": 0}):
            self.backend.handle_command(bad)
        self.assertEqual(self.outport.sent, [])

    def test_console_events_reach_the_state(self):
        self.backend.handle(parse(encoder.channel_fader_db(2, -12.0)))
        self.assertAlmostEqual(self.backend.state.channels[2].fader_db, -12.0, delta=0.2)

    def test_our_own_writes_reach_other_phones(self):
        # The console's echo is off, so nothing comes back over MIDI; the state
        # must pick up the change so every other phone sees it.
        self.backend.handle_command({"action": "fader", "channel": 7, "raw": 300})
        self.assertAlmostEqual(self.backend.state.channels[7].fader_db,
                               protocol.fader_db(300), delta=0.2)
        self.backend.handle_command({"action": "mute", "channel": 7, "muted": True})
        self.assertTrue(self.backend.state.channels[7].muted)
        self.backend.handle_command({"action": "master_fader", "raw": 300})
        self.assertAlmostEqual(self.backend.state.master_db,
                               protocol.fader_db(300, unity_top=True), delta=0.2)


if __name__ == "__main__":
    unittest.main()
