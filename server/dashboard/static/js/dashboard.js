/**
 * PHANTOM EYE — Dashboard JS v2
 * New: camera HW settings, LED, recording, history stats, plugins tab,
 *      mobile nav, badge fix, per-camera overrides, recordings list.
 */

// ─── State ────────────────────────────────────────────────────────────────────
const S = {
  cameras: [],
  settings: {},
  focusCam: null, // cam_id string
  ledStates: {}, // {cam_id: bool}
  recStates: {}, // {cam_id: bool}
};

// ─── API ──────────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// ─── Toast ────────────────────────────────────────────────────────────────────
let _toastTimer;
function toast(msg, err = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (err ? " toast--err" : "");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

// ─── Clock ────────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById("clock");
  const tick = () => {
    if (el)
      el.textContent = new Date().toLocaleTimeString("en-US", {
        hour12: false,
      });
  };
  tick();
  setInterval(tick, 1000);
}

// ─── Mobile nav ───────────────────────────────────────────────────────────────
const hamburger = document.getElementById("hamburger");
const nav = document.getElementById("hud-nav");
hamburger.addEventListener("click", () => nav.classList.toggle("open"));

// Close nav when a button is tapped on mobile
nav.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => nav.classList.remove("open"));
});

// ─── View switching ───────────────────────────────────────────────────────────
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
  if (name === "settings") loadSettingsUI();
  if (name === "focus") renderFocusSidebar();
}
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// ─── Settings tabs ────────────────────────────────────────────────────────────
document.querySelectorAll(".stab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document
      .querySelectorAll(".stab")
      .forEach((b) => b.classList.remove("active"));
    document
      .querySelectorAll(".stab-panel")
      .forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`stab-${btn.dataset.stab}`).classList.add("active");
    if (btn.dataset.stab === "plugins") loadPluginsUI();
    if (btn.dataset.stab === "recordings") loadRecordingsUI();
  });
});

// ─── Toggle helper ────────────────────────────────────────────────────────────
function bindToggle(id, cb) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("click", () => {
    const on = !el.classList.contains("on");
    el.classList.toggle("on", on);
    cb(on);
  });
}
function setToggle(id, on) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle("on", on);
}

// ─── Camera grid ──────────────────────────────────────────────────────────────
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

  const existing = new Set(
    [...grid.querySelectorAll(".camera-cell")].map((c) => c.dataset.camId),
  );

  cameras.forEach((cam) => {
    let cell = grid.querySelector(`[data-cam-id="${cam.id}"]`);
    if (!cell) {
      cell = buildCell(cam);
      grid.appendChild(cell);
    } else {
      updateCell(cell, cam);
    }
    existing.delete(cam.id);
  });

  existing.forEach((id) =>
    grid.querySelector(`[data-cam-id="${id}"]`)?.remove(),
  );
}

function buildCell(cam) {
  const div = document.createElement("div");
  div.className = "camera-cell";
  div.dataset.camId = cam.id;
  div.innerHTML = `
    <img class="cam-stream" src="/stream/${cam.id}" alt="${cam.name}"
         onerror="this.src='/snapshot/${cam.id}'">
    <div class="cam-hud">
      <span class="cam-name">${cam.name}</span>
      <div class="cam-badges">
        <span class="cam-status-badge cam-badge ${cam.online ? "cam-badge--online" : "cam-badge--offline"}">
          ${cam.online ? "LIVE" : "OFFLINE"}
        </span>
      </div>
      <button class="cam-menu-btn" title="Options">⋮</button>
    </div>`;

  div
    .querySelector(".cam-stream")
    .addEventListener("click", () => focusCamera(cam.id));
  div.querySelector(".cam-menu-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    showCamMenu(cam, e.target);
  });
  return div;
}

