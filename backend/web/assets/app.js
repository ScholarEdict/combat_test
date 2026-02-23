const state = {
  token: localStorage.getItem("session_token") || "",
  activeProfileId: localStorage.getItem("active_profile_id") || "",
  profiles: [],
  playing: false,
};

const byId = (id) => document.getElementById(id);
const logsEl = byId("logs");

function log(msg, data = null) {
  let text = `[${new Date().toLocaleTimeString()}] ${msg}`;
  if (data) text += `\n${JSON.stringify(data, null, 2)}`;
  logsEl.textContent = `${text}\n\n${logsEl.textContent}`;
}

function setHidden(id, hidden) {
  byId(id).classList.toggle("hidden", hidden);
}

function renderUiState() {
  const loggedIn = Boolean(state.token);
  setHidden("profileCard", !loggedIn);
  setHidden("gameCard", !(loggedIn && state.playing));
  if (!loggedIn) {
    byId("authStatus").textContent = "Not logged in";
    byId("playStatus").textContent = "Login first.";
  }
}

async function api(path, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;

  const resp = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });

  const payload = await resp.json().catch(() => null);
  if (!payload || !payload.ok) {
    throw new Error(payload?.error?.message || `HTTP ${resp.status}`);
  }
  return payload.data;
}

function renderProfiles() {
  const select = byId("profileSelect");
  select.innerHTML = "";
  for (const p of state.profiles) {
    const opt = document.createElement("option");
    opt.value = p.player_id;
    opt.textContent = `${p.display_name} (${p.player_id.slice(0, 6)})`;
    if (p.player_id === state.activeProfileId) opt.selected = true;
    select.appendChild(opt);
  }

  if (!state.profiles.some((p) => p.player_id === state.activeProfileId)) {
    state.activeProfileId = state.profiles[0]?.player_id || "";
  }
  if (state.activeProfileId) {
    localStorage.setItem("active_profile_id", state.activeProfileId);
  } else {
    localStorage.removeItem("active_profile_id");
  }
}

async function refreshProfiles() {
  const data = await api("/profiles");
  state.profiles = data.profiles;
  renderProfiles();
}

async function refreshWorld() {
  if (!state.playing || !state.activeProfileId) return;
  const data = await api("/world/state");
  const tbody = byId("worldBody");
  tbody.innerHTML = "";

  for (const player of data.players) {
    const me = player.player_id === state.activeProfileId;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${player.display_name}${me ? " (you)" : ""}</td>
      <td>${player.user_id.slice(0, 6)}</td>
      <td>${player.position.x.toFixed(1)}, ${player.position.y.toFixed(1)}</td>
      <td class="${player.online ? "online" : "offline"}">${player.online ? "online" : "offline"}</td>
      <td><button ${me ? "disabled" : ""}>Hit</button></td>
    `;

    const hitBtn = row.querySelector("button");
    if (!me) {
      hitBtn.addEventListener("click", async () => {
        try {
          const result = await api("/combat/hit", "POST", {
            attacker_player_id: state.activeProfileId,
            target_player_id: player.player_id,
          });
          log(`Hit success on ${player.display_name}`, result);
          await refreshWorld();
        } catch (err) {
          log(`Hit failed: ${err.message}`);
        }
      });
    }

    tbody.appendChild(row);
  }
}

function clearSession() {
  state.token = "";
  state.playing = false;
  state.profiles = [];
  state.activeProfileId = "";
  localStorage.removeItem("session_token");
  localStorage.removeItem("active_profile_id");
  byId("worldBody").innerHTML = "";
  renderProfiles();
  renderUiState();
}

function bindEvents() {
  byId("registerBtn").addEventListener("click", async () => {
    try {
      const data = await api("/auth/register", "POST", {
        username: byId("username").value,
        email: byId("email").value,
        password: byId("password").value,
      });
      byId("authStatus").textContent = `Registered ${data.user.username}. Login now.`;
      log("Register success", data);
    } catch (err) {
      log(`Register failed: ${err.message}`);
    }
  });

  byId("loginBtn").addEventListener("click", async () => {
    try {
      const data = await api("/auth/login", "POST", {
        credential: byId("credential").value,
        password: byId("password").value,
      });
      state.token = data.session.token;
      state.playing = false;
      localStorage.setItem("session_token", state.token);
      byId("authStatus").textContent = `Logged in as ${data.user.username}`;
      renderUiState();
      await refreshProfiles();
      log("Login success", data);
    } catch (err) {
      log(`Login failed: ${err.message}`);
    }
  });

  byId("logoutBtn").addEventListener("click", async () => {
    try { if (state.token) await api("/auth/logout", "POST"); } catch (_e) {}
    clearSession();
    log("Logged out");
  });

  byId("createProfileBtn").addEventListener("click", async () => {
    try {
      const data = await api("/profiles", "POST", { display_name: byId("displayName").value });
      log("Profile created", data);
      await refreshProfiles();
    } catch (err) {
      log(`Create profile failed: ${err.message}`);
    }
  });

  byId("profileSelect").addEventListener("change", (e) => {
    state.activeProfileId = e.target.value;
    localStorage.setItem("active_profile_id", state.activeProfileId);
  });

  byId("playBtn").addEventListener("click", async () => {
    if (!state.activeProfileId) {
      byId("playStatus").textContent = "Create/select profile first.";
      return;
    }
    try {
      const data = await api("/play/start", "POST", { player_id: state.activeProfileId });
      state.playing = true;
      byId("playStatus").textContent = `Playing as ${data.player.display_name}`;
      renderUiState();
      await refreshWorld();
      log("Play started", data);
    } catch (err) {
      byId("playStatus").textContent = `Play failed: ${err.message}`;
      log(`Play failed: ${err.message}`);
    }
  });

  byId("connectBtn").addEventListener("click", async () => {
    try { log("Connected", await api("/session/connect", "POST")); await refreshWorld(); }
    catch (err) { log(`Connect failed: ${err.message}`); }
  });

  byId("disconnectBtn").addEventListener("click", async () => {
    try { log("Disconnected", await api("/session/disconnect", "POST")); await refreshWorld(); }
    catch (err) { log(`Disconnect failed: ${err.message}`); }
  });

  byId("moveBtn").addEventListener("click", async () => {
    if (!state.activeProfileId) return;
    try {
      const data = await api("/profiles/position", "POST", {
        player_id: state.activeProfileId,
        x: Number(byId("posX").value),
        y: Number(byId("posY").value),
      });
      log("Position updated", data);
      await refreshWorld();
    } catch (err) {
      log(`Move failed: ${err.message}`);
    }
  });

  byId("refreshBtn").addEventListener("click", refreshWorld);
}

async function boot() {
  bindEvents();
  renderUiState();
  if (!state.token) return;

  try {
    const me = await api("/profile/me");
    byId("authStatus").textContent = `Logged in as ${me.profile.username}`;
    await refreshProfiles();
    renderUiState();
  } catch (err) {
    clearSession();
    log(`Session invalid: ${err.message}`);
  }
}

boot();
setInterval(() => refreshWorld().catch((err) => log(`Auto refresh failed: ${err.message}`)), 3000);
