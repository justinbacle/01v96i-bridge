"""Phone backend: keeps a live picture of the console and serves it to phones.

Unlike the OSC backends this one has no external target -- it *is* the target.
Console events update a ConsoleState, and connected phones are pushed the new
picture. Commands from phones are turned into parameter changes and sent back to
the console (step 2 of docs/phone-control-plan.md; not wired yet).
"""
from __future__ import annotations

import logging
import threading
import time

from yamaha01v96i import events as ev
from yamaha01v96i.state import ConsoleState
from web.server import WebUI

# The console emits a burst of events during startup sync and while a fader
# moves; coalescing avoids sending a websocket frame per message.
BROADCAST_INTERVAL_S = 0.05


class PhoneBackend:
    """Consumes console events; serves them to phones over a websocket."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.state = ConsoleState()
        self.ui = WebUI(self.state, on_command=self.handle_command,
                        host=host, port=port)
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._started = False

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
        # Step 2: translate into encoder calls and send to the console.
        logging.debug(f"phone command (not yet implemented): {command}")

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
