"""Every message the encoder builds must parse back to the value intended.

This is the Tx/Rx parity check: the encoder and parser are mirrors, so encoding a
value and decoding it again should return it. Catches an element or parameter
number typed wrong in one direction, which is otherwise only visible by watching
the console.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yamaha01v96i import encoder, parse  # noqa: E402
from yamaha01v96i import protocol  # noqa: E402
from yamaha01v96i import events as ev  # noqa: E402


class EncoderParityTest(unittest.TestCase):
    # The console quantises to integer steps, so a round-trip lands within one
    # step, not exactly: ~0.18 dB per fader step at -60 dB, and EQ frequency
    # steps are ~6% apart. Tolerances are half a step.
    ABSOLUTE_TOLERANCE = {"db": 0.2, "gain_db": 0.05, "value": 0.01, "q": 0.05}
    RELATIVE_TOLERANCE = {"freq_hz": 0.03}

    def assert_round_trip(self, payload, event_type, **expected):
        event = parse(payload)
        self.assertIsInstance(event, event_type,
                              f"{payload} parsed as {type(event).__name__}")
        for field, want in expected.items():
            got = getattr(event, field)
            if isinstance(want, float) and field in self.RELATIVE_TOLERANCE:
                self.assertAlmostEqual(got / want, 1.0, delta=self.RELATIVE_TOLERANCE[field],
                                       msg=f"{field}: {got} vs {want}")
            elif isinstance(want, float):
                self.assertAlmostEqual(got, want, delta=self.ABSOLUTE_TOLERANCE.get(field, 0.01),
                                       msg=f"{field}")
            else:
                self.assertEqual(got, want, f"{field}")

    def test_channel_fader(self):
        for db in (-60.0, -10.0, 0.0, 10.0):
            self.assert_round_trip(encoder.channel_fader_db(4, db),
                                   ev.FaderMoved, channel=4, db=db)

    def test_master_fader_tops_out_at_unity(self):
        for db in (-20.0, -5.0, 0.0):
            self.assert_round_trip(encoder.master_fader_db(db),
                                   ev.MasterFaderMoved, db=db)

    def test_channel_on(self):
        self.assert_round_trip(encoder.channel_on(2, True), ev.MuteChanged,
                               channel=2, muted=False)
        self.assert_round_trip(encoder.channel_on(2, False), ev.MuteChanged,
                               channel=2, muted=True)

    def test_master_on(self):
        self.assert_round_trip(encoder.master_on(False), ev.MasterMuteChanged, muted=True)

    def test_pan(self):
        for value in (-1.0, -0.5, 0.0, 0.5, 1.0):
            self.assert_round_trip(encoder.pan(0, value), ev.PanMoved,
                                   channel=0, value=value)

    def test_surround_axes(self):
        for axis in ("x", "y"):
            self.assert_round_trip(encoder.surround(3, axis, -1.0), ev.SurroundMoved,
                                   channel=3, axis=axis, value=-1.0)

    def test_eq_across_bands_and_selectors(self):
        for band in (1, 2, 3, 4):
            self.assert_round_trip(encoder.eq_gain(1, band, 6.0), ev.EqChanged,
                                   selector="channel", channel=1, band=band, gain_db=6.0)
            self.assert_round_trip(encoder.eq_freq(1, band, 1000.0), ev.EqChanged,
                                   band=band, freq_hz=1000.0)
            self.assert_round_trip(encoder.eq_q(1, band, 1.0), ev.EqChanged,
                                   band=band, q=1.0)
        self.assert_round_trip(encoder.eq_gain(0, 1, -3.0, selector="master"),
                               ev.EqChanged, selector="master", channel=None, gain_db=-3.0)
        self.assert_round_trip(encoder.eq_gain(2, 1, -3.0, selector="aux"),
                               ev.EqChanged, selector="aux", channel=2, gain_db=-3.0)

    def test_eq_filter_types_and_enable(self):
        self.assert_round_trip(encoder.eq_filter_type(0, 1, "HPF"), ev.EqChanged,
                               band=1, filter_type="HPF")
        self.assert_round_trip(encoder.eq_filter_type(0, 4, "LPF"), ev.EqChanged,
                               band=4, filter_type="LPF")
        self.assert_round_trip(encoder.eq_enable(0, 1, True), ev.EqChanged,
                               band=1, enabled=True)

    def test_aux_and_bus(self):
        for aux in (1, 7, 8):
            self.assert_round_trip(encoder.aux_send_db(aux, 5, -10.0), ev.AuxSendMoved,
                                   aux=aux, channel=5, db=-10.0)
            self.assert_round_trip(encoder.aux_master_db(aux, -10.0), ev.AuxMasterMoved,
                                   aux=aux, db=-10.0)
            self.assert_round_trip(encoder.aux_on(aux, True), ev.AuxOnChanged, aux=aux, on=True)
        for bus in (1, 5, 8):
            self.assert_round_trip(encoder.bus_fader_db(bus, -10.0), ev.BusFaderMoved,
                                   bus=bus, db=-10.0)
            self.assert_round_trip(encoder.bus_on(bus, False), ev.BusOnChanged, bus=bus, on=False)

    def test_eq_on_and_attenuation(self):
        for selector, channel in (("channel", 1), ("aux", 2), ("master", 0)):
            expected_channel = None if selector == "master" else channel
            self.assert_round_trip(encoder.eq_on(channel, False, selector=selector),
                                   ev.EqOnChanged, selector=selector,
                                   channel=expected_channel, on=False)
        for db in (12.0, 0.0, -96.0):
            self.assert_round_trip(encoder.attenuation(3, db),
                                   ev.AttenuationChanged, channel=3, db=db)

    def test_solo(self):
        self.assert_round_trip(encoder.solo(6, True), ev.SoloChanged, channel=6, soloed=True)

    def test_st_in_channels(self):
        # ST-IN 1 is track index 32; the L slot is the one that carries the value.
        self.assert_round_trip(encoder.channel_fader_db(32, 0.0), ev.FaderMoved,
                               channel=32, db=0.0)

    def test_state_requests(self):
        requests = encoder.state_requests()
        self.assertTrue(all(len(r) == 8 for r in requests), "requests carry no data bytes")
        self.assertEqual(len(requests), len(set(map(tuple, requests))), "no duplicates")
        # ST-IN right slots are linked duplicates and must not be asked for.
        st_right = {protocol.ST_IN_FIRST + 2 * i + 1 for i in range(protocol.ST_IN_COUNT)}
        asked = {r[7] for r in requests}
        self.assertFalse(asked & st_right, "must not request linked R slots")

    def test_parameter_request_is_distinct(self):
        request = encoder.request_channel_fader(0)
        self.assertEqual(len(request), 8, "a request carries no data bytes")
        self.assertNotEqual(request[1], encoder.channel_fader(0, 0)[1],
                            "request must use SUB STATUS 3n, not 1n")

    def test_st_in_tracks_write_their_left_slot(self):
        # Track index 33 is ST-IN 2, whose channel byte is 34 (the pair's L
        # slot); writing the index directly would hit 33 = ST-IN 1's R slot
        # and move the wrong strip.
        for track_index, byte in [(32, 32), (33, 34), (34, 36), (35, 38)]:
            payload = encoder.channel_fader(track_index, 500)
            self.assertEqual(payload[7], byte)
            # and the round trip still parses to the same track
            event = parse(payload)
            self.assertEqual(event.channel, track_index)

    def test_unknown_track_index_is_rejected(self):
        for bad in (-1, 36, 100):
            with self.assertRaises(ValueError):
                encoder.channel_fader(bad, 500)


if __name__ == "__main__":
    unittest.main()
