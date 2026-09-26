"""Raw 01V96i SysEx -> semantic events.

Message layout (docs/01v96i.md §2): the payload seen here excludes F0/F7, so
B0..B4 are the header, B5 is the Element no., B6 the Parameter no., B7 the
Channel no. (or an L/R slot for masters) and B8..B11 the value.

Adding a control means adding one template and one factory to MESSAGES; nothing
else in the codebase needs to change.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from . import events as ev
from . import protocol as p

# A mask entry is a literal to match, or None for "any value".
Template = List[Optional[int]]
_ = None  # reads as a wildcard in the tables below

H = [p.YAMAHA_ID, p.DEVICE_BYTE, p.GROUP_ID]
FORM_A = H + [p.MODEL_UNIVERSAL, p.ADDRESS_EDIT_BUFFER]
FORM_PATCH = H + [p.MODEL_01V96I, p.ADDRESS_PATCH]
FORM_SETUP = H + [p.MODEL_01V96I, p.ADDRESS_SETUP]
FORM_BACKUP = H + [p.MODEL_01V96I, p.ADDRESS_BACKUP]

# Element numbers (docs/01v96i.md §2).
EL_LAYER = 0x09
EL_CH_ON = 0x1A
EL_PAN = 0x1B
EL_CH_FADER = 0x1C
EL_ATT = 0x1D
EL_CH_NAME = 0x04
EL_CH_EQ = 0x20
EL_AUX_SEND = 0x23
EL_SURROUND = 0x25
EL_BUS_ON = 0x29
EL_BUS_FADER = 0x2B
EL_SOLO = 0x2E
EL_SETUP_FLAG = 0x2F
EL_SOLO_STATUS = 0x30
EL_AUX_ON = 0x36
EL_AUX_FADER = 0x39
EL_AUX_EQ = 0x3C
EL_EQ_BAND_SELECT = 0x4C
EL_MASTER_ON = 0x4D
EL_MASTER_FADER = 0x4F
EL_MASTER_EQ = 0x52
EL_CH_ON_B = 0x5A
EL_BUS_ON_B = 0x5B
EL_AUX_ON_B = 0x5C
EL_MASTER_ON_B = 0x5E

# Aux number lives in the Parameter no. as 3*aux - 1.
AUX_SEND_PARAMS = {3 * aux - 1: aux for aux in range(1, 9)}

SURROUND_AXES = {5: "x", 6: "y"}

# The slot straight after band 4's enable: the whole-EQ bypass.
EQ_ON_PARAM = 15


def matches(data: List[int], template: Template) -> bool:
    """True when every non-wildcard byte of the template equals the payload."""
    return len(data) == len(template) and all(
        t is None or d == t for d, t in zip(data, template)
    )


def _channel(data: List[int]) -> Optional[int]:
    return p.channel_index(data[7])


def _linked_slot(data: List[int]) -> ev.Ignored:
    """The right-hand slot of a linked stereo pair, carrying a duplicate value."""
    return ev.Ignored(tuple(data), "linked stereo slot")


# --- Factories: payload -> event, or None to drop the message ---------------- #

def _keepalive(data):
    return ev.Keepalive(tuple(data))


def _channel_fader(data):
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    return ev.FaderMoved(tuple(data), ch, p.fader_db(p.decode_value(data)))


def _master_fader(data):
    # B7 is the L/R slot; both carry the same value, so only L is acted on.
    if data[7] != 0:
        return _linked_slot(data)
    return ev.MasterFaderMoved(tuple(data), p.fader_db(p.decode_value(data), unity_top=True))


def _aux_send(data):
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    return ev.AuxSendMoved(tuple(data), AUX_SEND_PARAMS[data[6]], ch,
                           p.fader_db(p.decode_value(data), unity_top=True))


def _aux_master(data):
    return ev.AuxMasterMoved(tuple(data), data[7] + 1,
                             p.fader_db(p.decode_value(data), unity_top=True))


def _bus_fader(data):
    return ev.BusFaderMoved(tuple(data), data[7] + 1,
                            p.fader_db(p.decode_value(data), unity_top=True))


def _mute(data):
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    return ev.MuteChanged(tuple(data), ch, data[11] == 0)


def _master_mute(data):
    if data[7] != 0:
        return _linked_slot(data)
    return ev.MasterMuteChanged(tuple(data), data[11] == 0)


def _bus_on(data):
    return ev.BusOnChanged(tuple(data), data[7] + 1, bool(data[11]))


def _aux_on(data):
    return ev.AuxOnChanged(tuple(data), data[7] + 1, bool(data[11]))


def _pan(data):
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    return ev.PanMoved(tuple(data), ch, p.decode_value(data) / p.PAN_MAX)


def _surround(data):
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    return ev.SurroundMoved(tuple(data), ch, SURROUND_AXES[data[6]],
                            p.decode_value(data) / p.PAN_MAX)


def _channel_name(data):
    channel = _channel(data)
    if channel is None:
        return _linked_slot(data)
    code = data[11]
    return ev.ChannelNameChar(tuple(data), channel, data[6],
                              chr(code) if 32 <= code < 127 else " ")


def _solo(data):
    # Params 0 and 2 mirror each other on every press; act on one only.
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    if data[6] != 0:
        return ev.Ignored(tuple(data), "solo mirror parameter")
    return ev.SoloChanged(tuple(data), ch, bool(data[11]))


def _eq(data):
    # Three EQ elements share one parameter layout: channel, aux and master.
    if data[5] == EL_MASTER_EQ:
        if data[7] != 0:      # L/R slot, linked -- act on L only
            return _linked_slot(data)
        selector, channel = "master", None
    elif data[5] == EL_AUX_EQ:
        selector, channel = "aux", data[7]
    else:
        selector, channel = "channel", _channel(data)
        if channel is None:
            return _linked_slot(data)
    band, control = p.EQ_PARAMS[data[6]]
    raw = p.decode_value(data)
    if control == "gain":
        return ev.EqChanged(tuple(data), selector, channel, band,
                            gain_db=raw / p.EQ_GAIN_STEPS_PER_DB)
    if control == "freq":
        return ev.EqChanged(tuple(data), selector, channel, band, freq_hz=p.eq_freq_hz(raw))
    if control == "enable":
        return ev.EqChanged(tuple(data), selector, channel, band, enabled=bool(raw))
    filter_type = p.EQ_TYPE_CODES.get(raw)
    if filter_type is not None:
        return ev.EqChanged(tuple(data), selector, channel, band, filter_type=filter_type)
    return ev.EqChanged(tuple(data), selector, channel, band, q=p.eq_q(raw))


def _eq_on(data):
    if data[5] == EL_MASTER_EQ:
        if data[7] != 0:
            return _linked_slot(data)
        selector, channel = "master", None
    elif data[5] == EL_AUX_EQ:
        selector, channel = "aux", data[7]
    else:
        selector, channel = "channel", _channel(data)
        if channel is None:
            return _linked_slot(data)
    return ev.EqOnChanged(tuple(data), selector, channel, bool(data[11]))


def _attenuation(data):
    ch = _channel(data)
    if ch is None:
        return _linked_slot(data)
    # Tenths of a dB, like EQ gain.
    return ev.AttenuationChanged(tuple(data), ch,
                                 p.decode_value(data) / p.EQ_GAIN_STEPS_PER_DB)


def _status(kind: str) -> Callable[[List[int]], ev.MixerEvent]:
    def factory(data):
        return ev.ConsoleStatus(tuple(data), kind, data[6], data[11])
    return factory


# --- The message table ------------------------------------------------------- #
# Order matters: first match wins. Keepalive first, the broad EQ match last.

MESSAGES = [
    ("keepalive", list(p.KEEPALIVE), None, _keepalive),
    ("master_fader", FORM_A + [EL_MASTER_FADER, 0, _, _, _, _, _],
     lambda d: d[7] in (0, 1), _master_fader),
    ("master_mute_form_a", FORM_A + [EL_MASTER_ON, 0, _, 0, 0, 0, _],
     lambda d: d[11] in (0, 1), _master_mute),
    ("master_mute_form_b", FORM_BACKUP + [EL_MASTER_ON_B, 0, _, 0, 0, 0, _],
     lambda d: d[11] in (0, 1), _master_mute),
    ("channel_fader", FORM_A + [EL_CH_FADER, 0, _, _, _, _, _],
     lambda d: p.is_channel_byte(d[7]), _channel_fader),
    ("channel_mute_form_a", FORM_A + [EL_CH_ON, 0, _, 0, 0, 0, _],
     lambda d: p.is_channel_byte(d[7]) and d[11] in (0, 1), _mute),
    ("channel_mute_form_b", FORM_BACKUP + [EL_CH_ON_B, 0, _, 0, 0, 0, _],
     lambda d: p.is_channel_byte(d[7]) and d[11] in (0, 1), _mute),
    ("aux_send", FORM_A + [EL_AUX_SEND, _, _, _, _, _, _],
     lambda d: p.is_channel_byte(d[7]) and d[6] in AUX_SEND_PARAMS, _aux_send),
    ("aux_master", FORM_A + [EL_AUX_FADER, 0, _, _, _, _, _],
     lambda d: 0 <= d[7] <= 7, _aux_master),
    ("channel_name", FORM_PATCH + [EL_CH_NAME, _, _, 0, 0, 0, _],
     lambda d: d[7] in p.NAMED_CHANNELS and d[6] in p.NAME_INDICES, _channel_name),
    ("solo", FORM_SETUP + [EL_SOLO, _, _, 0, 0, 0, _],
     lambda d: p.is_channel_byte(d[7]) and d[6] in (0, 2) and d[11] in (0, 1), _solo),
    ("solo_status", FORM_BACKUP + [EL_SOLO_STATUS, _, 0, 0, 0, 0, _], None,
     _status("solo_status")),
    ("eq_band_select", FORM_BACKUP + [EL_EQ_BAND_SELECT, 0, 0, 0, 0, 0, _],
     lambda d: 0 <= d[11] <= 3, _status("eq_band_select")),
    ("layer_select", FORM_SETUP + [EL_LAYER, _, _, _, _, _, _], None, _status("layer_select")),
    ("layer_select_b", FORM_BACKUP + [EL_LAYER, _, _, _, _, _, _], None, _status("layer_select")),
    ("setup_channel_flag", FORM_SETUP + [EL_SETUP_FLAG, _, _, 0, 0, 0, _], None,
     _status("setup_channel_flag")),
    ("surround_mode", FORM_A + [EL_SURROUND, 0, _, 0, 0, 0, _], None, _status("surround_mode")),
    ("bus_fader", FORM_A + [EL_BUS_FADER, 0, _, _, _, _, _],
     lambda d: 0 <= d[7] <= 7, _bus_fader),
    ("bus_on", FORM_A + [EL_BUS_ON, 0, _, 0, 0, 0, _],
     lambda d: 0 <= d[7] <= 7 and d[11] in (0, 1), _bus_on),
    ("bus_on_form_b", FORM_BACKUP + [EL_BUS_ON_B, 0, _, 0, 0, 0, _],
     lambda d: 0 <= d[7] <= 7 and d[11] in (0, 1), _bus_on),
    ("aux_on", FORM_A + [EL_AUX_ON, 0, _, 0, 0, 0, _],
     lambda d: 0 <= d[7] <= 7 and d[11] in (0, 1), _aux_on),
    ("aux_on_form_b", FORM_BACKUP + [EL_AUX_ON_B, 0, _, 0, 0, 0, _],
     lambda d: 0 <= d[7] <= 7 and d[11] in (0, 1), _aux_on),
    ("attenuation", FORM_A + [EL_ATT, 0, _, _, _, _, _],
     lambda d: p.is_channel_byte(d[7]), _attenuation),
    ("eq_on", FORM_A + [_, EQ_ON_PARAM, _, 0, 0, 0, _],
     lambda d: d[5] in (EL_CH_EQ, EL_AUX_EQ, EL_MASTER_EQ) and d[11] in (0, 1), _eq_on),
    ("pan", FORM_A + [EL_PAN, 0, _, _, _, _, _], lambda d: p.is_channel_byte(d[7]), _pan),
    ("surround_y", FORM_A + [EL_SURROUND, 6, _, _, _, _, _],
     lambda d: p.is_channel_byte(d[7]), _surround),
    ("surround_x", FORM_A + [EL_SURROUND, 5, _, _, _, _, _],
     lambda d: p.is_channel_byte(d[7]), _surround),
    ("eq", FORM_A + [_, _, _, _, _, _, _],
     lambda d: d[5] in (EL_CH_EQ, EL_AUX_EQ, EL_MASTER_EQ) and d[6] in p.EQ_PARAMS
     and (p.is_channel_byte(d[7]) if d[5] == EL_CH_EQ else 0 <= d[7] <= 7), _eq),
]


def identify(data: List[int]) -> Optional[str]:
    """Name of the first matching message type, or None if unrecognised."""
    for name, template, guard, _factory in MESSAGES:
        if matches(data, template) and (guard is None or guard(data)):
            return name
    return None


def parse(data: List[int]) -> Optional[ev.MixerEvent]:
    """Decode one SysEx payload into an event, or None if unrecognised/ignored."""
    for _name, template, guard, factory in MESSAGES:
        if matches(data, template) and (guard is None or guard(data)):
            return factory(data)
    return None
