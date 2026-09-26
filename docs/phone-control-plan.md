# Phone control — plan

Letting the FOH engineer and musicians control the console from a phone.

**This is a working plan.** When it is built, fold what is still true into
[docs/features.md](features.md) and delete this file — a finished plan left lying around
is the same stale-docs problem as any other.

## Decided

| Question | Decision |
| --- | --- |
| Who | Musicians: their own monitor mix. FOH: channel faders and mutes |
| Delivery | Web UI served by the bridge; nothing to install on the phone |
| Musician scope | A curated channel list per aux, chosen by FOH |
| Musician access | A button to pick which aux is theirs; trust, no enforcement |
| FOH access | A shared PIN, set in the setup page |
| Configuration | A setup page in the browser |
| Coexistence | A `--backend` choice like REAPER — one at a time, not alongside |
| Metering | Possible, deferred |
| Channel names | Read from the console *if* it transmits them — see Step 0 |

## Stack

Plain HTML/CSS/JS with **no build step**, served by **Flask + flask-sock**.

Two dependencies, both threaded WSGI. That matters: the bridge is already threaded — a
blocking MIDI listener, a background sync thread — so an asyncio server would mean
bridging two concurrency models for no user-visible gain. No npm, no bundler, and the
frontend stays readable by anyone who knows JavaScript.

## Step 0 — resolved

**The console does transmit channel names**, as ordinary parameter changes, and they answer
parameter requests — so the bridge can read every name on demand. Documented in
[docs/01v96i.md](01v96i.md) §3.9: Patch-data space, element `0x04`, parameter number is a
character index, data byte is ASCII. Indices 0–3 are the 4-character short name and 4–19
the 16-character long name.

Consequences for the build: names come from the console, not the setup page. Use the long
name where there is room and the short name on a fader strip. Adding it is one row in
`MESSAGES`, a `ChannelNamed` event, and name requests folded into `state_requests()`.

Two caveats found while checking:

- **ST-IN 1–4 have no name** — only the 32 mono channels do. The four stereo inputs need a
  label from the setup page or a sensible default.
- **Reading every name costs 640 requests**, about 600 ms. Fetch once at startup alongside
  the existing state sync, not per view.

## Build order

1. **State model and `--backend phone`.** HTTP server, WebSocket, and a page showing live
   console state read-only. Proves console → parser → state → phone before any control
   exists; the existing startup sync already provides a complete picture to serve.
2. **Musician view.** Aux selector, curated faders, writing to the console through
   `yamaha01v96i/encoder.py`. Reuse the echo suppression written for REAPER, or a phone
   drag and a motorised fader will fight each other.
3. **FOH view** behind the PIN: channel faders and mutes.
4. **Setup page.** PIN, aux labels, curated channel list, persisted to a config file.
5. **Later.** EQ (already decoded — UI only), metering, compressor and gate.

## Constraints

- **Eight auxes** is a hard ceiling on independent monitor mixes.
- **Compressor and gate are not decoded.** Unlike EQ, adding them is console protocol
  discovery, not UI work.
- **Laptop-as-access-point is unverified** on the gig machine: it needs a Wi-Fi chipset
  advertising AP mode (`iw list | grep -A 10 "Supported interface modes"`, look for
  `* AP`), most adapters cannot be an AP and a client at once, and laptop APs are less
  reliable under load than a travel router. This also decides how phones find the bridge —
  a printed URL or QR code versus mDNS.
- **One backend at a time** means monitors and REAPER cannot share a gig. If that turns
  out to matter, it is a change to how `--backend` works, and better known early than at
  a show.