function updateCell(cell, cam) {
  const badges = cell.querySelector(".cam-badges");

  // Status badge (always present — LIVE / OFFLINE only, never duplicated)
  let statusBadge = cell.querySelector(".cam-status-badge");
  if (!statusBadge) {
    statusBadge = document.createElement("span");
    statusBadge.className = "cam-status-badge cam-badge";
    badges.appendChild(statusBadge);
  }
  statusBadge.className = `cam-status-badge cam-badge ${cam.online ? "cam-badge--online" : "cam-badge--offline"}`;
  statusBadge.textContent = cam.online ? "LIVE" : "OFFLINE";

  // Detection badge — separate element, only when detections exist
  let detBadge = cell.querySelector(".cam-det-badge");
  const classes = cam.detections?.length
    ? [...new Set(cam.detections.map((d) => d.class))]
    : [];
  if (classes.length) {
    if (!detBadge) {
      detBadge = document.createElement("span");
      detBadge.className = "cam-det-badge cam-badge cam-badge--alert";
      badges.insertBefore(detBadge, statusBadge);
    }
    detBadge.textContent = classes.join(", ").toUpperCase();
    cell.classList.add("camera-cell--detected");
  } else {
    detBadge?.remove();
    cell.classList.remove("camera-cell--detected");
  }

  // Motion badge
  let motBadge = cell.querySelector(".cam-mot-badge");
  if (cam.motion) {
    if (!motBadge) {
      motBadge = document.createElement("span");
      motBadge.className = "cam-mot-badge cam-badge cam-badge--motion";
      motBadge.textContent = "MOTION";
      badges.insertBefore(motBadge, statusBadge);
    }
    cell.classList.add("camera-cell--motion");
  } else {
    motBadge?.remove();
    cell.classList.remove("camera-cell--motion");
  }

  // Recording badge
  let recBadge = cell.querySelector(".cam-rec-badge");
  if (cam.recording) {
    if (!recBadge) {
      recBadge = document.createElement("span");
      recBadge.className = "cam-rec-badge cam-badge cam-badge--rec";
      recBadge.textContent = "⏺ REC";
      badges.insertBefore(recBadge, statusBadge);
    }
  } else {
    recBadge?.remove();
  }

  cell.classList.toggle("camera-cell--offline", !cam.online);
}

