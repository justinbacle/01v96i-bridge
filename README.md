# 01v96i-bridge

Turns a **Yamaha 01V96i digital mixer** into a control surface for whatever you point it
at. The console's faders, mutes, pan, surround position, solo and EQ are decoded from its
MIDI SysEx and translated to a *backend*; today that means **REAPER**, **Holophonix**
or a **phone/tablet web UI** served by the bridge itself, and the console can be driven
back the other way.

It runs on the console's **normal mixing layer**, so the desk stays a mixer while it
controls something else — no mode switch, no REMOTE layer.

```bash
./bridge
```

No arguments. It probes for the console, works out what to talk to, and reads the
console's whole state so both sides start in step.

## Backends

| Backend | Status | Notes |
| --- | --- | --- |
| **REAPER** (OSC) | working, both directions | Faders, mutes, solo, pan, master level. See [docs/reaper.md](docs/reaper.md) |
| **Holophonix** (OSC) | outbound; spatial controls mapped | Gain, mute, azimuth/distance from surround X/Y, EQ |
| **Phone** (web) | working, both directions | FOH: channel faders/mutes + master. Musician: aux send mixes + aux master. See [docs/phone-control-plan.md](docs/phone-control-plan.md) |
| ADM-OSC | not implemented | Open standard for object positions |
| MCU / HUI | not implemented | The console speaks HUI natively on its DAW ports; see [docs/features.md](docs/features.md) |

Selected automatically — REAPER if it has an OSC surface configured, otherwise
Holophonix — or forced with `--backend`.

### Phone control

```bash
./bridge --backend phone [--web-port 8080]
```

Serves a web UI (plain HTML/CSS/JS, no build step, Flask + flask-sock) on the LAN.
Open the bridge's address on any phone browser: an **FOH** view drives channel faders,
mutes and the stereo master; the **Musician** view picks an aux 1–8 and drives its
per-channel send levels plus that aux's master fader. Faders mirror the console's own
taper and position, updates flow live in both directions, and the page reconnects with
backoff when Wi-Fi drops. A FOH PIN and per-aux channel curation are planned — see
[docs/phone-control-plan.md](docs/phone-control-plan.md).

## How it works

1. `yamaha01v96i/` decodes the console's SysEx into semantic events. It is pure Python
   over `list[int]`: no MIDI, no OSC, no I/O, and no knowledge of any backend.
2. A backend in `backends/` turns those events into its own address scheme.
3. `yamaha01v96i/encoder.py` is the mirror image, so anything the bridge can read it can
   also send — which is what moves the console's motorised faders.

The protocol itself is reverse-engineered and documented in
[docs/01v96i.md](docs/01v96i.md), checked against Yamaha's own manuals in
[docs/manuals/](docs/manuals/). Every message the console emits in normal use is decoded.

## Setup

Requires Python 3.13+ and a MIDI input the mixer is connected to.

```bash
# One-time on Ubuntu/Debian: venv support, the Python headers and ALSA headers.
# python-rtmidi builds from source until wheels exist for your Python version.
sudo apt install python3-venv python3-dev libasound2-dev

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./bridge
```

`./bridge` needs no arguments: it probes for the console and, if REAPER has an OSC
surface configured, reads its settings from REAPER's own config.

### Platforms

The protocol layer (`yamaha01v96i/`) is pure Python and runs anywhere; MIDI and OSC go
through `mido`/`python-rtmidi`/`python-osc`, which are cross-platform. Platform notes:

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Launcher | `./bridge` | `./bridge` | `bridge.cmd` |
| REAPER config discovery | yes | yes | yes |
| REAPER port lookup before it speaks | `ss` | `lsof` | falls back to learning it from REAPER's first message |
| `tools/monitor.py` | yes | yes | needs `pip install windows-curses` |

The apt packages in the setup block above are Debian/Ubuntu only; on macOS and Windows
`python-rtmidi` ships prebuilt wheels and needs no compiler.

On startup you will be prompted to select a MIDI input port. Type `q` + Enter to quit.

The console exposes eight USB-MIDI ports; **MIDI 1** is the one to pick. It carries
everything, while the console's configured Tx Port carries only a subset and moves if that
setting changes.

### Console settings

On the console itself (full detail and rationale in
[docs/01v96i.md](docs/01v96i.md) § Console configuration):

- `MIDI` → `[F1]`: **PARAMETER CHANGE Tx = ON** (to read the console), **Rx = ON** (to
  drive it), **ECHO = off**, and **CHANNEL Tx/Rx = 1**.
- `MIDI` → `[F1]`: **Fader Resolution = HIGH**. On LOW the faders drop to 256 steps and
  every dB value the bridge reports will be wrong.
- `DIO/SETUP` → `MIDI/Host`: note which USB port is assigned to **Studio Manager** — that
  is the port to give the bridge. It carries the full stream in both directions, and is
  *not* the Rx/Tx PORT setting.

```bash
python3 main.py [--ip <address>] [--port <port>]
```

| Argument | Default | Description |
| --- | --- | --- |
| `--ip` | `192.168.1.104` | OSC destination IP |
| `--port` | `4003` | OSC destination port |

## Holophonix OSC address mapping

