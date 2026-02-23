const state = {
  token: localStorage.getItem("session_token") || "",
  profiles: [],
  activeProfileId: localStorage.getItem("active_profile_id") || "",
  playing: false,
};

const byId = (id) => document.getElementById(id);
const logsEl = byId("logs");
const authStatus = byId("authStatus");
const playStatus = byId("playStatus");

function log(message, payload = null) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  logsEl.textContent = `${line}\n${logsEl.textContent}`;
  if (payload) {
    logsEl.textContent = `${JSON.stringify(payload, null, 2)}\n${logsEl.textContent}`;
  }
}

function setVisible(id, show) {
  byId(id).classList.toggle("hidden", !show);
}

function updateUiState() {
  const loggedIn = Boolean(state.token);
  setVisible("profileCard", loggedIn);
  setVisible("gameCard", loggedIn && state.playing);
  if (!loggedIn) {
    authStatus.textContent = "Not logged in";
    playStatus.textContent = "Login first.";
  }
}

async function api(path, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });

  let data;
  try {
    data = await response.json();
  } catch (_error) {
    throw new Error(`HTTP ${response.status}`);
  }

  if (!data.ok) {
    throw new Error(data.error?.message || "Request failed");
  }
  return data.data;
}

function renderProfiles() {
  const select = byId("profileSelect");
  select.innerHTML = "";
  for (const profile of state.profiles) {
    const option = document.createElement("option");
    option.value = profile.player_id;
    option.textContent = `${profile.display_name} (${profile.player_id.slice(0, 6)})`;
    if (profile.player_id === state.activeProfileId) {
      option.selected = true;
    }
    select.appendChild(option);
  }

  if (state.profiles.length === 0) {
    state.activeProfileId = "";
    localStorage.removeItem("active_profile_id");
    playStatus.textContent = "No profile yet. Create one to continue.";
    return;
  }

  const selectedExists = state.profiles.some((p) => p.player_id === state.activeProfileId);
  if (!selectedExists) {
    state.activeProfileId = state.profiles[0].player_id;
    localStorage.setItem("active_profile_id", state.activeProfileId);
  }
  playStatus.textContent = "Select a profile and click Play.";
}

async function refreshProfiles() {
  const data = await api("/profiles");
  state.profiles = data.profiles;
  renderProfiles();
}

async function refreshWorld() {
  if (!state.playing || !state.activeProfileId) {
    return;
  }

  const data = await api("/world/state");
  const tbody = byId("worldBody");
  tbody.innerHTML = "";

  for (const player of data.players) {
    const tr = document.createElement("tr");
    const me = player.player_id === state.activeProfileId;

    tr.innerHTML = `
      <td>${player.display_name}${me ? " (you)" : ""}</td>
      <td>${player.user_id.slice(0, 6)}</td>
      <td>${player.position.x.toFixed(1)}, ${player.position.y.toFixed(1)}</td>
      <td class="${player.online ? "online" : "offline"}">${player.online ? "online" : "offline"}</td>
      <td><button ${me ? "disabled" : ""} data-target="${player.player_id}">Hit</button></td>
    `;

    const button = tr.querySelector("button");
    if (button && !me) {
      button.addEventListener("click", async () => {
        try {
          const hit = await api("/combat/hit", "POST", {
            attacker_player_id: state.activeProfileId,
            target_player_id: player.player_id,
          });
          log(`Hit success on ${player.display_name}`, hit);
          await refreshWorld();
        } catch (error) {
          log(`Hit failed: ${error.message}`);
        }
      });
    }

    tbody.appendChild(tr);
  }
}

async function onLoginSuccess(data, label) {
  state.token = data.session.token;
  state.playing = false;
  localStorage.setItem("session_token", state.token);
  authStatus.textContent = `Logged in as ${data.user.username}`;
  updateUiState();
  await refreshProfiles();
  log(`${label} success`, data);
}

