"use strict";

// Phone view of the console, live in both directions. The backend pushes a
// snapshot at most every 50 ms; strips are built once and updated in place so
// a rebuild never lands under a finger mid-drag, and updates for the strip
// being dragged are ignored entirely -- the phone is the source of truth until
// the touch ends.
//
// FOH drives channel faders and mutes with the master strip; a musician
// drives their aux's send levels. Sliders work in the console's own throw
// space (0..1023) with the same taper as protocol.py: a linear-dB slider
// spends most of its travel on the -60..-90 dB region nobody uses.

const statusEl = document.getElementById("status");
const channelsEl = document.getElementById("channels");
const masterEl = document.getElementById("master");
const masterFaderEl = document.querySelector("[data-master-fader]");
const masterDbEl = document.querySelector("[data-master-db]");
const masterMuteEl = document.querySelector("[data-master-mute]");
const auxSelect = document.getElementById("aux-select");
const viewButtons = document.querySelectorAll("#view-switch [data-view]");

const THROW_MAX = 1023;        // the console's fader resolution (HIGH)
const SEND_INTERVAL_MS = 50;   // ~20 updates/s per fader, like the backend's own throttle
const FINAL_TIMEOUT_MS = 200;  // a drag that stops moving ends after this

// (raw, dB) breakpoints, interpolated linearly in dB -- identical to
// protocol.FADER_LAW so the slider's feel matches the physical fader.
const FADER_LAW = [
  [0, -90.0], [55, -70.0], [166, -50.0], [331, -30.0],
  [552, -10.0], [823, 0.0], [1023, 10.0],
];

// Stereo master tops out at unity instead of +10 dB; so do aux sends.
const MASTER_LAW = FADER_LAW.map(([raw, db]) => [raw, db - 10.0]);
const SEND_LAW = MASTER_LAW;

function lawDb(law, raw) {
  raw = Math.max(law[0][0], Math.min(law[law.length - 1][0], raw));
  for (let i = 1; i < law.length; i++) {
    const [r0, d0] = law[i - 1], [r1, d1] = law[i];
    if (raw <= r1) return d0 + (d1 - d0) * (raw - r0) / (r1 - r0);
  }
  return law[law.length - 1][1];
}

function lawRaw(law, db) {
  db = Math.max(law[0][1], Math.min(law[law.length - 1][1], db));
  for (let i = 1; i < law.length; i++) {
    const [r0, d0] = law[i - 1], [r1, d1] = law[i];
    if (db <= d1) return r0 + (r1 - r0) * (db - d0) / (d1 - d0);
  }
  return law[law.length - 1][0];
}

function formatDb(db) {
  if (db === null || db === undefined) return "–";
  if (db <= -90) return "-∞";
  return `${db >= 0 ? "+" : ""}${db.toFixed(1)} dB`;
}

let socket = null;
let retryDelay = 500;
let strips = new Map();     // channel index -> {fader, db, mute}
let dragging = new Set();   // drag keys whose fader is under a finger
let lastSentAt = new Map();
let finalTimers = new Map();

// "foh" or "musician"; a musician picks their aux and drives its sends.
let view = "foh";
let aux = 1;
let lastState = null;   // the newest snapshot; a view switch re-renders from it

// --- websocket ----------------------------------------------------------- //

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.addEventListener("open", () => {
    setStatus("connected", true);
    retryDelay = 500;
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      lastState = message.state;   // so a view switch can re-render instantly
      render(message.state);
    }
  });

  socket.addEventListener("close", () => {
    setStatus("reconnecting…", false);
    // Back off so a phone that loses Wi-Fi mid-set does not hammer the bridge.
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 5000);
  });
}

function send(command) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(command));
}

// --- fader commands ------------------------------------------------------ //

