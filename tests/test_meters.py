"""Tests for the remote-meter path: request framing, reply decoding, state."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yamaha01v96i import encoder, events as ev, parse, protocol  # noqa: E402
from yamaha01v96i.state import ConsoleState  # noqa: E402


def meter_reply(levels, page=protocol.METER_CHANNEL_PAGE) -> list:
    """Build a bulk meter reply the way the console sends it.

    Captured on device: 43 10 3E 1A 21, page, two zeros, then the levels as
    two 7-bit bytes each, MSB first.
    """
    payload = [protocol.YAMAHA_ID, protocol.DEVICE_BYTE, protocol.GROUP_ID,
               protocol.MODEL_01V96I, protocol.METER_ELEMENT, page, 0x00, 0x00]
    for level in levels:
        payload += [(level >> 7) & 0x7F, level & 0x7F]
    return payload


class MeterTest(unittest.TestCase):
    def test_request_shape(self):
        """The request: SUB STATUS 3n, model 1A, element 0x21, count 32."""
        for payload, page in zip(encoder.request_meters(),
                                 (protocol.METER_CHANNEL_PAGE,
                                  protocol.METER_MASTER_PAGE)):
            self.assertEqual(payload[:4], [0x43, 0x30, 0x3E, 0x1A])
            self.assertEqual(payload[4], 0x21)
            self.assertEqual(payload[5], page)
            self.assertEqual(payload[6:8], [0x00, 0x00])   # address mid/low
            self.assertEqual(payload[8], 0x00)            # count H
            self.assertEqual(payload[9], protocol.METER_LEVELS)

    def test_request_is_not_mistaken_for_a_reply(self):
        # The console may echo the request; it must decode as nothing, not as
        # a bogus level frame.
        for payload in encoder.request_meters():
            self.assertIsNone(parse(payload))

    def test_reply_decodes_every_level(self):
        levels = tuple(100 + 13 * i for i in range(32))
        event = parse(meter_reply(levels))
        self.assertIsInstance(event, ev.MeterLevels)
        self.assertEqual(event.levels, levels)

    def test_master_reply_is_a_separate_event(self):
        event = parse(meter_reply([2230, 2230], page=protocol.METER_MASTER_PAGE))
        self.assertIsInstance(event, ev.MasterMeterLevels)
        self.assertEqual(event.levels, (2230, 2230))

    def test_reply_level_is_14_bit(self):
        # CH1 with a signal reads ~1900 on this desk: MSB 0x0E, LSB 0x4E.
        event = parse(meter_reply([(0x0E << 7) | 0x4E] + [0] * 31))
        self.assertEqual(event.levels[0], (0x0E << 7) | 0x4E)

    def test_levels_reach_the_state_and_snapshot(self):
        state = ConsoleState()
        self.assertTrue(state.apply(parse(meter_reply([500] * 32))))
        self.assertEqual(state.meters[31], 500)
        self.assertEqual(state.snapshot()["meters"]["31"], 500)

    def test_master_levels_reach_the_state(self):
        state = ConsoleState()
        state.apply(parse(meter_reply([2220, 2230], page=protocol.METER_MASTER_PAGE)))
        self.assertEqual(state.master_meters, (2220, 2230))
        self.assertEqual(state.snapshot()["master_meters"], [2220, 2230])

    def test_unchanged_levels_cost_no_dirty_flag(self):
        state = ConsoleState()
        state.apply(parse(meter_reply([500] * 32)))
        self.assertFalse(state.apply(parse(meter_reply([500] * 32))))
        self.assertTrue(state.apply(parse(meter_reply([501] * 32))))


if __name__ == "__main__":
    unittest.main()