// ─── Camera context menu ──────────────────────────────────────────────────────
function showCamMenu(cam, anchor) {
  const opts = [
    "1 — Rename",
    "2 — Delete",
    "3 — Camera HW settings",
    "4 — Toggle AI (this cam)",
    "5 — Focus view",
    "6 — Cancel",
  ];
  const action = prompt(
    `CAMERA: ${cam.name}\n\n${opts.join("\n")}\n\nEnter option:`,
  );
  if (!action) return;

  if (action === "1") {
    const n = prompt("New name:", cam.name);
    if (n)
      api(`/api/cameras/${cam.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: n }),
      }).then(() => {
        toast("Renamed");
        poll();
      });
  } else if (action === "2") {
    if (confirm(`Delete "${cam.name}"?`))
      api(`/api/cameras/${cam.id}`, { method: "DELETE" }).then(() => {
        toast("Camera removed");
        poll();
      });
  } else if (action === "3") {
    openCamSettings(cam);
  } else if (action === "4") {
    const ov = cam.ai_enabled_override;
    const next = ov === null || ov === undefined ? !S.settings.ai_enabled : !ov;
    api(`/api/cameras/${cam.id}`, {
      method: "PATCH",
      body: JSON.stringify({ ai_enabled_override: next }),
    }).then(() => toast(`AI ${next ? "ON" : "OFF"} for ${cam.name}`));
  } else if (action === "5") {
    focusCamera(cam.id);
  }
}

// ─── Per-camera settings override modal ───────────────────────────────────────
let _camSettingsCamId = null;
function openCamSettings(cam) {
  _camSettingsCamId = cam.id;
  document.getElementById("cam-settings-title").textContent =
    `CAMERA SETTINGS — ${cam.name}`;
  const ov = cam.cam_settings_override || {};
  const setOv = (id, key) => {
    const el = document.getElementById(id);
    if (el) el.value = ov[key] !== undefined ? ov[key] : "";
  };
  setOv("ov-framesize", "framesize");
  setOv("ov-quality", "quality");
  setOv("ov-brightness", "brightness");
  setOv("ov-contrast", "contrast");
  setOv("ov-saturation", "saturation");
  setOv("ov-vflip", "vflip");
  setOv("ov-hmirror", "hmirror");
  setOv("ov-special-effect", "special_effect");
  document.getElementById("modal-cam-settings").classList.remove("hidden");
}

document
  .getElementById("btn-cam-settings-cancel")
  .addEventListener("click", () => {
    document.getElementById("modal-cam-settings").classList.add("hidden");
  });

document
  .getElementById("btn-cam-settings-save")
  .addEventListener("click", async () => {
    if (!_camSettingsCamId) return;
    const ov = {};
    const grab = (id, key, isNum = true) => {
      const v = document.getElementById(id).value;
      if (v !== "") ov[key] = isNum ? Number(v) : v;
    };
    grab("ov-framesize", "framesize");
    grab("ov-quality", "quality");
    grab("ov-brightness", "brightness");
    grab("ov-contrast", "contrast");
    grab("ov-saturation", "saturation");
    grab("ov-vflip", "vflip");
    grab("ov-hmirror", "hmirror");
    grab("ov-special-effect", "special_effect");

    await api(`/api/cameras/${_camSettingsCamId}`, {
      method: "PATCH",
      body: JSON.stringify({ cam_settings_override: ov }),
    });
    toast("Camera settings applied");
    document.getElementById("modal-cam-settings").classList.add("hidden");
    poll();
  });

// ─── Focus view ───────────────────────────────────────────────────────────────
function focusCamera(camId) {
  switchView("focus");
  S.focusCam = camId;
  const cam = S.cameras.find((c) => c.id === camId);
  document.getElementById("focus-stream").src = `/stream/${camId}`;
  document.getElementById("focus-name").textContent = cam?.name || camId;
  const recBtn = document.getElementById("btn-record");
  const ledBtn = document.getElementById("btn-led");
  recBtn.classList.toggle("recording", !!cam?.recording);
  recBtn.textContent = cam?.recording ? "⏹ STOP REC" : "⏺ RECORD";
  ledBtn.classList.toggle("led-on", !!cam?.led);
  ledBtn.textContent = cam?.led ? "💡 LED ON" : "💡 LED OFF";
  renderFocusSidebar();
  refreshCamHistory();
}

function renderFocusSidebar() {
  const list = document.getElementById("focus-cam-list");
  list.innerHTML = S.cameras
    .map(
      (c) => `
    <div class="focus-cam-item ${c.id === S.focusCam ? "active" : ""} ${!c.online ? "offline" : ""}"
         onclick="focusCamera('${c.id}')">
      ${c.name}${!c.online ? " (offline)" : ""}
    </div>`,
    )
    .join("");

  const cam = S.cameras.find((c) => c.id === S.focusCam);
  const detList = document.getElementById("focus-det-list");
  if (!cam?.detections?.length) {
    detList.innerHTML = `<span class="no-data">None</span>`;
  } else {
    detList.innerHTML = cam.detections
      .map(
        (d) => `
      <div class="det-item">
        <span class="det-class">${d.class.toUpperCase()}</span>
        <span class="det-conf">${Math.round(d.confidence * 100)}%</span>
      </div>`,
      )
      .join("");
  }
}

// Snapshot
document.getElementById("btn-snapshot").addEventListener("click", () => {
  if (!S.focusCam) return;
  const a = document.createElement("a");
  a.href = `/snapshot/${S.focusCam}`;
  a.download = `${S.focusCam}_${Date.now()}.jpg`;
  a.click();
  toast("Snapshot saved");
});

// Recording
document.getElementById("btn-record").addEventListener("click", async () => {
  if (!S.focusCam) return;
  const cam = S.cameras.find((c) => c.id === S.focusCam);
  const action = cam?.recording ? "stop" : "start";
  await api(`/api/cameras/${S.focusCam}/recording`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
  toast(action === "start" ? "Recording started" : "Recording stopped");
  poll();
});

// LED
document.getElementById("btn-led").addEventListener("click", async () => {
  if (!S.focusCam) return;
  const cam = S.cameras.find((c) => c.id === S.focusCam);
  const on = !cam?.led;
  await api(`/api/cameras/${S.focusCam}/led`, {
    method: "POST",
    body: JSON.stringify({ on }),
  });
  toast(`LED ${on ? "ON" : "OFF"}`);
  poll();
});

// ─── History / Stats ──────────────────────────────────────────────────────────
document
  .getElementById("btn-history-refresh")
  .addEventListener("click", refreshCamHistory);
document
  .getElementById("hist-from")
  .addEventListener("change", refreshCamHistory);
document
  .getElementById("hist-to")
  .addEventListener("change", refreshCamHistory);

async function refreshCamHistory() {
  if (!S.focusCam) return;
  const from = document.getElementById("hist-from").value;
  const to = document.getElementById("hist-to").value;
  let url = `/api/stats?cam_id=${S.focusCam}`;
  if (from) url += `&from=${from}`;
  if (to) url += `&to=${to}`;

  const stats = await api(url).catch(() => null);
  if (!stats) return;

  document.getElementById("stat-detections").textContent =
    stats.total_detections;
  document.getElementById("stat-motion").textContent = stats.motion_events;

  // Class bars
  const cc = stats.class_counts || {};
  const total = Math.max(...Object.values(cc), 1);
  const brkEl = document.getElementById("class-breakdown");
  brkEl.innerHTML = Object.entries(cc)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6)
    .map(
      ([cls, cnt]) => `
      <div class="class-bar">
        <span class="class-bar-label">${cls}</span>
        <div class="class-bar-track">
          <div class="class-bar-fill" style="width:${Math.round((cnt / total) * 100)}%"></div>
        </div>
        <span class="class-bar-count">${cnt}</span>
      </div>`,
    )
    .join("");

  // Recent detections list
  let histUrl = `/api/history?cam_id=${S.focusCam}&limit=30`;
  if (from) histUrl += `&from=${from}`;
  if (to) histUrl += `&to=${to}`;
  const hist = await api(histUrl).catch(() => []);
  const histEl = document.getElementById("history-list");
  if (!hist.length) {
    histEl.innerHTML = `<span class="no-data">No detections in range</span>`;
  } else {
    histEl.innerHTML = hist
      .map(
        (d) => `
      <div class="hist-item">
        <span class="hist-class">${d.class.toUpperCase()}</span>
        <span class="hist-conf">${Math.round(d.confidence * 100)}%</span>
        <span class="hist-time">${d.ts.slice(11, 19)}</span>
      </div>`,
      )
      .join("");
  }
}

// ─── Alerts ───────────────────────────────────────────────────────────────────
async function refreshAlerts() {
  const camFilter = document.getElementById("alert-filter-cam").value;
  let url = "/api/alerts?limit=100";
  if (camFilter) url += `&cam_id=${camFilter}`;
  const alerts = await api(url).catch(() => []);
  const list = document.getElementById("alert-list");
  if (!alerts.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">✓</span><p>NO ALERTS</p></div>`;
    return;
  }
  list.innerHTML = alerts
    .map((a) => {
      const t = new Date(a.timestamp).toLocaleString();
      const snap = a.snapshot
        ? `<img class="alert-snap" src="/api/alerts/snapshots/${a.snapshot}" onclick="window.open(this.src)" title="View">`
        : "";
      return `
      <div class="alert-item alert-item--${a.type.startsWith("detection") ? "detection" : "motion"}">
        <span class="alert-time">${t}</span>
        <span class="alert-cam">${a.cam_name}</span>
        <span class="alert-msg">${a.detail}</span>
        ${snap}
      </div>`;
    })
    .join("");
}

document
  .getElementById("alert-filter-cam")
  .addEventListener("change", refreshAlerts);

document
  .getElementById("btn-clear-alerts")
  .addEventListener("click", async () => {
    if (!confirm("Clear all alerts?")) return;
    await api("/api/alerts", { method: "DELETE" });
    toast("Alerts cleared");
    refreshAlerts();
  });

// ─── Settings UI ──────────────────────────────────────────────────────────────
async function loadSettingsUI() {
  const s = await api("/api/settings").catch(() => ({}));
  S.settings = s;

  // AI
  setToggle("toggle-ai", s.ai_enabled);
  setToggle("toggle-motion", s.motion_enabled);
  setToggle("toggle-snap", s.snapshot_on_alert);
  const mdEl = document.getElementById("set-ai-model");
  if (mdEl) mdEl.value = s.ai_model || "yolov8n.pt";
  setRangeAndLabel(
    "set-confidence",
    "set-confidence-val",
    Math.round((s.ai_confidence || 0.5) * 100),
    (v) => v + "%",
  );
  setInputVal("set-alert-classes", (s.alert_classes || []).join(", "));
  setInputVal("set-alert-cooldown", s.alert_cooldown || 30);

  // Motion / recording
  setRangeAndLabel(
    "set-motion-sens",
    "set-motion-val",
    s.motion_sensitivity || 25,
  );
  setRangeAndLabel("set-rec-fps", "set-rec-fps-val", s.recording_fps || 10);
  setInputVal("set-rec-max", s.recording_max_seconds || 60);
  setInputVal("set-server-name", s.server_name || "Phantom Eye");

  // Camera HW
  loadHWSettings(s);

  // AI status
  const status = await api("/api/status").catch(() => ({}));
  const aiEl = document.getElementById("ai-install-status");
  if (aiEl) {
    aiEl.textContent = status.ai_available
      ? "✓ Ultralytics/YOLO installed\n✓ AI detection available"
      : "✗ Not installed\n\nRun:\n  pip install ultralytics\nthen restart server.";
    aiEl.style.color = status.ai_available ? "var(--acc)" : "var(--acc3)";
  }

  // System info
  const sysEl = document.getElementById("sys-info");
  if (sysEl && status.uptime !== undefined) {
    const up = status.uptime;
    sysEl.textContent =
      `Server: ${status.server}\n` +
      `Cameras: ${status.cameras_online}/${status.cameras_total} online\n` +
      `Recording: ${status.cameras_recording || 0}\n` +
      `Plugins: ${status.plugins_count || 0}\n` +
      `Detections: ${status.detections_total || 0}\n` +
      `Alerts: ${status.alerts_total || 0}\n` +
      `Uptime: ${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m`;
  }
}

function loadHWSettings(s) {
  const hw = [
    ["hw-framesize", "cam_framesize", "select"],
    ["hw-quality", "cam_quality", "range", "hw-quality-val"],
    ["hw-special-effect", "cam_special_effect", "select"],
    ["hw-aec", "cam_aec", "toggle"],
    ["hw-aec2", "cam_aec2", "toggle"],
    ["hw-ae-level", "cam_ae_level", "range", "hw-ae-level-val"],
    ["hw-aec-value", "cam_aec_value", "range", "hw-aec-value-val"],
    ["hw-agc", "cam_agc", "toggle"],
    ["hw-agc-gain", "cam_agc_gain", "range", "hw-agc-gain-val"],
    ["hw-gainceiling", "cam_gainceiling", "range", "hw-gainceiling-val"],
    ["hw-brightness", "cam_brightness", "range", "hw-brightness-val"],
    ["hw-contrast", "cam_contrast", "range", "hw-contrast-val"],
    ["hw-saturation", "cam_saturation", "range", "hw-saturation-val"],
    ["hw-sharpness", "cam_sharpness", "range", "hw-sharpness-val"],
    ["hw-wb-mode", "cam_wb_mode", "select"],
    ["hw-awb", "cam_awb", "toggle"],
    ["hw-awb-gain", "cam_awb_gain", "toggle"],
    ["hw-denoise", "cam_denoise", "range", "hw-denoise-val"],
    ["hw-vflip", "cam_vflip", "toggle"],
    ["hw-hmirror", "cam_hmirror", "toggle"],
    ["hw-lenc", "cam_lenc", "toggle"],
    ["hw-raw-gma", "cam_raw_gma", "toggle"],
    ["hw-bpc", "cam_bpc", "toggle"],
    ["hw-wpc", "cam_wpc", "toggle"],
    ["hw-dcw", "cam_dcw", "toggle"],
  ];
  hw.forEach(([id, key, type, labelId]) => {
    const v = s[key];
    if (v === undefined) return;
    if (type === "toggle") {
      setToggle(id, !!v);
    } else if (type === "select") {
      const el = document.getElementById(id);
      if (el) el.value = v;
    } else {
      const el = document.getElementById(id);
      if (el) {
        el.value = v;
        if (labelId) document.getElementById(labelId).textContent = v;
      }
    }
  });
}

// Range live labels
[
  "set-confidence",
  "set-motion-sens",
  "set-rec-fps",
  "hw-quality",
  "hw-ae-level",
  "hw-aec-value",
  "hw-agc-gain",
  "hw-gainceiling",
  "hw-brightness",
  "hw-contrast",
  "hw-saturation",
  "hw-sharpness",
  "hw-denoise",
].forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("input", () => {
    const labelId =
      id === "set-confidence"
        ? "set-confidence-val"
        : id === "set-motion-sens"
          ? "set-motion-val"
          : id === "set-rec-fps"
            ? "set-rec-fps-val"
            : id + "-val";
    const lbl = document.getElementById(labelId);
    if (lbl)
      lbl.textContent = id === "set-confidence" ? el.value + "%" : el.value;
  });
});