// key identifies what is being dragged: "ch/5", "aux/1/5" or "master".
function sendFader(key, raw, final) {
  const now = Date.now();
  if (!final && now - (lastSentAt.get(key) || 0) < SEND_INTERVAL_MS) return;
  lastSentAt.set(key, now);
  const parts = key.split("/");
  if (key === "master" && view === "musician") {
    send({action: "aux_master_fader", aux: aux, raw: Math.round(raw), final: !!final});
  } else if (key === "master") {
    send({action: "master_fader", raw: Math.round(raw), final: !!final});
  } else if (parts[0] === "aux") {
    send({action: "aux_send", aux: Number(parts[1]), channel: Number(parts[2]),
          raw: Math.round(raw), final: !!final});
  } else {
    send({action: "fader", channel: Number(parts[1]), raw: Math.round(raw), final: !!final});
  }
}

// A touch that stops moving is still a drag until the finger lifts; the
// timeout guarantees the settled value still gets its final send.
function scheduleFinal(key, raw) {
  clearTimeout(finalTimers.get(key));
  finalTimers.set(key, setTimeout(() => {
    dragging.delete(key);
    sendFader(key, raw, true);
  }, FINAL_TIMEOUT_MS));
}

// --- rendering ------------------------------------------------------------ //

function stripKey(index) {
  return view === "musician" ? `aux/${aux}/${index}` : `ch/${index}`;
}

function render(state) {
  renderMaster(state);
  const seen = new Set();
  for (const channel of state.channels) {
    seen.add(channel.index);
    renderStrip(channel);
  }
  for (const [index, strip] of strips) {
    if (!seen.has(index)) { strip.root.remove(); strips.delete(index); }
  }
}

function renderMaster(state) {
  const strip = document.getElementById("master");
  strip.hidden = false;
  if (view === "musician") {
    // A musician sees their aux's own fader, not the stereo master.
    masterLabelEl.innerHTML = `<span class="number">AUX</span>${aux}`;
    const db = state.aux_masters[String(aux)] ?? null;
    if (!dragging.has("master")) {
      masterHandle.setRaw(db === null ? 0 : Math.round(lawRaw(SEND_LAW, db)), false);
    }
    masterDbEl.textContent = formatDb(db);
    const on = state.aux_on[String(aux)] ?? null;
    masterMuteEl.textContent = on === null ? "" : (on ? "ON" : "MUTE");
    masterMuteEl.classList.toggle("on", on === false);
    return;
  }
  masterLabelEl.innerHTML = `<span class="number">ST</span>Master`;
  const db = state.master.fader_db;
  if (!dragging.has("master")) {
    masterHandle.setRaw(db === null ? 0 : Math.round(lawRaw(MASTER_LAW, db)), false);
  }
  masterDbEl.textContent = formatDb(db);
  masterMuteEl.textContent = state.master.muted ? "MUTE" : "ON";
  masterMuteEl.classList.toggle("on", Boolean(state.master.muted));
}

function renderStrip(channel) {
  const key = stripKey(channel.index);
  let strip = strips.get(channel.index);
  if (!strip || strip.key !== key) {
    if (strip) strip.root.remove();
    strip = buildStrip(channel.index, channel.label, key);
    strips.set(channel.index, strip);
    insertStripInOrder(strip.root, channel.index);
  }
  if (view === "musician") {
    const db = channel.aux_sends[String(aux)] ?? null;
    if (!dragging.has(key)) {
      strip.handle.setRaw(db === null ? 0 : Math.round(lawRaw(SEND_LAW, db)), false);
      strip.db.textContent = formatDb(db);
    }
  } else if (!dragging.has(key)) {
    strip.handle.setRaw(channel.fader_db === null ? 0
      : Math.round(lawRaw(FADER_LAW, channel.fader_db)), false);
    strip.db.textContent = formatDb(channel.fader_db);
  }
  if (view === "musician") return;   // sends have no mute of their own to show
  strip.mute.textContent = channel.muted ? "MUTE" : "ON";
  strip.mute.classList.toggle("on", Boolean(channel.muted));
}

// Strips arrive in whatever order the console talks about channels; keep the
// desk's own numbering on screen.
function insertStripInOrder(root, index) {
  for (const other of channelsEl.children) {
    if (Number(other.dataset.index) > index) {
      channelsEl.insertBefore(root, other);
      return;
    }
  }
  channelsEl.append(root);
}

