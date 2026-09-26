"""A live picture of the console, assembled from events.

Pure: it consumes events and produces plain data, with no MIDI, OSC or I/O. A
consumer that needs to *show* the console rather than react to individual moves
feeds every event through `apply()` and reads `snapshot()`.

Names arrive one character at a time (docs/01v96i.md §3.9), so those are
accumulated here rather than in the parser, which stays one-event-per-message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import events as ev
from . import protocol as p


@dataclass
class ChannelState:
    """Everything known about one strip."""
    index: int
    fader_db: Optional[float] = None
    muted: Optional[bool] = None
    pan: Optional[float] = None
    att_db: Optional[float] = None
    soloed: Optional[bool] = None
    surround_x: Optional[float] = None
    surround_y: Optional[float] = None
    # index -> character code, assembled on demand
    name_chars: Dict[int, int] = field(default_factory=dict)
    # aux number (1-based) -> send level in dB
    aux_sends: Dict[int, float] = field(default_factory=dict)

    @property
    def short_name(self) -> str:
        return p.name_text(self.name_chars, p.NAME_SHORT)

    @property
    def long_name(self) -> str:
        return p.name_text(self.name_chars, p.NAME_LONG)

    def label(self) -> str:
        """The best name available, falling back to the console's own numbering."""
        return (self.long_name or self.short_name
                or (f"CH{self.index + 1}" if self.index < p.MONO_CHANNELS
                    else f"ST{self.index - p.MONO_CHANNELS + 1}"))


class ConsoleState:
    """Folds events into a snapshot. Not thread-safe; guard it if shared."""

    def __init__(self) -> None:
        self.channels: Dict[int, ChannelState] = {}
        self.master_db: Optional[float] = None
        self.master_muted: Optional[bool] = None
        self.aux_masters: Dict[int, float] = {}
        self.aux_on: Dict[int, bool] = {}
        self.bus_faders: Dict[int, float] = {}
        self.bus_on: Dict[int, bool] = {}

    def channel(self, index: int) -> ChannelState:
        return self.channels.setdefault(index, ChannelState(index=index))

    def apply(self, event: ev.MixerEvent) -> bool:
        """Update from one event. Returns True if anything changed."""
        before = self._fingerprint(event)
        self._apply(event)
        return self._fingerprint(event) != before

    def _fingerprint(self, event: ev.MixerEvent) -> Any:
        """Cheap change detection: the part of the state this event can touch."""
        index = getattr(event, "channel", None)
        if isinstance(index, int) and index in self.channels:
            channel = self.channels[index]
            return (channel.fader_db, channel.muted, channel.pan, channel.att_db,
                    channel.soloed, channel.surround_x, channel.surround_y,
                    tuple(sorted(channel.name_chars.items())),
                    tuple(sorted(channel.aux_sends.items())))
        return (self.master_db, self.master_muted,
                tuple(sorted(self.aux_masters.items())), tuple(sorted(self.aux_on.items())),
                tuple(sorted(self.bus_faders.items())), tuple(sorted(self.bus_on.items())),
                index in self.channels)

    def _apply(self, event: ev.MixerEvent) -> None:
        if isinstance(event, ev.FaderMoved):
            self.channel(event.channel).fader_db = event.db
        elif isinstance(event, ev.MuteChanged):
            self.channel(event.channel).muted = event.muted
        elif isinstance(event, ev.PanMoved):
            self.channel(event.channel).pan = event.value
        elif isinstance(event, ev.AttenuationChanged):
            self.channel(event.channel).att_db = event.db
        elif isinstance(event, ev.SoloChanged):
            self.channel(event.channel).soloed = event.soloed
        elif isinstance(event, ev.SurroundMoved):
            channel = self.channel(event.channel)
            if event.axis == "x":
                channel.surround_x = event.value
            else:
                channel.surround_y = event.value
        elif isinstance(event, ev.ChannelNameChar):
            self.channel(event.channel).name_chars[event.index] = ord(event.char)
        elif isinstance(event, ev.AuxSendMoved):
            self.channel(event.channel).aux_sends[event.aux] = event.db
        elif isinstance(event, ev.MasterFaderMoved):
            self.master_db = event.db
        elif isinstance(event, ev.MasterMuteChanged):
            self.master_muted = event.muted
        elif isinstance(event, ev.AuxMasterMoved):
            self.aux_masters[event.aux] = event.db
        elif isinstance(event, ev.AuxOnChanged):
            self.aux_on[event.aux] = event.on
        elif isinstance(event, ev.BusFaderMoved):
            self.bus_faders[event.bus] = event.db
        elif isinstance(event, ev.BusOnChanged):
            self.bus_on[event.bus] = event.on

    def snapshot(self) -> Dict[str, Any]:
        """JSON-ready picture of everything known."""
        return {
            "channels": [
                {
                    "index": c.index,
                    "label": c.label(),
                    "short_name": c.short_name,
                    "long_name": c.long_name,
                    "fader_db": c.fader_db,
                    "muted": c.muted,
                    "pan": c.pan,
                    "soloed": c.soloed,
                    "aux_sends": dict(sorted(c.aux_sends.items())),
                }
                for c in sorted(self.channels.values(), key=lambda c: c.index)
            ],
            "master": {"fader_db": self.master_db, "muted": self.master_muted},
            "aux_masters": dict(sorted(self.aux_masters.items())),
            "aux_on": dict(sorted(self.aux_on.items())),
            "bus_faders": dict(sorted(self.bus_faders.items())),
            "bus_on": dict(sorted(self.bus_on.items())),
        }