// HW toggle bindings
const hwToggles = {
  "hw-aec": "cam_aec",
  "hw-aec2": "cam_aec2",
  "hw-agc": "cam_agc",
  "hw-awb": "cam_awb",
  "hw-awb-gain": "cam_awb_gain",
  "hw-vflip": "cam_vflip",
  "hw-hmirror": "cam_hmirror",
  "hw-lenc": "cam_lenc",
  "hw-raw-gma": "cam_raw_gma",
  "hw-bpc": "cam_bpc",
  "hw-wpc": "cam_wpc",
  "hw-dcw": "cam_dcw",
};
Object.entries(hwToggles).forEach(([id, key]) => {
  const el = document.getElementById(id);
  if (el)
    el.addEventListener("click", () => {
      const on = !el.classList.contains("on");
      el.classList.toggle("on", on);
      S.settings[key] = on ? 1 : 0;
    });
});

// ── Global HW settings push
document
  .getElementById("btn-push-global-hw")
  ?.addEventListener("click", async () => {
    const payload = collectHWSettings();
    const res = await api("/api/cameras/settings/global", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    toast(`Settings pushed to ${res.pushed_to} camera(s)`);
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  });

document.getElementById("btn-reset-hw")?.addEventListener("click", async () => {
  if (!confirm("Reset all camera HW settings to defaults?")) return;
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      cam_framesize: 8,
      cam_quality: 12,
      cam_brightness: 0,
      cam_contrast: 0,
      cam_saturation: 0,
      cam_sharpness: 0,
      cam_special_effect: 0,
      cam_vflip: 0,
      cam_hmirror: 0,
      cam_awb: 1,
      cam_aec: 1,
      cam_agc: 1,
      cam_lenc: 1,
      cam_wpc: 1,
      cam_raw_gma: 1,
      cam_dcw: 1,
    }),
  });
  loadSettingsUI();
  toast("HW settings reset");
});

