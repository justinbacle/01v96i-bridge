"""Tests for the console state model."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yamaha01v96i import encoder, parse, protocol  # noqa: E402
from yamaha01v96i.state import ConsoleState  # noqa: E402


def name_message(channel: int, index: int, char: str):
    return [67, 16, 62, 26, 2, 4, index, channel, 0, 0, 0, ord(char)]


class StateTest(unittest.TestCase):
    def setUp(self):
        self.state = ConsoleState()

    def feed(self, payload):
        return self.state.apply(parse(payload))

    def test_fader_and_mute(self):
        self.feed(encoder.channel_fader_db(0, -6.0))
        self.feed(encoder.channel_on(0, False))
        channel = self.state.channel(0)
        self.assertAlmostEqual(channel.fader_db, -6.0, delta=0.2)
        self.assertTrue(channel.muted)

    def test_reapplying_the_same_value_reports_no_change(self):
        self.assertTrue(self.feed(encoder.channel_fader_db(0, -6.0)))
        self.assertFalse(self.feed(encoder.channel_fader_db(0, -6.0)))

    def test_names_assemble_from_characters(self):
        for offset, char in enumerate("VOX"):
            self.feed(name_message(0, protocol.NAME_LONG.start + offset, char))
        for offset, char in enumerate("VX"):
            self.feed(name_message(0, protocol.NAME_SHORT.start + offset, char))
        self.assertEqual(self.state.channel(0).long_name, "VOX")
        self.assertEqual(self.state.channel(0).short_name, "VX")
        self.assertEqual(self.state.channel(0).label(), "VOX")

    def test_partial_names_do_not_raise(self):
        self.feed(name_message(0, protocol.NAME_LONG.start, "V"))
        self.feed(name_message(0, protocol.NAME_LONG.start + 2, "X"))
        self.assertEqual(self.state.channel(0).long_name, "V X")

    def test_label_falls_back_to_console_numbering(self):
        self.assertEqual(self.state.channel(9).label(), "CH10")
        self.assertEqual(self.state.channel(protocol.MONO_CHANNELS).label(), "ST1")

    def test_aux_sends_are_kept_per_aux(self):
        self.feed(encoder.aux_send_db(1, 0, -10.0))
        self.feed(encoder.aux_send_db(7, 0, -20.0))
        sends = self.state.channel(0).aux_sends
        self.assertAlmostEqual(sends[1], -10.0, delta=0.2)
        self.assertAlmostEqual(sends[7], -20.0, delta=0.2)

    def test_master_and_buses(self):
        self.feed(encoder.master_fader_db(-3.0))
        self.feed(encoder.master_on(False))
        self.feed(encoder.bus_fader_db(2, -12.0))
        self.feed(encoder.aux_master_db(3, -8.0))
        self.assertAlmostEqual(self.state.master_db, -3.0, delta=0.2)
        self.assertTrue(self.state.master_muted)
        self.assertAlmostEqual(self.state.bus_faders[2], -12.0, delta=0.2)
        self.assertAlmostEqual(self.state.aux_masters[3], -8.0, delta=0.2)

    def test_surround_axes_are_independent(self):
        self.feed(encoder.surround(0, "x", -1.0))
        self.feed(encoder.surround(0, "y", 1.0))
        self.assertAlmostEqual(self.state.channel(0).surround_x, -1.0, places=2)
        self.assertAlmostEqual(self.state.channel(0).surround_y, 1.0, places=2)

    def test_snapshot_is_json_ready(self):
        import json
        self.feed(encoder.channel_fader_db(0, 0.0))
        self.feed(encoder.master_fader_db(-3.0))
        json.dumps(self.state.snapshot())  # must not raise

    def test_ignored_events_do_not_create_channels(self):
        # The right-hand slot of a linked ST-IN pair must not appear as a strip.
        self.feed(encoder.channel_fader_db(protocol.ST_IN_FIRST + 1, 0.0))
        self.assertEqual(self.state.channels, {})


if __name__ == "__main__":
    unittest.main()
