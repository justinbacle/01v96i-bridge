"""Wire-level facts about the Yamaha 01V96i's SysEx parameter changes.

Pure functions over ``list[int]`` — no mido, no OSC, no I/O. Everything here is
sourced from the Reference Manual §2.8.3 or from on-device captures; see
docs/01v96i.md, which is the authority and should be updated before this file.
"""
from __future__ import annotations

import math
from typing import Optional

# --- Framing (Reference Manual §2.8.3) --------------------------------------- #

YAMAHA_ID = 0x43
DEVICE_BYTE = 0x10          # SUB STATUS 1n, n = device number; n=0 observed
REQUEST_DEVICE_BYTE = 0x30  # SUB STATUS 3n marks a parameter *request*
GROUP_ID = 0x3E             # digital mixer
MODEL_UNIVERSAL = 0x7F      # "Universal" model ID
MODEL_01V96I = 0x1A         # 01V96i-specific model ID

ADDRESS_EDIT_BUFFER = 0x01
ADDRESS_PATCH = 0x02
ADDRESS_SETUP = 0x03
ADDRESS_BACKUP = 0x04

# Emitted by the console roughly 6x/second. ADDRESS 0x7F is undocumented.
KEEPALIVE = (YAMAHA_ID, DEVICE_BYTE, GROUP_ID, MODEL_01V96I, 0x7F)

# --- Remote metering (docs/01v96i.md §3.10) ----------------------------------- #
# One request makes the console stream a bulk meter frame every ~60 ms for
# 10 s; re-request to keep it running. The page is the first address byte:
#   page 0 = 32 channel input levels (14-bit each)
#   page 4 = stereo master L/R (two 14-bit levels)
# Other pages stream too (1, 2, 5 = 8 levels each; likely auxes, buses and
# ST-IN) but read zero on this desk with no aux sends -- unidentified.
#
# The reply is 43 10 3E 1A 21 <page> 00 00 followed by the levels, 14-bit
# each, MSB first. Open inputs read ~90-150 (preamp noise), so the scale is
# fine-grained, not the front panel's 0..32 segments.
METER_ELEMENT = 0x21
METER_CHANNEL_PAGE = 0x00
METER_MASTER_PAGE = 0x04
METER_LEVELS = 32
METER_LEVEL_MAX = (1 << 14) - 1

# --- Channel numbering (docs/01v96i.md §6) ----------------------------------- #

MONO_CHANNELS = 32   # CH1..CH32, across the 1-16 and 17-32 layers
ST_IN_FIRST = 32     # ST-IN 1L, 1R, 2L, ... 4R
ST_IN_COUNT = 4


def is_channel_byte(b7: int) -> bool:
    """True for any channel byte the bridge recognises, including both ST-IN slots."""
    return 0 <= b7 < MONO_CHANNELS or 0 <= b7 - ST_IN_FIRST < ST_IN_COUNT * 2


def channel_index(b7: int) -> Optional[int]:
    """0-based track index for a channel byte, or None to ignore.

    The two sides of each ST-IN pair are linked and carry identical values, so the
    R slot returns None and ST-IN 1..4 land after the mono channels.
    """
    if 0 <= b7 < MONO_CHANNELS:
        return b7
    offset = b7 - ST_IN_FIRST
    if 0 <= offset < ST_IN_COUNT * 2:
        return None if offset % 2 else MONO_CHANNELS + offset // 2
    return None


# --- Channel names (docs/01v96i.md §3.9) ------------------------------------- #

# One character per message, the parameter number being the index. Only the 32
# mono channels have names; ST-IN returns nothing.
NAME_SHORT = range(0, 4)      # 4 characters
NAME_LONG = range(4, 20)      # 16 characters
NAME_INDICES = range(0, 20)
NAMED_CHANNELS = range(0, MONO_CHANNELS)


def name_text(characters: dict, indices: range) -> str:
    """Assemble a name from {index: byte}, blanks for anything not yet seen."""
    codes = (characters.get(i, 32) for i in indices)
    return "".join(chr(c) if 32 <= c < 127 else " " for c in codes).rstrip()


# --- The data field (docs/01v96i.md §4.1) ------------------------------------ #

VALUE_BITS = 28  # four 7-bit bytes


def decode_value(data: list[int]) -> int:
    """Decode bytes 8..11 as a 28-bit two's-complement integer."""
    raw = (data[8] << 21) | (data[9] << 14) | (data[10] << 7) | data[11]
    if raw >= 1 << (VALUE_BITS - 1):
        raw -= 1 << VALUE_BITS
    return raw


def encode_value(value: int) -> list[int]:
    """Inverse of decode_value: an integer as four 7-bit bytes, MSB first."""
    raw = value & ((1 << VALUE_BITS) - 1)
    return [(raw >> 21) & 0x7F, (raw >> 14) & 0x7F, (raw >> 7) & 0x7F, raw & 0x7F]


# --- Faders (docs/01v96i.md §4.2) -------------------------------------------- #

