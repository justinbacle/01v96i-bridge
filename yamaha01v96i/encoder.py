"""Build 01V96i SysEx messages to send *to* the console.

The mirror of parser.py. Payloads exclude the F0/F7 framing, matching what the
parser consumes and what mido's ``Message("sysex", data=...)`` expects, so a
message can be round-tripped through parse() to check it before sending.

The console only acts on these if Parameter Change **Rx** is enabled in its MIDI
setup and its device number matches (Reference Manual §2.8.3.2).
"""
from __future__ import annotations

from typing import List

from . import parser as _parser
from . import protocol as p


def parameter_change(element: int, param: int, channel: int, value: int) -> List[int]:
    """A parameter change for the edit buffer: the console applies it immediately."""
    return [p.YAMAHA_ID, p.DEVICE_BYTE, p.GROUP_ID, p.MODEL_UNIVERSAL, p.ADDRESS_EDIT_BUFFER,
            element, param, channel] + p.encode_value(value)


def parameter_request(element: int, param: int, channel: int) -> List[int]:
    """Ask the console for a parameter's current value.

    Same message with SUB STATUS 3n instead of 1n and no data bytes; the console
    replies with the corresponding parameter change (Reference Manual §2.8.3.3).
    """
    return [p.YAMAHA_ID, p.REQUEST_DEVICE_BYTE, p.GROUP_ID, p.MODEL_UNIVERSAL,
            p.ADDRESS_EDIT_BUFFER, element, param, channel]


def channel_fader(channel: int, raw: int) -> List[int]:
    """Set a channel fader by position index (0..1023). See protocol.fader_raw()."""
    return parameter_change(_parser.EL_CH_FADER, 0, channel, raw)


def channel_fader_db(channel: int, db: float) -> List[int]:
    """Set a channel fader to a dB value, via the measured fader law."""
    return channel_fader(channel, p.fader_raw(db))


def channel_on(channel: int, on: bool) -> List[int]:
    """Set a channel's ON state (True = unmuted, matching the console)."""
    return parameter_change(_parser.EL_CH_ON, 0, channel, int(on))


def pan(channel: int, value: float) -> List[int]:
    """Set a channel's pan, -1.0 (full left) .. +1.0 (full right)."""
    return parameter_change(_parser.EL_PAN, 0, channel, p.pan_raw(value))


def surround(channel: int, axis: str, value: float) -> List[int]:
    """Set a surround axis, "x" or "y", -1.0 .. +1.0."""
    param = {"x": 5, "y": 6}[axis]
    return parameter_change(_parser.EL_SURROUND, param, channel, p.pan_raw(value))


def master_fader(raw: int) -> List[int]:
    """Set the stereo fader by position index; slot 0 is the L of the linked pair."""
    return parameter_change(_parser.EL_MASTER_FADER, 0, 0, raw)


def master_fader_db(db: float) -> List[int]:
    """Set the stereo fader to a dB value. It tops out at unity, not +10 dB."""
    return master_fader(p.fader_raw(db, unity_top=True))


def master_on(on: bool) -> List[int]:
    return parameter_change(_parser.EL_MASTER_ON, 0, 0, int(on))


def aux_send_db(aux: int, channel: int, db: float) -> List[int]:
    """Set a channel's send to an aux (1-based aux number)."""
    param = next(k for k, v in _parser.AUX_SEND_PARAMS.items() if v == aux)
    return parameter_change(_parser.EL_AUX_SEND, param, channel, p.fader_raw(db, unity_top=True))


def aux_master_db(aux: int, db: float) -> List[int]:
    return parameter_change(_parser.EL_AUX_FADER, 0, aux - 1, p.fader_raw(db, unity_top=True))


def aux_on(aux: int, on: bool) -> List[int]:
    return parameter_change(_parser.EL_AUX_ON, 0, aux - 1, int(on))


def bus_fader_db(bus: int, db: float) -> List[int]:
    return parameter_change(_parser.EL_BUS_FADER, 0, bus - 1, p.fader_raw(db, unity_top=True))


def bus_on(bus: int, on: bool) -> List[int]:
    return parameter_change(_parser.EL_BUS_ON, 0, bus - 1, int(on))


def _eq_element(selector: str) -> int:
    return {"channel": _parser.EL_CH_EQ, "aux": _parser.EL_AUX_EQ,
            "master": _parser.EL_MASTER_EQ}[selector]


def _eq_param(band: int, control: str) -> int:
    return next(k for k, v in p.EQ_PARAMS.items() if v == (band, control))


def eq_gain(channel: int, band: int, db: float, selector: str = "channel") -> List[int]:
    return parameter_change(_eq_element(selector), _eq_param(band, "gain"),
                            channel, p.eq_gain_raw(db))


def eq_freq(channel: int, band: int, hz: float, selector: str = "channel") -> List[int]:
    return parameter_change(_eq_element(selector), _eq_param(band, "freq"),
                            channel, p.eq_freq_raw(hz))