function collectHWSettings() {
  const ids = {
    "hw-framesize": "cam_framesize",
    "hw-quality": "cam_quality",
    "hw-brightness": "cam_brightness",
    "hw-contrast": "cam_contrast",
    "hw-saturation": "cam_saturation",
    "hw-sharpness": "cam_sharpness",
    "hw-denoise": "cam_denoise",
    "hw-special-effect": "cam_special_effect",
    "hw-wb-mode": "cam_wb_mode",
    "hw-ae-level": "cam_ae_level",
    "hw-aec-value": "cam_aec_value",
    "hw-agc-gain": "cam_agc_gain",
    "hw-gainceiling": "cam_gainceiling",
  };
  const out = {};
  Object.entries(ids).forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (el) out[key] = Number(el.value);
  });
  Object.entries(hwToggles).forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (el) out[key] = el.classList.contains("on") ? 1 : 0;
  });
  return out;
}

// ── Global toggle bindings (ai / motion)
bindToggle("toggle-ai", async (on) => {
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({ ai_enabled: on }),
  });
  toast(`AI Detection ${on ? "ON" : "OFF"}`);
});
bindToggle("toggle-motion", async (on) => {
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({ motion_enabled: on }),
  });
  toast(`Motion Detection ${on ? "ON" : "OFF"}`);
});
bindToggle("toggle-snap", async (on) => {
  S.settings.snapshot_on_alert = on;
});

