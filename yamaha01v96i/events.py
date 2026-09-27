"""Semantic events emitted by the 01V96i parser.

Backends consume these and never see raw bytes. Every event keeps ``raw`` so a
capture can be replayed and an encoding re-derived without losing information.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class MixerEvent:
    """Base class for everything the parser emits."""
    raw: Tuple[int, ...]


@dataclass(frozen=True)
class Keepalive(MixerEvent):
    """The console's periodic heartbeat. Useful only for port detection."""


@dataclass(frozen=True)
class Ignored(MixerEvent):
    """A recognised message deliberately not acted on.

    The console emits genuine duplicates -- both slots of a linked stereo pair,
    and solo's mirrored parameter -- so one copy is dropped. Distinct from an
    unrecognised message, which the parser reports by returning None.
    """
    reason: str


@dataclass(frozen=True)
class ConsoleStatus(MixerEvent):
    """A console-side status message with no control semantics (docs/01v96i.md §8)."""
    kind: str
    param: int
    value: int


@dataclass(frozen=True)
class FaderMoved(MixerEvent):
    channel: int          # 0-based track index; ST-IN follow the mono channels
    db: float


@dataclass(frozen=True)
class MasterFaderMoved(MixerEvent):
    db: float


@dataclass(frozen=True)
class AuxSendMoved(MixerEvent):
    aux: int              # 1-based
    channel: int
    db: float


@dataclass(frozen=True)
class AuxMasterMoved(MixerEvent):
    aux: int              # 1-based
    db: float


@dataclass(frozen=True)
class BusFaderMoved(MixerEvent):
    bus: int              # 1-based
    db: float


@dataclass(frozen=True)
class MuteChanged(MixerEvent):
    channel: int
    muted: bool


@dataclass(frozen=True)
class MasterMuteChanged(MixerEvent):
    muted: bool


@dataclass(frozen=True)
class BusOnChanged(MixerEvent):
    bus: int              # 1-based
    on: bool


@dataclass(frozen=True)
class AuxOnChanged(MixerEvent):
    aux: int              # 1-based
    on: bool


@dataclass(frozen=True)
class PanMoved(MixerEvent):
    channel: int
    value: float          # -1.0 (full left) .. +1.0 (full right)


@dataclass(frozen=True)
class SurroundMoved(MixerEvent):
    channel: int
    axis: str             # "x" or "y"
    value: float          # -1.0 .. +1.0


@dataclass(frozen=True)
class EqOnChanged(MixerEvent):
    """Whole-EQ bypass, distinct from bands 1/4's HPF/LPF enable."""
    selector: str
    channel: Optional[int]
    on: bool


@dataclass(frozen=True)
class AttenuationChanged(MixerEvent):
    """The EQ page's ATT trim, -96.0 .. +12.0 dB."""
    channel: int
    db: float


@dataclass(frozen=True)
class ChannelNameChar(MixerEvent):
    """One character of a channel's name.

    The console sends a message per character, so this mirrors the wire; use
    protocol.name_text() to assemble the short and long names.
    """
    channel: int
    index: int
    char: str


@dataclass(frozen=True)
class MeterLevels(MixerEvent):
    """Every channel's level at once, as the remote-meter reply.

    The console streams this every 50 ms while metering is enabled. Levels are
    the console's own 0..32 meter scale, one per channel index 0..31.
    """
    levels: Tuple[int, ...]


@dataclass(frozen=True)
class MasterMeterLevels(MixerEvent):
    """The stereo master's L/R levels, from the master meter page."""
    levels: Tuple[int, ...]   # (left, right), 14-bit each


@dataclass(frozen=True)
class SoloChanged(MixerEvent):
    channel: int
    soloed: bool


@dataclass(frozen=True)
class EqChanged(MixerEvent):
    """One EQ parameter. Exactly one of the value fields is set."""
    selector: str                     # "channel", "aux" or "master"
    channel: Optional[int]            # 0-based channel or aux index; None for master
    band: int                         # 1..4, the console's band number
    gain_db: Optional[float] = None
    freq_hz: Optional[float] = None
    q: Optional[float] = None
    filter_type: Optional[str] = None  # set alongside q when a non-bell type is selected
    enabled: Optional[bool] = None     # HPF/LPF on-off, bands 1 and 4 only