// A custom fader: a cap that moves along a slot. Pointer events, because the
// horizontal/vertical split is ours to decide -- a mostly-horizontal gesture
// scrolls the mixer (never a fader move), a mostly-vertical one drags the cap.
const CAP_INSET = 12;              // px between the slot ends and the cap centre

function wireFader(faderEl, key, law, onInput) {
  // `law` may be a constant or a getter, because the master strip's law
  // depends on the view (stereo master vs aux master).
  const lawOf = (typeof law === "function" && law.length === 0) ? law : () => law;

  const cap = document.createElement("div");
  cap.className = "cap";
  const unity = document.createElement("div");
  unity.className = "unity";
  faderEl.append(cap, unity);
  faderEl.classList.add("fader");

  let raw = 0;
  let dragState = null;   // {id, x0, y0, raw0, claimed}

  function trackRect() {
    const height = faderEl.clientHeight - 2 * CAP_INSET;
    return {top: CAP_INSET, height};
  }

  function positionCap() {
    const {top, height} = trackRect();
    // All positioning is done with the cap CENTRE: what the finger tracks,
    // what the notch marks, and what a tap means. The cap element is placed
    // from its top edge, half a cap above the centre -- mixing the two up is
    // how a cap sitting on the 0 dB notch reads +2 dB on the desk.
    const centre = top + height * (1 - raw / THROW_MAX);
    cap.style.top = `${centre - cap.offsetHeight / 2}px`;
    unity.style.top = `${top + height * (1 - lawRaw(lawOf(), 0) / THROW_MAX)}px`;
  }

  function setRaw(value, fromUser) {
    raw = Math.max(0, Math.min(THROW_MAX, Math.round(value)));
    positionCap();
    if (fromUser) {
      onInput(raw);
      scheduleFinal(key, raw);
      sendFader(key, raw, false);
    }
  }

  faderEl.addEventListener("pointerdown", (event) => {
    if (dragState) return;
    dragState = {id: event.pointerId, x0: event.clientX, y0: event.clientY,
                 raw0: raw, claimed: false};
    faderEl.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  faderEl.addEventListener("pointermove", (event) => {
    if (!dragState || event.pointerId !== dragState.id) return;
    if (!dragState.claimed) {
      const dx = Math.abs(event.clientX - dragState.x0);
      const dy = Math.abs(event.clientY - dragState.y0);
      if (dx < 4 && dy < 4) return;                 // still deciding
      // A mostly-horizontal gesture is a scroll, not a fader move: release
      // the pointer so the scroller takes over.
      if (dx > dy) {
        faderEl.releasePointerCapture(event.pointerId);
        dragState = null;
        return;
      }
      dragState.claimed = true;
      dragging.add(key);
      faderEl.classList.add("dragging");
      clearTimeout(finalTimers.get(key));
    }
    const dy = event.clientY - dragState.y0;
    const {height} = trackRect();
    setRaw(dragState.raw0 - (dy / height) * THROW_MAX, true);
    event.preventDefault();
  });

  const release = (event) => {
    if (!dragState || event.pointerId !== dragState.id) return;
    const wasClaimed = dragState.claimed;
    dragState = null;
    faderEl.classList.remove("dragging");
    if (wasClaimed) {
      clearTimeout(finalTimers.get(key));
      finalTimers.delete(key);
      dragging.delete(key);
      sendFader(key, raw, true);
      suppressClickUntil = Date.now() + 400;
    }
  };
  faderEl.addEventListener("pointerup", release);
  faderEl.addEventListener("pointercancel", release);
  faderEl.addEventListener("lostpointercapture", release);

  // Tap anywhere on the track jumps the cap centre there -- unless this click
  // is the tail of a drag that just ended.
  let suppressClickUntil = 0;
  faderEl.addEventListener("click", (event) => {
    if (Date.now() < suppressClickUntil) return;
    const rect = faderEl.getBoundingClientRect();
    const centreFromTop = event.clientY - rect.top;
    const {top, height} = trackRect();
    const fromBottom = faderEl.clientHeight - CAP_INSET - centreFromTop;
    setRaw((fromBottom / height) * THROW_MAX, true);
    scheduleFinal(key, raw);
    sendFader(key, raw, true);
  });

  // Keep the cap positioned when the layout changes size.
  new ResizeObserver(positionCap).observe(faderEl);
  positionCap();

  return {setRaw, refresh: positionCap};
}

function buildStrip(index, label, key) {
  const isSend = key.startsWith("aux/");
  const law = isSend ? SEND_LAW : FADER_LAW;

  const root = document.createElement("section");
  root.className = "strip";
  root.dataset.index = index;

  const nameEl = document.createElement("span");
  nameEl.className = "label";
  nameEl.innerHTML = `<span class="number">${index + 1}</span>${label}`;

  const fader = document.createElement("div");

  const db = document.createElement("span");
  db.className = "value";

  const handle = wireFader(fader, key, law, raw => {
    db.textContent = formatDb(lawDb(law, raw));
  });

  if (isSend) {
    root.append(nameEl, fader, db);
    return {root, key, handle, db};
  }

  const mute = document.createElement("button");
  mute.className = "mute";
  mute.type = "button";

  mute.addEventListener("click", () => {
    const strip = strips.get(index);
    const muted = !strip.mute.classList.contains("on");
    send({action: "mute", channel: index, muted: muted});
    // Optimistic: the next broadcast confirms or corrects it.
    strip.mute.textContent = muted ? "MUTE" : "ON";
    strip.mute.classList.toggle("on", muted);
  });

  root.append(nameEl, fader, db, mute);
  return {root, key, handle, db, mute};
}

// The master strip lives in the HTML; in musician view it is the selected
// aux's master fader, in FOH view the stereo master.
const masterLabelEl = masterEl.querySelector(".label");
const masterHandle = wireFader(masterFaderEl, "master",
                              () => (view === "musician" ? SEND_LAW : MASTER_LAW),
                              raw => {
  const law = view === "musician" ? SEND_LAW : MASTER_LAW;
  masterDbEl.textContent = formatDb(lawDb(law, raw));
});

masterMuteEl.addEventListener("click", () => {
  if (view === "musician") {
    // The desk reports aux ON (unmuted); the button shows its negation.
    const on = !masterMuteEl.classList.contains("on");   // clicking MUTE turns it on
    send({action: "aux_on", aux: aux, on: on});
    masterMuteEl.textContent = on ? "ON" : "MUTE";
    masterMuteEl.classList.toggle("on", !on);
    return;
  }
  const muted = !masterMuteEl.classList.contains("on");
  send({action: "master_mute", muted: muted});
  masterMuteEl.textContent = muted ? "MUTE" : "ON";
  masterMuteEl.classList.toggle("on", muted);
});

// --- view switch ---------------------------------------------------------- //

// Switching FOH/musician rebuilds the strips (a send fader and a channel
// fader are different controls), so any drag in flight ends first. The new
// strips render from the cached snapshot right away -- the next broadcast may
// be half a second out, and an idle desk sends nothing at all.
function setView(next) {
  if (next === view) return;
  view = next;
  for (const button of viewButtons) {
    button.classList.toggle("current", button.dataset.view === view);
  }
  auxSelect.hidden = view !== "musician";
  for (const strip of strips.values()) strip.root.remove();
  strips.clear();
  dragging.clear();
  lastSentAt.delete("master");   // a different fader owns the key now
  masterHandle.refresh();
  if (lastState) render(lastState);
}

for (const button of viewButtons) {
  button.addEventListener("click", () => setView(button.dataset.view));
}

auxSelect.addEventListener("change", () => {
  aux = Number(auxSelect.value);
  // New aux, new strips: the faders become sends to a different bus, and
  // the aux master becomes a different fader.
  for (const strip of strips.values()) strip.root.remove();
  strips.clear();
  dragging.clear();
  lastSentAt.delete("master");
  masterHandle.refresh();
  if (lastState) render(lastState);
});

function setStatus(text, online) {
  statusEl.textContent = text;
  statusEl.className = online ? "online" : "offline";
}

connect();