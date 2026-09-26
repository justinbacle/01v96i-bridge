// Read-only view of the console. Step 1 of docs/phone-control-plan.md: it proves
// console -> parser -> state -> phone before anything can write to the desk.

const statusEl = document.getElementById("status");
const channelsEl = document.getElementById("channels");
const masterDbEl = document.querySelector("[data-master-db]");
const masterMuteEl = document.querySelector("[data-master-mute]");

let socket = null;
let retryDelay = 500;

function formatDb(db) {
  if (db === null || db === undefined) return "–";
  if (db <= -89) return "-∞";          // the console's bottom stop
  return `${db >= 0 ? "+" : ""}${db.toFixed(1)} dB`;
}

function renderChannel(channel) {
  const row = document.createElement("section");
  row.className = "strip";
  row.innerHTML = `
    <span class="label"><span class="number">${channel.index + 1}</span>${channel.label}</span>
    <span class="value">${formatDb(channel.fader_db)}</span>
    <span class="mute ${channel.muted ? "on" : ""}">${channel.muted ? "MUTE" : "ON"}</span>`;
  return row;
}

function render(state) {
  masterDbEl.textContent = formatDb(state.master.fader_db);
  masterMuteEl.textContent = state.master.muted ? "MUTE" : "ON";
  masterMuteEl.classList.toggle("on", Boolean(state.master.muted));

  channelsEl.replaceChildren();
  if (!state.channels.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Waiting for the console…";
    channelsEl.append(empty);
    return;
  }
  for (const channel of state.channels) {
    channelsEl.append(renderChannel(channel));
  }
}

function setStatus(text, online) {
  statusEl.textContent = text;
  statusEl.className = online ? "online" : "offline";
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.addEventListener("open", () => {
    setStatus("connected", true);
    retryDelay = 500;
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") render(message.state);
  });

  socket.addEventListener("close", () => {
    setStatus("reconnecting…", false);
    // Back off so a phone that loses Wi-Fi mid-set does not hammer the bridge.
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 5000);
  });
}

connect();