def eq_q(channel: int, band: int, q: float, selector: str = "channel") -> List[int]:
    return parameter_change(_eq_element(selector), _eq_param(band, "q"),
                            channel, p.eq_q_raw(q))


def eq_filter_type(channel: int, band: int, filter_type: str,
                   selector: str = "channel") -> List[int]:
    """Select a non-bell filter type: L.Shelf, H.Shelf, LPF or HPF."""
    code = next(k for k, v in p.EQ_TYPE_CODES.items() if v == filter_type)
    return parameter_change(_eq_element(selector), _eq_param(band, "q"), channel, code)


def eq_enable(channel: int, band: int, enabled: bool, selector: str = "channel") -> List[int]:
    """HPF/LPF on-off, bands 1 and 4 only."""
    return parameter_change(_eq_element(selector), _eq_param(band, "enable"),
                            channel, int(enabled))


def eq_on(channel: int, on: bool, selector: str = "channel") -> List[int]:
    """Whole-EQ bypass, distinct from bands 1/4's HPF/LPF enable."""
    return parameter_change(_eq_element(selector), _parser.EQ_ON_PARAM, channel, int(on))


def attenuation(channel: int, db: float) -> List[int]:
    """Set the EQ page's ATT trim, -96.0 .. +12.0 dB."""
    db = max(-96.0, min(12.0, db))
    return parameter_change(_parser.EL_ATT, 0, channel, p.eq_gain_raw(db))


def solo(channel: int, soloed: bool) -> List[int]:
    """Solo lives in the Setup address space, not the edit buffer."""
    return [p.YAMAHA_ID, p.DEVICE_BYTE, p.GROUP_ID, p.MODEL_01V96I, p.ADDRESS_SETUP,
            _parser.EL_SOLO, 0, channel] + p.encode_value(int(soloed))


def request_channel_fader(channel: int) -> List[int]:
    return parameter_request(_parser.EL_CH_FADER, 0, channel)


def request_channel_name(channel: int, index: int) -> List[int]:
    """Ask for one character of a channel's name (docs/01v96i.md §3.9).

    Names live in the patch-data space, not the edit buffer, so this cannot use
    parameter_request().
    """
    return [p.YAMAHA_ID, p.REQUEST_DEVICE_BYTE, p.GROUP_ID, p.MODEL_01V96I,
            p.ADDRESS_PATCH, _parser.EL_CH_NAME, index, channel]


def channel_bytes() -> List[int]:
    """Every channel byte worth requesting: the mono channels plus each ST-IN L slot.

    The ST-IN R slots are skipped -- they are linked and carry a duplicate value.
    """
    mono = list(range(p.MONO_CHANNELS))
    st_in = [p.ST_IN_FIRST + 2 * i for i in range(p.ST_IN_COUNT)]
    return mono + st_in


def state_requests() -> List[List[int]]:
    """Requests covering everything the parser understands.

    Replies arrive as ordinary parameter changes, so feeding them through the
    normal parse -> backend path populates the backend with no special casing.
    Roughly 800 messages; the console answered 32 in 16 ms, so this completes
    in well under a second.
    """
    requests: List[List[int]] = []
    for channel in channel_bytes():
        requests.append(parameter_request(_parser.EL_CH_FADER, 0, channel))
        requests.append(parameter_request(_parser.EL_CH_ON, 0, channel))
        requests.append(parameter_request(_parser.EL_PAN, 0, channel))
        requests.append(parameter_request(_parser.EL_ATT, 0, channel))
        for axis_param in _parser.SURROUND_AXES:
            requests.append(parameter_request(_parser.EL_SURROUND, axis_param, channel))
        for eq_param in list(p.EQ_PARAMS) + [_parser.EQ_ON_PARAM]:
            requests.append(parameter_request(_parser.EL_CH_EQ, eq_param, channel))

    requests.append(parameter_request(_parser.EL_MASTER_FADER, 0, 0))
    requests.append(parameter_request(_parser.EL_MASTER_ON, 0, 0))
    for eq_param in list(p.EQ_PARAMS) + [_parser.EQ_ON_PARAM]:
        requests.append(parameter_request(_parser.EL_MASTER_EQ, eq_param, 0))

    # Names are one request per character, and only the mono channels have them.
    for channel in p.NAMED_CHANNELS:
        for index in p.NAME_INDICES:
            requests.append(request_channel_name(channel, index))

    for index in range(8):
        requests.append(parameter_request(_parser.EL_AUX_FADER, 0, index))
        requests.append(parameter_request(_parser.EL_AUX_ON, 0, index))
        requests.append(parameter_request(_parser.EL_BUS_FADER, 0, index))
        requests.append(parameter_request(_parser.EL_BUS_ON, 0, index))
    return requests