| Mixer control | OSC address | Value range |
| --- | --- | --- |
| Channel fader | `/track/{n}/gain` | −∞ to +10 dB |
| Channel mute | `/track/{n}/mute` | 0 / 1 |
| Channel pan | `/track/{n}/azim` | −45 to +45° |
| Surround X/Y | `/track/{n}/azim` + `/track/{n}/dist` | polar coords |
| Master fader | `/master/gain` | −∞ to 0 dB |
| Master mute | `/master/mute` | 0 / 1 |
| EQ gain | `/track/{n}/equalizer/filter/{b}/gain` | −18 to +18 dB |
| EQ frequency | `/track/{n}/equalizer/filter/{b}/freq` | 21.2 Hz – 20 kHz |
| EQ Q | `/track/{n}/equalizer/filter/{b}/q` | — |

`n` = track number (1-based), `b` = EQ band index.

---

## Status

**The console side is complete.** Channels 1–32, ST-IN 1–4, aux sends and masters, buses,
all four EQ bands on channel/aux/master, solo, ATT, EQ on/off and the console's own status
messages are all decoded — zero unrecognised messages across ~12,600 captured. Everything
decoded can also be sent back, so the console's motorised faders and lamps follow, and
`--sync` reads the console's whole state at startup (~1733 parameters in well under a
second). See [docs/features.md](docs/features.md) for what the console offers against
what is handled.

**REAPER is working in both directions** — faders, mutes, solo, pan and master level, with
master mute outbound only because REAPER does not expose it. See
[docs/reaper.md](docs/reaper.md).

**Phone control is working in both directions** — FOH (channel faders, mutes, stereo
master) and per-musician aux mixes (send levels and the aux's own master), served as a
web UI from the bridge. PIN protection and per-aux channel curation are still to build;
see [docs/phone-control-plan.md](docs/phone-control-plan.md).

**Holophonix is outbound only**, and its spatial controls are mapped: gain, mute, azimuth
from pan, azimuth + distance from surround X/Y, and EQ.

### Decoded but unmapped

Fully decoded and logged, but with no Holophonix address chosen yet — a mapping decision
rather than a protocol gap (see [docs/01v96i.md](docs/01v96i.md) §5.2):

aux sends and aux masters, bus faders, bus/aux ON, solo, EQ on/off, the bands 1/4 filter
enable, and ATT.

### Not implemented

- **ADM-OSC** — the [open standard](https://github.com/immersive-audio-live/ADM-OSC) for
  object positions, as an alternative to Holophonix's proprietary addresses: `/adm/obj/{n}/x`
  and `/y` from surround X/Y, or `/azim` and `/dist` in polar, with linear gain
- **Holophonix feedback** — the return path exists for REAPER; nothing is received from
  Holophonix, so the console is not updated from its state
- **Console dynamics and routing** — gate, compressor, delay, phase, insert, routing, aux
  send ON and pre/post, scene recall
- **Configuration file** — everything is discovered or passed as flags; nothing is persisted

## Project structure

```text
bridge                     # Launcher: runs main.py in the project venv
main.py                    # CLI and wiring only
yamaha01v96i/              # The 01V96i protocol API - no MIDI or OSC dependencies
    protocol.py            #   framing, value encoding, fader laws, EQ tables
    events.py              #   semantic events backends consume
    parser.py              #   message table; raw SysEx -> events
    state.py               #   folds events into a live console snapshot
    encoder.py             #   mirror of parser.py: events -> raw SysEx
backends/holophonix.py     # Holophonix OSC addresses (the only place they live)
backends/reaper.py         # REAPER OSC addresses, both directions
backends/phone.py          # Console state -> phones, phone commands -> console
web/server.py              # Flask + flask-sock: page, REST state, websocket push
web/static/                # The phone UI: plain HTML/CSS/JS, no build step
midi/ports.py              # Port listing, selection, keepalive detection
midi/midi_sysex.py         # MIDI SysEx listener used by the run loop
osc/osc_sender.py          # Thin UDP wrapper around python-osc
tools/monitor.py           # Live TUI: decodes the console's SysEx as you move controls
tools/capture.py           # Bulk MIDI capture & annotation logger
tools/osc_dump.py          # Stand-in OSC receiver for testing without Holophonix
tools/phone_smoke.py       # Drives the phone backend's websocket like a phone would
tests/                     # Unit tests + golden OSC snapshot (no MIDI hardware needed)
docs/01v96i.md             # Reverse-engineered 01V96i SysEx reference (authoritative)
docs/features.md           # What the console offers vs what the bridge handles
docs/reaper.md             # Using the console as a REAPER control surface
docs/phone-control-plan.md # Phone backend plan: what is built, what is left
docs/manuals/              # Yamaha reference and owner's manuals (the authority)
requirements.txt
```

## Development

[![tests](https://github.com/justinbacle/01v96i-bridge/actions/workflows/tests.yml/badge.svg)](https://github.com/justinbacle/01v96i-bridge/actions/workflows/tests.yml)

With the venv active:

```bash
python3 -m unittest discover -s tests -v   # no MIDI hardware needed
python3 -m flake8 main.py yamaha01v96i backends web midi osc tools tests
python3 tools/monitor.py                   # live decode of everything the mixer sends
python3 tools/osc_dump.py --port 4003      # print what the bridge sends over OSC
```

`tools/monitor.py` shares `main.py`'s masks, so it cannot drift from the bridge. Unknown
messages are highlighted — that is how the aux, bus and solo support above was found.
