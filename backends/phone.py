"""Phone backend: keeps a live picture of the console and serves it to phones.

Unlike the OSC backends this one has no external target -- it *is* the target.
Console events update a ConsoleState, and connected phones are pushed the new
picture. Commands from phones are turned into parameter changes and sent back to
the console (step 2 of docs/phone-control-plan.md).

No echo suppression here, unlike REAPER: the phone never re-sends on state
updates, so the console confirming our own write cannot loop. The fight that
does exist -- a broadcast moving the fader under a finger mid-drag -- is
settled in the frontend, which ignores updates for the strip being dragged.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import mido

from yamaha01v96i import encoder, events as ev, parse
from yamaha01v96i.state import ConsoleState
from web.server import WebUI

# The console emits a burst of events during startup sync and while a fader
# moves; coalescing avoids sending a websocket frame per message.
BROADCAST_INTERVAL_S = 0.05

# Touch events fire at up to 60 Hz; that many SysEx messages would flood the
# console's MIDI input. The frontend throttles too, but the backend is the one
# that can guarantee it. Intermediate values are dropped, latest wins; a
# command with final=True always goes out (the finger lifted).
FADER_MIN_INTERVAL_S = 0.05


class PhoneBackend:
    """Consumes console events; serves them to phones over a websocket."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.state = ConsoleState()
        self.ui = WebUI(self.state, on_command=self.handle_command,
                        host=host, port=port)
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._started = False
        self._outport: Optional["mido.ports.BaseOutput"] = None
        self._lock = threading.Lock()
        self._last_sent_at: dict = {}

    def attach_outport(self, outport: "mido.ports.BaseOutput") -> None:
        """Let phone commands reach the console; called once the port is open."""
        self._outport = outport

    def start(self) -> None:
        self.ui.start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        self._started = True

    def stop(self) -> None:
        self._stop.set()

    def handle(self, event: ev.MixerEvent) -> None:
        """Called for every console event, from the MIDI thread."""
        if self.state.apply(event):
            self._dirty.set()

    def handle_command(self, command: dict) -> None:
        """Called for every websocket message, from a Flask worker thread."""
        if not isinstance(command, dict):
            return
        action = command.get("action")
        if action == "fader":
            self._set_fader(command)
        elif action == "mute":
            self._set_mute(command)
        elif action == "master_fader":
            self._set_master_fader(command)
        elif action == "master_mute":
            self._set_master_mute(command)
        else:
            logging.debug(f"unhandled phone command: {command}")

    def _set_fader(self, command: dict) -> None:
        channel, raw = command.get("channel"), command.get("raw")
        if not isinstance(channel, int) or not isinstance(raw, int):
            return
        if not self._throttle_ok(f"fader/{channel}", command):
            return
        self._send(encoder.channel_fader(channel, raw))

    def _set_mute(self, command: dict) -> None:
        channel, muted = command.get("channel"), command.get("muted")
        if not isinstance(channel, int) or not isinstance(muted, bool):
            return
        self._send(encoder.channel_on(channel, not muted))

    def _set_master_fader(self, command: dict) -> None:
        raw = command.get("raw")
        if not isinstance(raw, int):
            return
        if not self._throttle_ok("fader/master", command):
            return
        self._send(encoder.master_fader(raw))

    def _set_master_mute(self, command: dict) -> None:
        muted = command.get("muted")
        if not isinstance(muted, bool):
            return
        self._send(encoder.master_on(not muted))

    def _throttle_ok(self, key: str, command: dict) -> bool:
        """Final sends always pass; a drag's intermediate values are dropped."""
        if command.get("final"):
            return True
        with self._lock:
            now = time.monotonic()
            if now - self._last_sent_at.get(key, 0.0) < FADER_MIN_INTERVAL_S:
                return False
            self._last_sent_at[key] = now
        return True

    def _send(self, payload: list) -> None:
        """Deliver one parameter change, and fold it into the local state.

        The console's parameter-change echo is off (it must be, or the bridge
        would loop), so a phone's own write never comes back as an event. The
        sending phone knows what it did; applying the change here is for every
        *other* phone watching. The payload is exactly what the parser eats,
        so it round-trips through the ordinary decode path.
        """
        outport = self._outport
        if outport is None:
            logging.debug("phone command dropped: no MIDI output")
            return
        outport.send(mido.Message("sysex", data=payload))
        event = parse(payload)
        if event is not None and self.state.apply(event):
            self._dirty.set()
        logging.debug(f"phone -> console: {payload}")

    def _broadcast_loop(self) -> None:
        """Push at most one frame per interval, however busy the console is."""
        while not self._stop.is_set():
            if self._dirty.wait(timeout=0.5):
                self._dirty.clear()
                try:
                    self.ui.broadcast_state()
                except Exception:
                    logging.exception("failed to push state to phones")
                time.sleep(BROADCAST_INTERVAL_S)