// ── Save all settings
document
  .getElementById("btn-save-settings")
  ?.addEventListener("click", async () => {
    const classes = (document.getElementById("set-alert-classes")?.value || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      ai_model: document.getElementById("set-ai-model")?.value,
      ai_confidence:
        parseInt(document.getElementById("set-confidence")?.value || 50) / 100,
      alert_classes: classes,
      alert_cooldown: parseInt(
        document.getElementById("set-alert-cooldown")?.value || 30,
      ),
      motion_sensitivity: parseInt(
        document.getElementById("set-motion-sens")?.value || 25,
      ),
      recording_fps: parseInt(
        document.getElementById("set-rec-fps")?.value || 10,
      ),
      recording_max_seconds: parseInt(
        document.getElementById("set-rec-max")?.value || 60,
      ),
      server_name: document.getElementById("set-server-name")?.value,
      snapshot_on_alert: document
        .getElementById("toggle-snap")
        ?.classList.contains("on"),
      ...collectHWSettings(),
    };
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    toast("Settings saved");
    loadSettingsUI();
  });

// ─── Plugins tab ──────────────────────────────────────────────────────────────
async function loadPluginsUI() {
  const plugins = await api("/api/plugins").catch(() => []);
  const el = document.getElementById("plugins-list");
  if (!plugins.length) {
    el.innerHTML = `<div class="empty-state"><span class="empty-icon">⊕</span>
      <p>NO PLUGINS LOADED</p>
      <p class="empty-sub">Place .py files in <code>server/plugins/</code> and restart.</p></div>`;
    return;
  }
  el.innerHTML = plugins
    .map(
      (p) => `
    <div class="plugin-card">
      <div class="plugin-icon">⊕</div>
      <div class="plugin-info">
        <div class="plugin-name">${p.name.toUpperCase()}</div>
        <div class="plugin-desc">${p.description || "No description"}</div>
        <div class="plugin-version">v${p.version}</div>
      </div>
      <span class="plugin-enabled">ACTIVE</span>
    </div>`,
    )
    .join("");
}

