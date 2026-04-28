/**
 * PHANTOM EYE - Dashboard JS
 * All UI logic: views, camera grid, settings, alerts, modals.
 */

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  cameras: [],
  settings: {},
  alerts: [],
  focusCamId: null,
  pollingInterval: null,
};

// ─── API helpers ───────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

// ─── Toast ─────────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, err = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (err ? " toast--err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

// ─── Clock ─────────────────────────────────────────────────────────────────────
function startClock() {
  function tick() {
    document.getElementById("clock").textContent =
      new Date().toLocaleTimeString("en-US", { hour12: false });
  }
  tick();
  setInterval(tick, 1000);
}

// ─── View switching ────────────────────────────────────────────────────────────
function switchView(name) {
  document
    .querySelectorAll(".view")
    .forEach((v) => v.classList.remove("active"));
  document
    .querySelectorAll(".nav-btn")
    .forEach((b) => b.classList.remove("active"));
  document.getElementById(`view-${name}`).classList.add("active");
  document.querySelector(`[data-view="${name}"]`).classList.add("active");
  if (name === "alerts") refreshAlerts();
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// ─── Toggles ───────────────────────────────────────────────────────────────────
function bindToggle(id, settingKey, onChange) {
  const el = document.getElementById(id);
  el.addEventListener("click", async () => {
    const on = !el.classList.contains("on");
    el.classList.toggle("on", on);
    state.settings[settingKey] = on;
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ [settingKey]: on }),
    });
    toast(
      `${settingKey.replace(/_/g, " ").toUpperCase()} ${on ? "ON" : "OFF"}`,
    );
    if (onChange) onChange(on);
  });
}

function setToggle(id, on) {
  document.getElementById(id).classList.toggle("on", on);
}

// ─── Camera grid ───────────────────────────────────────────────────────────────
function renderGrid(cameras) {
  const grid = document.getElementById("camera-grid");
  const empty = document.getElementById("empty-state");

  if (!cameras.length) {
    grid.innerHTML = "";
    grid.appendChild(empty);
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");

  // Update existing cells or add new ones
  const existing = new Set(
    [...grid.querySelectorAll(".camera-cell")].map((c) => c.dataset.camId),
  );

  cameras.forEach((cam) => {
    let cell = grid.querySelector(`[data-cam-id="${cam.id}"]`);

    if (!cell) {
      cell = buildCameraCell(cam);
      grid.appendChild(cell);
    } else {
      updateCameraCell(cell, cam);
    }
    existing.delete(cam.id);
  });

  // Remove deleted cameras
  existing.forEach((id) => {
    const el = grid.querySelector(`[data-cam-id="${id}"]`);
    if (el) el.remove();
  });
}

function buildCameraCell(cam) {
  const div = document.createElement("div");
  div.className = "camera-cell";
  div.dataset.camId = cam.id;
  div.innerHTML = `
    <img class="cam-stream" src="/stream/${cam.id}" alt="${cam.name}"
         onerror="this.src='/snapshot/${cam.id}'">
    <div class="cam-hud">
      <span class="cam-name">${cam.name}</span>
      <div class="cam-badges">
        <span class="cam-badge ${cam.online ? "cam-badge--online" : "cam-badge--offline"}">
          ${cam.online ? "LIVE" : "OFFLINE"}
        </span>
      </div>
      <button class="cam-menu-btn" title="Camera options">⋮</button>
    </div>
  `;

  div.querySelector(".cam-stream").addEventListener("click", () => {
    focusCamera(cam.id);
  });

  div.querySelector(".cam-menu-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    showCamMenu(cam, e.target);
  });

  return div;
}

