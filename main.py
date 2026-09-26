"""Yamaha 01V96i -> OSC bridge.

Wiring only: pick a MIDI port, decode with `yamaha01v96i`, hand the events to a
backend. Protocol knowledge lives in `yamaha01v96i/`, address schemes in
`backends/`.
"""
from __future__ import annotations

import argparse
import logging
import threading
import time

from backends.holophonix import HolophonixBackend
from backends.phone import PhoneBackend
from backends.reaper import ReaperBackend, discover_listen_port, discover_osc_surface
import mido

from midi import ports
from midi.midi_sysex import MidiSysexListener
from backends.reaper_inbound import ReaperInbound
from osc.osc_receiver import OSCReceiver
from osc.osc_sender import OSCSender
from yamaha01v96i import encoder, parse


# The OSC backends take a sender; the phone backend is its own target and takes
# none, so it is constructed separately below.
OSC_BACKENDS = {"holophonix": HolophonixBackend, "reaper": ReaperBackend}
BACKENDS = sorted(OSC_BACKENDS) + ["phone"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Yamaha 01V96i MIDI to OSC bridge. Run with no arguments: it finds "
                    "the console, and REAPER's OSC settings if REAPER is configured.")
    parser.add_argument("--ip", help="OSC destination IP (default: discovered)")
    parser.add_argument("--port", type=int, help="OSC destination port (default: discovered)")
    parser.add_argument("--midi-in", help="MIDI input port: the console's Tx PORT "
                                          "(substring match; skips the prompt)")
    parser.add_argument("--midi-out", help="MIDI output port: the console's Rx PORT "
                                           "(substring match; enables sending)")
    parser.add_argument("--backend", choices=BACKENDS,
                        help="OSC address scheme (default: reaper when REAPER has an "
                             "OSC surface configured, else holophonix)")
    parser.add_argument("--web-port", type=int, default=8080,
                        help="port the phone UI is served on (phone backend only)")
    parser.add_argument("--listen-port", type=int,
                        help="UDP port to receive OSC feedback on, so the DAW can drive "
                             "the console (reaper backend only)")
    parser.add_argument("--no-sync", dest="sync", action="store_false",
                        help="do not ask the console for its state on startup")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every OSC send")
    return parser


# Requests are answered immediately, so a whole burst overruns the input buffer
# while nothing is draining it: sending all 805 at once loses about 60% of the
# replies. Chunks of 64 with a short pause let the listener keep up and every
# reply arrives, in roughly a third of a second.
SYNC_CHUNK = 64
SYNC_PAUSE_S = 0.02
SYNC_STARTUP_DELAY_S = 0.3


def request_state(outport) -> None:
    """Ask the console for everything, paced so no replies are dropped.

    Runs after the listener is up: the replies are ordinary parameter changes, so
    they arrive through the normal decode path and populate the backend with no
    special casing.
    """
    time.sleep(SYNC_STARTUP_DELAY_S)  # let the listener come up first
    requests = encoder.state_requests()
    logging.info(f"Requesting console state ({len(requests)} parameters)...")
    for start in range(0, len(requests), SYNC_CHUNK):
        for payload in requests[start:start + SYNC_CHUNK]:
            outport.send(mido.Message("sysex", data=payload))
        time.sleep(SYNC_PAUSE_S)


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s: %(message)s")

    # Discovered so the bridge runs with no arguments; flags override any of it.
    surface = discover_osc_surface()
    backend_name = args.backend or ("reaper" if surface else "holophonix")
    if surface and backend_name == "reaper":
        # In Device IP/Port mode REAPER has no configured local port, so find the
        # ephemeral one it is bound to; otherwise nothing can be sent until REAPER
        # happens to speak first.
        port = args.port or surface.send_to_port or discover_listen_port() or 0
        where = (f"sending to port {port}" if port
                 else "destination learned from REAPER's first message")
        logging.info(f"Found REAPER OSC surface {surface.name!r}: {where}, "
                     f"listening on {surface.listen_on_port}")
        ip = args.ip or "127.0.0.1"
        listen_port = args.listen_port or surface.listen_on_port
        # A device IP of 0.0.0.0 still reaches a local listener on Linux, so it
        # needs no correction -- noted only for diagnosis.
        logging.debug(f"REAPER's OSC device IP is {surface.device_ip!r}")
    else:
        ip = args.ip or "192.168.1.104"
        port = args.port or 4003
        listen_port = args.listen_port

    sender = OSCSender(ip, port)
    inbound: ReaperInbound | None = None
    phone: PhoneBackend | None = None

    class EchoAwareSender:
        """Passes sends through, recording them so REAPER's echo can be ignored."""

        def send(self, address: str, *values) -> None:
            if inbound is not None and values:
                inbound.note_sent(address, values[0])
            sender.send(address, *values)

    if backend_name == "phone":
        phone = PhoneBackend(port=args.web_port)
        backend = phone
    else:
        backend = OSC_BACKENDS[backend_name](EchoAwareSender())

    midi_port = ports.resolve_input(args.midi_in)
    midi_out = ports.resolve_output(args.midi_out)
    if not midi_port or not midi_out:
        # Probing finds the working pair whatever the console's port assignments are.
        detected_in, detected_out = ports.detect_console()
        midi_port = midi_port or detected_in
        midi_out = midi_out or detected_out
    if not midi_port:
        midi_port = ports.select_interactively()
    if not midi_port:
        return 1

    def on_sysex(data) -> None:
        payload = list(data)
        event = parse(payload)
        if event is None:
            logging.warning(f"Unhandled Sysex: {payload}")
            return
        backend.handle(event)

    listener = MidiSysexListener(midi_port)
    listener.add_callback(on_sysex)

    outport = None
    if midi_out:
        outport = mido.open_output(midi_out)  # pyright: ignore[reportAttributeAccessIssue]
        logging.info(f"Sending to {midi_out}")
    elif args.sync:
        logging.warning("No MIDI output found: starting without console state.")

    if phone is not None and outport is not None:
        phone.attach_outport(outport)

    receiver = None
    if listen_port is not None and backend_name != "reaper":
        logging.info("Return path is only implemented for the reaper backend.")
    elif listen_port is not None and outport is None:
        logging.warning("No MIDI output found: the console cannot be driven back.")
    elif listen_port is not None:
        inbound = ReaperInbound(outport)

        def learn_peer(peer_ip: str, peer_port: int) -> None:
            # REAPER's Device IP/Port mode receives on an ephemeral port, so its
            # address is taken from whatever it sends us.
            sender.retarget(peer_ip, peer_port)

        receiver = OSCReceiver("0.0.0.0", listen_port, inbound.handle, learn_peer)
        receiver.start()

    if args.sync and outport is not None:
        threading.Thread(target=request_state, args=(outport,), daemon=True).start()

    def check_exit() -> None:
        while True:
            try:
                if input().strip().lower() == "q":
                    break
            except EOFError:
                # No console attached (service, nohup, redirected stdin): there is
                # no one to type 'q', so stop watching rather than stopping the bridge.
                return
            except KeyboardInterrupt:
                break
        listener.stop()
        logging.info("Exiting Sysex listener...")

    if phone is not None:
        phone.start()

    threading.Thread(target=check_exit, daemon=True).start()
    logging.info(f"Listening for Sysex on {midi_port}... (press 'q' + Enter to exit)")
    listener.listen()
    if receiver is not None:
        receiver.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