FADER_MAX_RAW = 1023

# (raw, dB) breakpoints, interpolated linearly in dB. Anchors at raw 0, 823 and
# 1023 are measured; the shape between them is the IEC 60268-17 console taper.
FADER_LAW = [
    (0, -90.0),     # bottom stop; reported as -inf
    (55, -70.0),
    (166, -50.0),
    (331, -30.0),
    (552, -10.0),
    (823, 0.0),     # measured
    (1023, 10.0),   # measured
]

# Stereo, bus, aux master and aux send faders end at unity instead of +10 dB.
FADER_LAW_UNITY = [(raw, db - 10.0) for raw, db in FADER_LAW]


def fader_db(raw: int, unity_top: bool = False) -> float:
    """Convert a fader position index to dB; unity_top for faders ending at 0 dB."""
    law = FADER_LAW_UNITY if unity_top else FADER_LAW
    raw = max(law[0][0], min(law[-1][0], raw))
    for (r0, d0), (r1, d1) in zip(law, law[1:]):
        if raw <= r1:
            span = r1 - r0
            return d0 if span == 0 else d0 + (d1 - d0) * (raw - r0) / span
    return law[-1][1]


def fader_raw(db: float, unity_top: bool = False) -> int:
    """Inverse of fader_db, for driving the console's motorised faders."""
    law = FADER_LAW_UNITY if unity_top else FADER_LAW
    db = max(law[0][1], min(law[-1][1], db))
    for (r0, d0), (r1, d1) in zip(law, law[1:]):
        if db <= d1:
            span = d1 - d0
            return int(round(r0 if span == 0 else r0 + (r1 - r0) * (db - d0) / span))
    return law[-1][0]


# --- Pan and surround (docs/01v96i.md §4.3) ---------------------------------- #

PAN_MAX = 63  # console shows L63 .. C .. R63


def pan_raw(value: float) -> int:
    """-1.0 .. +1.0 -> the console's own -63 .. +63."""
    return max(-PAN_MAX, min(PAN_MAX, int(round(value * PAN_MAX))))


# --- EQ (docs/01v96i.md §4.4, §5.3) ------------------------------------------ #

EQ_GAIN_STEPS_PER_DB = 10  # raw is tenths of a dB

EQ_FREQ_RAW_MIN, EQ_FREQ_RAW_MAX = 5, 124
EQ_FREQ_HZ_MIN, EQ_FREQ_HZ_MAX = 21.2, 20000.0

# Parameter no. -> (band, control). Bands are contiguous blocks; bands 1 and 4
# carry an extra "enable" because the console repurposes their gain knob as the
# HPF/LPF on/off switch. All observed except params 9 and 12 (band 3 and 4 freq).
EQ_PARAMS = {
    1: (1, "q"), 2: (1, "freq"), 3: (1, "gain"), 4: (1, "enable"),
    5: (2, "q"), 6: (2, "freq"), 7: (2, "gain"),
    8: (3, "q"), 9: (3, "freq"), 10: (3, "gain"),
    11: (4, "q"), 12: (4, "freq"), 13: (4, "gain"), 14: (4, "enable"),
}

# Global type codes; each band exposes only the two that apply to it.
EQ_TYPE_CODES = {41: "L.Shelf", 42: "H.Shelf", 43: "LPF", 44: "HPF"}


def eq_freq_hz(raw: int) -> float:
    """Single-byte logarithmic frequency, 21.2 Hz .. 20 kHz."""
    span = EQ_FREQ_RAW_MAX - EQ_FREQ_RAW_MIN
    ratio = EQ_FREQ_HZ_MAX / EQ_FREQ_HZ_MIN
    return EQ_FREQ_HZ_MIN * (ratio ** ((raw - EQ_FREQ_RAW_MIN) / span))


def eq_q(raw: int) -> float:
    """Bell Q from the shared type/Q parameter: raw 0 -> Q 10, raw 40 -> Q 0.1."""
    return 10 * (0.1 / 10) ** (raw / 40)


def eq_gain_raw(db: float) -> int:
    """dB -> tenths of a dB."""
    return int(round(db * EQ_GAIN_STEPS_PER_DB))


def eq_freq_raw(hz: float) -> int:
    """Inverse of eq_freq_hz, clamped to the console's range."""
    hz = max(EQ_FREQ_HZ_MIN, min(EQ_FREQ_HZ_MAX, hz))
    span = EQ_FREQ_RAW_MAX - EQ_FREQ_RAW_MIN
    ratio = EQ_FREQ_HZ_MAX / EQ_FREQ_HZ_MIN
    return int(round(EQ_FREQ_RAW_MIN + span * (math.log(hz / EQ_FREQ_HZ_MIN) / math.log(ratio))))


def eq_q_raw(q: float) -> int:
    """Inverse of eq_q, clamped to the bell range (Q 10 .. 0.1)."""
    q = max(0.1, min(10.0, q))
    return int(round(40 * math.log(q / 10) / math.log(0.1 / 10)))