function clearAuthState() {
  state.token = "";
  state.profiles = [];
  state.activeProfileId = "";
  state.playing = false;
  localStorage.removeItem("session_token");
  localStorage.removeItem("active_profile_id");
  byId("worldBody").innerHTML = "";
  renderProfiles();
  updateUiState();
}

function bindEvents() {
  byId("registerBtn").addEventListener("click", async () => {
    try {
      const data = await api("/auth/register", "POST", {
        username: byId("username").value,
        email: byId("email").value,
        password: byId("password").value,
      });
      log("Register success. Please login now.", data);
      authStatus.textContent = `Registered ${data.user.username}. Please login.`;
    } catch (error) {
      log(`Register failed: ${error.message}`);
    }
  });

  byId("loginBtn").addEventListener("click", async () => {
    try {
      const data = await api("/auth/login", "POST", {
        credential: byId("credential").value,
        password: byId("password").value,
      });
      await onLoginSuccess(data, "Login");
    } catch (error) {
      log(`Login failed: ${error.message}`);
    }
  });

  byId("logoutBtn").addEventListener("click", async () => {
    try {
      if (state.token) {
        await api("/auth/logout", "POST");
      }
    } catch (_error) {
      // best effort
    }
    clearAuthState();
    log("Logged out");
  });

  byId("createProfileBtn").addEventListener("click", async () => {
    try {
      const data = await api("/profiles", "POST", {
        display_name: byId("displayName").value,
      });
      log("Profile created", data);
      await refreshProfiles();
    } catch (error) {
      log(`Create profile failed: ${error.message}`);
    }
  });

  byId("profileSelect").addEventListener("change", (event) => {
    state.activeProfileId = event.target.value;
    localStorage.setItem("active_profile_id", state.activeProfileId);
  });

  byId("playBtn").addEventListener("click", async () => {
    if (!state.activeProfileId) {
      playStatus.textContent = "Please create/select a profile first.";
      return;
    }
    try {
      const started = await api("/play/start", "POST", {
        player_id: state.activeProfileId,
      });
      state.playing = true;
      updateUiState();
      playStatus.textContent = `Playing as ${started.player.display_name}.`;
      log("Play started", started);
      await refreshWorld();
    } catch (error) {
      playStatus.textContent = `Play failed: ${error.message}`;
      log(`Play failed: ${error.message}`);
    }
  });

  byId("connectBtn").addEventListener("click", async () => {
    try {
      const data = await api("/session/connect", "POST");
      log("Connected", data);
      await refreshWorld();
    } catch (error) {
      log(`Connect failed: ${error.message}`);
    }
  });

  byId("disconnectBtn").addEventListener("click", async () => {
    try {
      const data = await api("/session/disconnect", "POST");
      log("Disconnected", data);
      await refreshWorld();
    } catch (error) {
      log(`Disconnect failed: ${error.message}`);
    }
  });

  byId("moveBtn").addEventListener("click", async () => {
    if (!state.activeProfileId) {
      log("Pick your active profile first");
      return;
    }
    try {
      const data = await api("/profiles/position", "POST", {
        player_id: state.activeProfileId,
        x: Number(byId("posX").value),
        y: Number(byId("posY").value),
      });
      log("Position updated", data);
      await refreshWorld();
    } catch (error) {
      log(`Move failed: ${error.message}`);
    }
  });

  byId("refreshBtn").addEventListener("click", refreshWorld);
}

async function boot() {
  bindEvents();
  updateUiState();

  if (!state.token) {
    return;
  }

  try {
    const me = await api("/profile/me");
    authStatus.textContent = `Logged in as ${me.profile.username}`;
    await refreshProfiles();
    updateUiState();
  } catch (error) {
    clearAuthState();
    authStatus.textContent = "Session expired. Please login again.";
    log(`Boot session failed: ${error.message}`);
  }
}

boot();
setInterval(() => {
  refreshWorld().catch((error) => log(`Auto refresh failed: ${error.message}`));
}, 3000);
