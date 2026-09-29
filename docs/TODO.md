# TODO

Working list, most important first. The protocol reference is
[docs/01v96i.md](01v96i.md), the capability inventory is
[docs/features.md](features.md), the REAPER setup is [docs/reaper.md](reaper.md)
and the phone work is tracked in [docs/phone-control-plan.md](phone-control-plan.md).

## Phone control

- [ ] **FOH PIN** — gate the FOH view behind a shared PIN, entered once per phone.
- [ ] **Setup page** — browser page for the PIN, aux labels, curated channel lists
      per aux, persisted to a config file. Fixes two gaps: the musician view shows all
      36 channels' sends instead of a curated list, and ST-IN 1–4 have no console-provided
      names. Design the config file to also serve general bridge configuration — today
      nothing persists across runs (README "Not implemented").
- [ ] **Aux/bus meter pages** — meter pages 1, 2 and 5 stream 8 levels each but read zero
      with no signal routed. One session with auxes active identifies them; then the
      musician view's aux master gets a VU. See [docs/01v96i.md](01v96i.md) §3.10.
- [ ] **EQ view on the phone** — UI only; EQ is fully decoded.

## Backends

- [ ] **Holophonix return path** — the console does not follow moves made in Holophonix.
      `backends/reaper_inbound.py` is the template (OSC → SysEx with echo suppression).
- [ ] **Holophonix address scheme** — aux sends, aux masters, bus faders, bus/aux ON,
      solo, EQ on/off, the EQ filter enable and ATT all decode but have no Holophonix
      addresses. Also the §5.2 decision: which Holophonix filter slot a band 1 HPF
      maps to. A decision, not code.
- [ ] **ADM-OSC backend** — open-standard addresses (`/adm/obj/{n}/x`, `/y` from
      surround, `/azim` + `/dist` polar, linear gain) as an alternative to Holophonix's
      proprietary ones. Reuses decoded events; address-scheme work only.
- [ ] **Track banking in REAPER** — whether `/track/20` addresses project track 20 or the
      20th of an 8-track window is untested. Matters once more than 8 channels are used.

## Console protocol (capture sessions)

- [ ] **Compressor and gate** — the unmapped channel dynamics. Protocol discovery,
      not UI work.
- [ ] **Remaining coverage** — delay, phase, insert, routing, aux send ON and pre/post,
      scene recall (Program Change, a different message class), and the hypothesised
      bus EQ.

## Gig readiness

- [ ] **Laptop-as-access-point** — unverified on the gig machine; needs a Wi-Fi chipset
      advertising AP mode (`iw list | grep -A 10 "Supported interface modes"`, look for
      `* AP`). Also decides how phones find the bridge: QR code or printed URL versus
      mDNS.

## Debt

- [ ] `tools/phone_smoke.py` treats a websocket receive timeout as a closed connection
      (`receive()` returns `None` on timeout in this simple-websocket version). Fix
      before using it again.
- [ ] Delete merged branches: `dev/smartphone-remote`, `dev/misc_fixes`.

## Gotchas

- **Fader Resolution must be HIGH** on the console. LOW switches faders to 256 steps and
  silently invalidates `FADER_LAW` and every dB reading. No error, just wrong numbers.
- **The console does not echo** parameter changes it receives — silence after sending is
  normal; watch the console. The phone backend therefore folds its own writes into the
  state itself.
- **The console does not answer parameter requests for aux masters** (`0x39`) or aux ON
  (`0x36`) — the state arrives empty until the fader is moved on the desk or from a phone.
- **Port probing can land on the Tx/Rx ports** (a subset) when the Studio Manager port is
  busy — naming `MIDI 1` explicitly (`--midi-in`/`--midi-out`) is the reliable choice.
- **`tests/test_golden_dispatch.py`** replays 346 real captured messages; regenerate with
  `--update` only when a behaviour change is intended, and read the diff.