"""Live smoke test: drives the running bridge like a phone would.

Connects to the websocket, reads the console state, sends one fader command
and one mute command, and checks the console's echoes come back as state.
Run with the bridge up:  python3 tools/phone_smoke.py [ws://localhost:8082/ws]
"""
from __future__ import annotations

import json
import sys
import time

from simple_websocket import Client


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8082/ws"
    ws = Client.connect(url)
    print(f"connected to {url}")

    # The first frame is the full state pushed on connect.
    hello = json.loads(ws.receive())
    channels = hello["state"]["channels"]
    print(f"state: {len(channels)} channels, master fader "
          f"{hello['state']['master']['fader_db']} dB")
    if not channels:
        print("FAIL: no channels in state -- console not synced?")
        return 1

    # Pick channel 1's strip and drive it from the phone side.
    ws.send(json.dumps({"action": "fader", "channel": 0, "db": -20.0, "final": True}))
    print("sent fader -20.0 dB to channel 0")
    ws.send(json.dumps({"action": "mute", "channel": 0, "muted": True}))
    print("sent mute to channel 0")

    # Wait for the console's confirmation to come back as a state update.
    deadline = time.time() + 5
    fader_seen = mute_seen = False
    while time.time() < deadline and not (fader_seen and mute_seen):
        try:
            frame = json.loads(ws.receive(timeout=max(0.1, deadline - time.time())))
        except Exception:
            break
        for channel in frame.get("state", {}).get("channels", []):
            if channel["index"] != 0:
                continue
            if channel["fader_db"] is not None and abs(channel["fader_db"] + 20.0) < 1.0:
                fader_seen = True
                print(f"console confirmed fader: {channel['fader_db']} dB")
            if channel.get("muted") is True:
                mute_seen = True
                print("console confirmed mute: True")

    # Leave the desk as we found it.
    ws.send(json.dumps({"action": "mute", "channel": 0, "muted": False}))

    if fader_seen and mute_seen:
        print("PASS: phone -> console -> state round trip works")
        return 0
    print(f"FAIL: fader_seen={fader_seen} mute_seen={mute_seen}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