// ─── Recordings tab ───────────────────────────────────────────────────────────
document
  .getElementById("btn-refresh-recordings")
  ?.addEventListener("click", loadRecordingsUI);

async function loadRecordingsUI() {
  const recs = await api("/api/recordings").catch(() => []);
  const el = document.getElementById("recordings-list");
  if (!recs.length) {
    el.innerHTML = `<div class="empty-state"><span class="empty-icon">⏹</span><p>NO RECORDINGS</p></div>`;
    return;
  }
  el.innerHTML = recs
    .map(
      (r) => `
    <div class="recording-item">
      <span class="recording-cam">${r.cam_id}</span>
      <span class="recording-name">${r.filename}</span>
      <span class="recording-size">${r.size_mb} MB</span>
      <a href="/recordings/${r.filename}" download class="tool-btn" style="text-decoration:none">⬇ DL</a>
    </div>`,
    )
    .join("");
}

// ─── Add camera modal ─────────────────────────────────────────────────────────
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
    toast(`"${name}" added`);
    poll();
  });

// ─── Discover modal ───────────────────────────────────────────────────────────
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
    const resEl = document.getElementById("discover-results");
    resEl.classList.remove("hidden");
    resEl.innerHTML = `<div class="discover-item">Scanning ${subnet}.1–254…</div>`;
    const found = await api("/api/discover", {
      method: "POST",
      body: JSON.stringify({ subnet }),
    });
    if (!found.length) {
      resEl.innerHTML = `<div class="discover-item">No cameras found.</div>`;
      return;
    }
    resEl.innerHTML = found
      .map(
        (c) => `
    <div class="discover-item">
      <span>${c.name} — ${c.ip}</span>
      <button class="tool-btn" onclick="addDiscovered('${c.name}','${c.ip}')">ADD</button>
    </div>`,
      )
      .join("");
  });
async function addDiscovered(name, ip) {
  await api("/api/cameras", {
    method: "POST",
    body: JSON.stringify({ name, stream_url: `http://${ip}/stream` }),
  });
  toast(`Added: ${name}`);
  document.getElementById("modal-discover").classList.add("hidden");
  poll();
}

// ─── Polling ──────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const [cameras, status] = await Promise.all([
      api("/api/cameras"),
      api("/api/status"),
    ]);
    S.cameras = cameras;

    document.getElementById("stat-online").textContent = status.cameras_online;
    document.getElementById("stat-total").textContent = status.cameras_total;
    document.getElementById("ai-dot").className =
      `dot ${status.ai_enabled && status.ai_available ? "dot--cyan pulse" : "dot--off"}`;

    const badge = document.getElementById("alert-badge");
    if (status.alerts_total > 0) {
      badge.textContent = status.alerts_total;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }

    renderGrid(cameras);
    if (document.getElementById("view-focus").classList.contains("active"))
      renderFocusSidebar();

    // Update camera filter in alerts
    const sel = document.getElementById("alert-filter-cam");
    const existing = new Set([...sel.options].map((o) => o.value));
    cameras.forEach((c) => {
      if (!existing.has(c.id)) {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = c.name;
        sel.appendChild(opt);
      }
    });
  } catch (e) {
    console.warn("Poll error:", e);
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function setRangeAndLabel(rangeId, labelId, val, fmt = (v) => v) {
  const r = document.getElementById(rangeId);
  const l = document.getElementById(labelId);
  if (r) r.value = val;
  if (l) l.textContent = fmt(val);
}
function setInputVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  startClock();
  // Set default date range to today in history pickers
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 7 * 86400000)
    .toISOString()
    .slice(0, 10);
  document.getElementById("hist-from").value = weekAgo;
  document.getElementById("hist-to").value = today;

  await poll();
  setInterval(poll, 2500);
}

init();
