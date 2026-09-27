# Feature inventory

What the console offers, what the bridge handles today, and what each intended use
needs. Sources: the Yamaha manuals in [docs/manuals/](manuals/), and on-device captures recorded in
[docs/01v96i.md](01v96i.md).

Status key: **done** decoded and encoded · **decoded** read but not sent anywhere ·
**none** not implemented.

## Per-channel parameters

Input channels 1–32, from the Reference Manual's channel signal flow:

| Parameter | Status | Notes |
| --- | --- | --- |
| Fader (LEVEL) | done | Position index 0–1023, measured dB law |
| ON / mute | done | Emitted in two forms; polarity confirmed |
| PAN | done | Console's own −63…+63 |
| ATT (attenuator) | decoded | Element `0x1D`, tenths of a dB, −96…+12 |
| 4-band EQ | done | Gain, freq, Q, filter type, per-band enable, whole-EQ bypass |
| Surround X / Y | done | Only present in surround mode |
| Solo | decoded | Setup address space |
| Aux send level | decoded | Element `0x23`, aux number in the parameter no. |
| **Phase** | none | Never captured |
| **GATE** | none | Dynamics; gate or ducking |
| **COMP** | none | Dynamics; compressor, expander or limiter |
| **INPUT DELAY** | none | Per-channel delay |
| **Insert** | none | |
| **Routing** (bus 1–8, stereo) | none | Which buses a channel feeds |
| **Aux send ON / pre-post** | none | We have the send *level* only |

ST IN channels 1–4 are a reduced set — phase, ATT, 4-band EQ, ON, LEVEL, PAN, aux
sends, meter — and carry no gate, comp or delay. All of what we support works on them,
with one caveat: **ST-IN pan is per-side**, L and R reading −63/+63, so neither slot is
"the channel's pan" (see [docs/01v96i.md](01v96i.md) § open questions).

## Outputs

| Target | Status | Notes |
| --- | --- | --- |
| Stereo (master) fader, ON, EQ | done | L/R slots linked; slot 0 acted on |
| Aux masters 1–8 fader, ON | decoded | |
| Aux EQ | decoded | Element `0x3C`, same layout as channel EQ |
| Bus 1–8 fader, ON | decoded | |
| Bus EQ | none | Hypothesised on the channel/aux/master pattern, never seen |
| Output attenuation, delay, insert | none | |

## Global

| Feature | Status | Notes |
| --- | --- | --- |
| Layer / selection indicators | decoded | Recognised, semantics unknown |
| EQ band selection | decoded | Which band the UI shows |
| Solo status | decoded | Global flags accompanying solo |
| **Scene recall / store** | none | Program Change, not SysEx — a different message class |
| **Fader / mute groups** | none | |
| **Effects processors 1–4** | none | |
| **Metering** | working | Remote-meter class decoded: channel inputs + stereo master, streamed on request ([docs/01v96i.md](01v96i.md) §3.10); aux/bus pages unidentified |

## What each use needs

### Holophonix spatial bridge — the current goal

Needs fader, mute, pan, surround X/Y and EQ. **All present.** What remains is not
protocol work but decisions: the OSC address scheme for the *decoded* rows above, the
filter-slot mapping in [docs/01v96i.md](01v96i.md) §5.2, and what a stereo input's pan
should mean. Plus one build task — the bridge can only *send* OSC, so Holophonix cannot
drive the console (see § Bidirectional below).

### REAPER — working, over OSC on the normal mixing layer

The console drives REAPER, and REAPER drives the console, while the console stays a
mixer. The REMOTE layer is **not** used: it is a mode that takes the console over, and it
speaks HUI, which is the legacy Pro Tools protocol rather than MCU. On this machine
REAPER also crashes when a HUI surface is added — `SIGABRT` inside ALSA's
`snd_rawmidi_open`, called from `reaper_csurf.so` — so that route is closed regardless.

Run `python3 main.py` with no arguments: it reads REAPER's own `reaper.ini` for the OSC
surface, finds the port REAPER is listening on, probes for the console, and syncs state.

| Control | Console → REAPER | REAPER → Console |
| --- | --- | --- |
| Channel fader | `/track/N/volume/db`, real dB | yes |
| Channel mute | `/track/N/mute` | yes |
| Solo | `/track/N/solo` | yes |
| Pan | `/track/N/pan`, normalized with centre 0.5 | yes |
| Master fader | `/master/volume` via the measured taper | yes |
| Master mute | `/action/18/cc` | **no — REAPER does not expose it** |
| EQ, aux, bus, ATT, surround | — | — |

Notes that cost time to learn:

- **REAPER's OSC modes matter.** "Local port (receive only)" makes REAPER *never* send, so
  feedback is impossible. Device IP/Port mode sends, but has no configurable local port —
  REAPER binds an ephemeral one that changes each launch, which is why the bridge reads it
  from the socket table.
- **Master fader is not a dB scale.** `MASTER_VOLUME` accepts only a normalized value, and
  REAPER's normalized scale is its own fader taper: 0 dB sits at ≈0.716 and 1.0 is +12 dB.
  `REAPER_FADER_LAW` in `backends/reaper.py` is measured from REAPER itself.
- **Master mute is one-way.** `Default.ReaperOSC` has no `MASTER_MUTE` pattern; muting
  REAPER's master emits only `/track/mute` for the selected track, which would mute the
  wrong console strip. Console → REAPER works through action 18, the *set* variant.
- **Track banking is unresolved.** `DEVICE_TRACK_COUNT` is 8, and whether `/track/20`
  means project track 20 or the 20th of an 8-track window is untested — the test project
  had only two tracks. It only matters above 8 channels.
- **ReaEQ is reachable** if wanted: it is addressed by slot (`hipass`, `loshelf`,
  `band/@`, `hishelf`, `lopass`), mirroring the console's filter-type-picks-the-slot
  behaviour, and `DEVICE_EQ INSERT` inserts it automatically. Not implemented.

### General control surface

If the scope grows beyond spatial control, the gaps are the **none** rows above:
dynamics (gate, comp), delay, phase, routing, aux send ON and pre/post, and scene recall.
All are likely reachable the same way everything else was — move the control, read the
element and parameter number off the monitor, add a row to `MESSAGES`.

## Bidirectional

The console direction is complete: every parameter the bridge decodes it can also send,
and `--sync` reads the console's whole state on startup.

The OSC direction is not. `osc/osc_sender.py` can only send; nothing listens. So a level
change in Holophonix cannot move the console's motorised fader, even though the mechanism
to move it exists. Closing that needs an OSC server, a reverse mapping from Holophonix
addresses to `encoder` calls, and echo suppression so a console move does not bounce back
and fight the operator.
