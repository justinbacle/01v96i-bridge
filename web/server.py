"""Web server for phone control: serves the UI and pushes console state.

Flask with flask-sock, both threaded WSGI, matching the rest of the bridge --
a blocking MIDI listener and background threads. An asyncio server would mean
bridging two concurrency models for no user-visible gain.

The server owns no console knowledge: it is handed a ConsoleState to read and a
callback to invoke when a phone changes something.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable, Optional, Set

from flask import Flask, jsonify, send_from_directory
from flask_sock import Sock

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebUI:
    """Serves the UI and keeps connected phones in step with the console."""

    def __init__(self, state, on_command: Optional[Callable[[dict], None]] = None,
                 host: str = "0.0.0.0", port: int = 8080) -> None:
        self.state = state
        self.on_command = on_command
        self.host = host
        self.port = port

        self.app = Flask(__name__, static_folder=None)
        self.app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
        self.sock = Sock(self.app)
        self._clients: Set[object] = set()
        self._lock = threading.Lock()
        self._register_routes()

    # --- routes ------------------------------------------------------------- #

    def _register_routes(self) -> None:
        @self.app.route("/")
        def index():
            return send_from_directory(STATIC_DIR, "index.html")

        @self.app.route("/<path:filename>")
        def static_file(filename):
            return send_from_directory(STATIC_DIR, filename)

        @self.app.route("/api/state")
        def api_state():
            return jsonify(self.state.snapshot())

        @self.sock.route("/ws")
        def websocket(ws):
            with self._lock:
                self._clients.add(ws)
            try:
                ws.send(json.dumps({"type": "state", "state": self.state.snapshot()}))
                while True:
                    message = ws.receive()
                    if message is None:
                        break
                    self._handle_command(message)
            finally:
                with self._lock:
                    self._clients.discard(ws)

    def _handle_command(self, message: str) -> None:
        try:
            command = json.loads(message)
        except ValueError:
            logging.debug("ignoring unparseable websocket message")
            return
        if self.on_command is not None:
            self.on_command(command)

    # --- pushing state ------------------------------------------------------ #

    def broadcast_state(self) -> None:
        """Send the current snapshot to every connected phone."""
        if not self._clients:
            return
        payload = json.dumps({"type": "state", "state": self.state.snapshot()})
        with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                ws.send(payload)
            except Exception:  # a phone that walked out of range
                with self._lock:
                    self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # --- lifecycle ---------------------------------------------------------- #

    def start(self) -> threading.Thread:
        """Serve in a background thread so the MIDI loop keeps the main one."""
        thread = threading.Thread(target=self._serve, daemon=True)
        thread.start()
        logging.info(f"Phone UI on http://{self.host}:{self.port}")
        return thread

    def _serve(self) -> None:
        # threaded=True so several phones are served at once; the reloader would
        # fork a second process and open the MIDI ports twice.
        self.app.run(host=self.host, port=self.port, threaded=True,
                     use_reloader=False, debug=False)