function updateCameraCell(cell, cam) {
  const badge = cell.querySelector(".cam-badge");
  badge.className = `cam-badge ${cam.online ? "cam-badge--online" : "cam-badge--offline"}`;
  badge.textContent = cam.online ? "LIVE" : "OFFLINE";

  // Detection badge
  let detBadge = cell.querySelector(".cam-badge--detect");
  if (cam.detections && cam.detections.length) {
    if (!detBadge) {
      detBadge = document.createElement("span");
      detBadge.className = "cam-badge cam-badge--detect";
      cell.querySelector(".cam-badges").prepend(detBadge);
    }
    const classes = [...new Set(cam.detections.map((d) => d.class))];
    detBadge.textContent = classes.join(", ").toUpperCase();
    cell.classList.add("camera-cell--detected");
  } else {
    detBadge?.remove();
    cell.classList.remove("camera-cell--detected");
  }

  // Motion
  cell.classList.toggle("camera-cell--motion", !!cam.motion);

  // Offline styling
  cell.classList.toggle("camera-cell--offline", !cam.online);
}

// ─── Camera context menu ───────────────────────────────────────────────────────
function showCamMenu(cam, anchor) {
  // Simple menu using prompt/confirm for minimal dependencies
  const action = prompt(
    `CAMERA: ${cam.name}\n\n` +
      "1 - Rename\n" +
      "2 - Delete\n" +
      "3 - Toggle AI for this cam\n" +
      "4 - Cancel\n\n" +
      "Enter option:",
  );

  if (action === "1") {
    const newName = prompt("New camera name:", cam.name);
    if (newName)
      api(`/api/cameras/${cam.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: newName }),
      }).then(() => {
        toast("Renamed");
        poll();
      });
  } else if (action === "2") {
    if (confirm(`Delete camera "${cam.name}"?`)) {
      api(`/api/cameras/${cam.id}`, { method: "DELETE" }).then(() => {
        toast("Camera removed");
        poll();
      });
    }
  } else if (action === "3") {
    const override = cam.ai_enabled_override;
    let next;
    if (override === null || override === undefined) {
      next = !state.settings.ai_enabled;
    } else {
      next = !override;
    }
    api(`/api/cameras/${cam.id}`, {
      method: "PATCH",
      body: JSON.stringify({ ai_enabled_override: next }),
    }).then(() => {
      toast(`AI ${next ? "ON" : "OFF"} for ${cam.name}`);
    });
  }
}

// ─── Focus view ────────────────────────────────────────────────────────────────
function focusCamera(camId) {
  switchView("focus");
  state.focusCamId = camId;

  const cam = state.cameras.find((c) => c.id === camId);
  if (!cam) return;

  document.getElementById("focus-stream").src = `/stream/${camId}`;
  document.getElementById("focus-name").textContent = cam.name;
  renderFocusSidebar();
}

function renderFocusSidebar() {
  const list = document.getElementById("focus-cam-list");
  list.innerHTML = state.cameras
    .map(
      (c) => `
    <div class="focus-cam-item ${c.id === state.focusCamId ? "active" : ""} ${!c.online ? "offline" : ""}"
         onclick="focusCamera('${c.id}')">
      ${c.name} ${!c.online ? "(offline)" : ""}
    </div>
  `,
    )
    .join("");

  // Detection list
  const cam = state.cameras.find((c) => c.id === state.focusCamId);
  const detList = document.getElementById("focus-det-list");
  if (!cam || !cam.detections?.length) {
    detList.innerHTML = `<span style="color:var(--muted);font-size:.68rem">None</span>`;
  } else {
    detList.innerHTML = cam.detections
      .map(
        (d) => `
      <div class="det-item">
        <span class="det-class">${d.class.toUpperCase()}</span>
        <span class="det-conf">${Math.round(d.confidence * 100)}%</span>
      </div>
    `,
      )
      .join("");
  }
}

document.getElementById("btn-snapshot").addEventListener("click", () => {
  if (!state.focusCamId) return;
  const a = document.createElement("a");
  a.href = `/snapshot/${state.focusCamId}`;
  a.download = `${state.focusCamId}_${Date.now()}.jpg`;
  a.click();
  toast("Snapshot saved");
});

// ─── Alerts ────────────────────────────────────────────────────────────────────
async function refreshAlerts() {
  const alerts = await api("/api/alerts?limit=100");
  state.alerts = alerts;

  const list = document.getElementById("alert-list");
  if (!alerts.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">✓</span><p>NO ALERTS</p></div>`;
    return;
  }

  list.innerHTML = alerts
    .map((a) => {
      const t = new Date(a.timestamp).toLocaleString();
      const isDetect = a.type.startsWith("detection");
      const snap = a.snapshot
        ? `<img class="alert-snap" src="/api/alerts/snapshots/${a.snapshot}"
             onclick="window.open(this.src)" title="Click to enlarge">`
        : "";
      return `
      <div class="alert-item alert-item--${isDetect ? "detection" : "motion"}">
        <span class="alert-time">${t}</span>
        <span class="alert-cam">${a.cam_name}</span>
        <span class="alert-msg">${a.detail}</span>
        ${snap}
      </div>
    `;
    })
    .join("");

  // Update badge
  const badge = document.getElementById("alert-badge");
  if (alerts.length > 0) {
    badge.textContent = alerts.length;
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

document
  .getElementById("btn-clear-alerts")
  .addEventListener("click", async () => {
    if (!confirm("Clear all alerts?")) return;
    await api("/api/alerts", { method: "DELETE" });
    toast("Alerts cleared");
    refreshAlerts();
  });

// ─── Settings ──────────────────────────────────────────────────────────────────
async function loadSettings() {
  const s = await api("/api/settings");
  state.settings = s;

  setToggle("toggle-ai", s.ai_enabled);
  setToggle("toggle-motion", s.motion_enabled);
  setToggle("toggle-snap", s.snapshot_on_alert);

  document.getElementById("set-ai-model").value = s.ai_model || "yolov8n.pt";
  document.getElementById("set-confidence").value = Math.round(
    (s.ai_confidence || 0.5) * 100,
  );
  document.getElementById("set-confidence-val").textContent =
    `${Math.round((s.ai_confidence || 0.5) * 100)}%`;
  document.getElementById("set-alert-classes").value = (
    s.alert_classes || []
  ).join(", ");
  document.getElementById("set-alert-cooldown").value = s.alert_cooldown || 30;
  document.getElementById("set-motion-sens").value = s.motion_sensitivity || 25;
  document.getElementById("set-motion-val").textContent =
    s.motion_sensitivity || 25;
  document.getElementById("set-server-name").value =
    s.server_name || "Phantom Eye";

  // AI install status
  const status = await api("/api/status");
  const aiEl = document.getElementById("ai-install-status");
  if (status.ai_available) {
    aiEl.textContent =
      "✓ YOLO / Ultralytics installed\n✓ AI detection available";
    aiEl.style.color = "var(--accent)";
  } else {
    aiEl.textContent =
      "✗ Ultralytics not installed\n\nRun:\npip install ultralytics\n\nthen restart the server.";
    aiEl.style.color = "var(--accent3)";
  }

  // AI dot
  document.getElementById("ai-dot").className =
    `dot ${status.ai_enabled && status.ai_available ? "dot--cyan pulse" : "dot--off"}`;
}

document.getElementById("set-confidence").addEventListener("input", (e) => {
  document.getElementById("set-confidence-val").textContent =
    `${e.target.value}%`;
});

document.getElementById("set-motion-sens").addEventListener("input", (e) => {
  document.getElementById("set-motion-val").textContent = e.target.value;
});

document
  .getElementById("btn-save-settings")
  .addEventListener("click", async () => {
    const classes = document
      .getElementById("set-alert-classes")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const payload = {
      ai_model: document.getElementById("set-ai-model").value,
      ai_confidence:
        parseInt(document.getElementById("set-confidence").value) / 100,
      alert_classes: classes,
      alert_cooldown: parseInt(
        document.getElementById("set-alert-cooldown").value,
      ),
      motion_sensitivity: parseInt(
        document.getElementById("set-motion-sens").value,
      ),
      server_name: document.getElementById("set-server-name").value,
      snapshot_on_alert: document
        .getElementById("toggle-snap")
        .classList.contains("on"),
    };

    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    toast("Settings saved");
    loadSettings();
  });

// ─── Add camera modal ──────────────────────────────────────────────────────────
function openAddCam() {
  document.getElementById("modal-add-cam").classList.remove("hidden");
}

document.getElementById("btn-add-cam").addEventListener("click", openAddCam);
document.getElementById("btn-modal-cancel").addEventListener("click", () => {
  document.getElementById("modal-add-cam").classList.add("hidden");
});

document
  .getElementById("btn-modal-save")
  .addEventListener("click", async () => {
    const name = document.getElementById("new-cam-name").value.trim();
    const url = document.getElementById("new-cam-url").value.trim();
    if (!name || !url) {
      toast("Name and URL required", true);
      return;
    }

    await api("/api/cameras", {
      method: "POST",
      body: JSON.stringify({ name, stream_url: url }),
    });
    document.getElementById("modal-add-cam").classList.add("hidden");
    document.getElementById("new-cam-name").value = "";
    document.getElementById("new-cam-url").value = "";
    toast(`Camera "${name}" added`);
    poll();
  });

// ─── Discover modal ────────────────────────────────────────────────────────────
document.getElementById("btn-discover").addEventListener("click", () => {
  document.getElementById("modal-discover").classList.remove("hidden");
});

document.getElementById("btn-discover-cancel").addEventListener("click", () => {
  document.getElementById("modal-discover").classList.add("hidden");
});

document
  .getElementById("btn-discover-scan")
  .addEventListener("click", async () => {
    const subnet = document.getElementById("discover-subnet").value.trim();
    const resultsEl = document.getElementById("discover-results");
    resultsEl.innerHTML = `<div class="discover-item">Scanning ${subnet}.1–254 …</div>`;
    resultsEl.classList.remove("hidden");

    const found = await api("/api/discover", {
      method: "POST",
      body: JSON.stringify({ subnet }),
    });

    if (!found.length) {
      resultsEl.innerHTML = `<div class="discover-item">No cameras found.</div>`;
      return;
    }

    resultsEl.innerHTML = found
      .map(
        (c) => `
    <div class="discover-item">
      <span>${c.name} — ${c.ip}</span>
      <button class="tool-btn" onclick="addDiscoveredCam('${c.name}', '${c.ip}')">
        ADD
      </button>
    </div>
  `,
      )
      .join("");
  });

async function addDiscoveredCam(name, ip) {
  await api("/api/cameras", {
    method: "POST",
    body: JSON.stringify({ name, stream_url: `http://${ip}/stream` }),
  });
  toast(`Added: ${name}`);
  document.getElementById("modal-discover").classList.add("hidden");
  poll();
}

// ─── Polling ───────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const [cameras, status] = await Promise.all([
      api("/api/cameras"),
      api("/api/status"),
    ]);

    state.cameras = cameras;

    // Header stats
    document.getElementById("stat-online").textContent = status.cameras_online;
    document.getElementById("stat-total").textContent = status.cameras_total;

    // AI dot
    document.getElementById("ai-dot").className =
      `dot ${status.ai_enabled && status.ai_available ? "dot--cyan pulse" : "dot--off"}`;

    // Alert badge
    const badge = document.getElementById("alert-badge");
    if (status.alerts_total > 0) {
      badge.textContent = status.alerts_total;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }

    renderGrid(cameras);

    if (document.getElementById("view-focus").classList.contains("active")) {
      renderFocusSidebar();
    }
  } catch (e) {
    console.error("Poll error:", e);
  }
}

// ─── Global toggle bindings ────────────────────────────────────────────────────
bindToggle("toggle-ai", "ai_enabled");
bindToggle("toggle-motion", "motion_enabled");
bindToggle("toggle-snap", "snapshot_on_alert");

// ─── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  startClock();
  await loadSettings();
  await poll();
  state.pollingInterval = setInterval(poll, 2000);
}

init();
