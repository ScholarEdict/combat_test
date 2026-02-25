const state = {
  token: localStorage.getItem("session_token") || "",
  profiles: [],
  activeProfileId: localStorage.getItem("active_profile_id") || "",
  inGame: false,
};

const byId = (id) => document.getElementById(id);
const logsEl = byId("logs");
const authStatus = byId("authStatus");
const lobbyStatus = byId("lobbyStatus");

function log(message, payload = null) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  logsEl.textContent = `${line}\n${logsEl.textContent}`;
  if (payload) {
    logsEl.textContent = `${JSON.stringify(payload, null, 2)}\n${logsEl.textContent}`;
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
  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.error?.message || "Request failed");
  }
  return data.data;
}

function updateView() {
  const loggedIn = Boolean(state.token);
  byId("authCard").classList.toggle("hidden", loggedIn);
  byId("lobbyCard").classList.toggle("hidden", !loggedIn || state.inGame);
  byId("gameCard").classList.toggle("hidden", !loggedIn || !state.inGame);
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

  if (!state.profiles.some((profile) => profile.player_id === state.activeProfileId)) {
    state.activeProfileId = state.profiles.length > 0 ? state.profiles[0].player_id : "";
  }

  if (state.activeProfileId) {
    localStorage.setItem("active_profile_id", state.activeProfileId);
    lobbyStatus.textContent = "Profile selected. Click Play to enter the game.";
  } else {
    localStorage.removeItem("active_profile_id");
    lobbyStatus.textContent = "Create or select a profile, then click Play.";
  }
}

async function refreshProfiles() {
  const data = await api("/profiles");
  state.profiles = data.profiles;
  renderProfiles();
}

async function refreshWorld() {
  if (!state.inGame) {
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
        if (!state.activeProfileId) {
          log("Pick your active profile first");
          return;
        }
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

async function enterGame() {
  if (!state.activeProfileId) {
    log("Select or create a profile before playing");
    return;
  }

  try {
    await api("/session/connect", "POST", {
      player_id: state.activeProfileId,
    });
    state.inGame = true;
    updateView();
    await refreshWorld();
    log("Entered game world");
  } catch (error) {
    log(`Unable to enter game: ${error.message}`);
  }
}

async function leaveGame() {
  try {
    await api("/session/disconnect", "POST", {
      player_id: state.activeProfileId,
    });
  } catch (_error) {
    // Ignore disconnect failure.
  }

  state.inGame = false;
  byId("worldBody").innerHTML = "";
  updateView();
  log("Returned to profile selection");
}

function resetAuthState(message = "Not logged in") {
  state.token = "";
  state.profiles = [];
  state.activeProfileId = "";
  state.inGame = false;

  localStorage.removeItem("session_token");
  localStorage.removeItem("active_profile_id");

  byId("worldBody").innerHTML = "";
  authStatus.textContent = message;
  renderProfiles();
  updateView();
}

function bindEvents() {
  byId("registerBtn").addEventListener("click", async () => {
    try {
      const data = await api("/auth/register", "POST", {
        username: byId("username").value,
        email: byId("email").value,
        password: byId("password").value,
      });
      state.token = data.session.token;
      localStorage.setItem("session_token", state.token);
      authStatus.textContent = `Logged in as ${data.user.username}`;
      log("Register success", data);
      await refreshProfiles();
      updateView();
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
      state.token = data.session.token;
      localStorage.setItem("session_token", state.token);
      authStatus.textContent = `Logged in as ${data.user.username}`;
      log("Login success", data);
      await refreshProfiles();
      updateView();
    } catch (error) {
      log(`Login failed: ${error.message}`);
    }
  });

  byId("logoutBtn").addEventListener("click", async () => {
    try {
      await api("/auth/logout", "POST");
    } catch (_error) {
      // Ignore logout failure.
    }
    resetAuthState("Not logged in");
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
    renderProfiles();
  });

  byId("playBtn").addEventListener("click", enterGame);
  byId("changeProfileBtn").addEventListener("click", leaveGame);

  byId("disconnectBtn").addEventListener("click", async () => {
    try {
      const data = await api("/session/disconnect", "POST", {
        player_id: state.activeProfileId,
      });
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
      const x = Number(byId("posX").value);
      const y = Number(byId("posY").value);
      const data = await api("/profiles/position", "POST", {
        player_id: state.activeProfileId,
        x,
        y,
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
  updateView();

  if (!state.token) {
    authStatus.textContent = "Not logged in";
    return;
  }

  try {
    const me = await api("/profile/me");
    authStatus.textContent = `Logged in as ${me.profile.username}`;
    await refreshProfiles();
    updateView();
  } catch (error) {
    resetAuthState("Session expired. Please login again.");
    log(`Boot session failed: ${error.message}`);
  }
}

boot();
setInterval(() => {
  if (state.token && state.inGame) {
    refreshWorld().catch((error) => log(`Auto refresh failed: ${error.message}`));
  }
}, 3000);
