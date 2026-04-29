"""
PHANTOM EYE - Dashboard Backend v2.0
======================================
New in v2:
  - Camera hardware settings (global + per-camera override)
  - LED control per camera
  - Recording plugin (saves MP4 clips)
  - Detection history + stats with date range filtering
  - Plugin registry API endpoint
  - Full CORS support for all routes

Start:  python server.py
Deps:   pip install flask flask-cors requests ultralytics opencv-python-headless
"""

import os, json, time, threading, logging, re
from pathlib import Path
from datetime import datetime, date
from typing import Optional
import importlib, pkgutil

import cv2
import numpy as np
import requests
from flask import Flask, render_template, Response, jsonify, request, abort, send_from_directory
from flask_cors import CORS

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    YOLO = None

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("phantom")

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
SNAP_DIR    = DATA_DIR / "snapshots"
ALERT_DIR   = DATA_DIR / "alerts"
RECORD_DIR  = DATA_DIR / "recordings"
PLUGINS_DIR = BASE_DIR / "plugins"

for d in [DATA_DIR, SNAP_DIR, ALERT_DIR, RECORD_DIR, PLUGINS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Create empty __init__.py so plugins/ is a package
init_file = PLUGINS_DIR / "__init__.py"
if not init_file.exists():
    init_file.write_text("")

CAMERAS_FILE  = DATA_DIR / "cameras.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
ALERTS_FILE   = DATA_DIR / "alerts.json"
HISTORY_FILE  = DATA_DIR / "history.json"

# ─── Default settings ─────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    # AI
    "ai_enabled": False,
    "ai_model": "yolov8n.pt",
    "ai_confidence": 0.5,
    "ai_classes": [],
    "alert_classes": ["person", "car"],
    "alert_cooldown": 30,
    # Motion
    "motion_enabled": False,
    "motion_sensitivity": 25,
    # Recording
    "recording_enabled": False,
    "recording_fps": 10,
    "recording_max_seconds": 60,
    # Snapshot
    "snapshot_on_alert": True,
    # System
    "server_name": "Phantom Eye",
    # Global camera hardware defaults (pushed to all cameras unless overridden)
    "cam_framesize": 8,       # 8=VGA (640x480)
    "cam_quality": 12,        # JPEG quality 0=best 63=worst
    "cam_brightness": 0,
    "cam_contrast": 0,
    "cam_saturation": 0,
    "cam_sharpness": 0,
    "cam_denoise": 0,
    "cam_special_effect": 0,
    "cam_wb_mode": 0,
    "cam_awb": 1,
    "cam_awb_gain": 1,
    "cam_aec": 1,
    "cam_aec2": 0,
    "cam_ae_level": 0,
    "cam_aec_value": 300,
    "cam_agc": 1,
    "cam_agc_gain": 0,
    "cam_gainceiling": 0,
    "cam_bpc": 0,
    "cam_wpc": 1,
    "cam_raw_gma": 1,
    "cam_lenc": 1,
    "cam_vflip": 0,
    "cam_hmirror": 0,
    "cam_dcw": 1,
}

# ─── In-memory state ──────────────────────────────────────────────────────────
cameras: dict        = {}
settings: dict       = {}
yolo_model           = None
alert_history: list  = []
detection_history: list = []   # [{ts, cam_id, cam_name, class, confidence}]
plugin_registry: list = []
recording_threads: dict = {}   # {cam_id: RecordingThread}
state_lock = threading.Lock()
START_TIME = time.time()

# ─── Flask ────────────────────────────────────────────────────────────────────
app = Flask(__name__,
            template_folder="dashboard/templates",
            static_folder="dashboard/static")
CORS(app)


# ══════════════════════════════════════════════════════════════════════════════
# Persistence
# ══════════════════════════════════════════════════════════════════════════════

def _json_read(path: Path, default):
    if path.exists():
        try: return json.loads(path.read_text())
        except: pass
    return default

def _json_write(path: Path, data):
    path.write_text(json.dumps(data, indent=2))

def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(_json_read(SETTINGS_FILE, {}))
    return s

def save_settings():
    _json_write(SETTINGS_FILE, settings)

def load_cameras() -> dict:
    return _json_read(CAMERAS_FILE, {})

def save_cameras():
    skip = {"frame_cache", "prev_gray", "writer", "writer_lock"}
    export = {k: {kk: vv for kk, vv in v.items() if kk not in skip}
              for k, v in cameras.items()}
    _json_write(CAMERAS_FILE, export)

def load_alerts() -> list:
    return _json_read(ALERTS_FILE, [])

def save_alerts():
    _json_write(ALERTS_FILE, alert_history[-500:])

def load_history() -> list:
    return _json_read(HISTORY_FILE, [])

def save_history():
    _json_write(HISTORY_FILE, detection_history[-5000:])


# ══════════════════════════════════════════════════════════════════════════════
# Camera defaults
# ══════════════════════════════════════════════════════════════════════════════

def cam_defaults(cam_id: str, name: str, stream_url: str) -> dict:
    return {
        "id": cam_id,
        "name": name,
        "stream_url": stream_url,
        "base_url": _base_url(stream_url),
        "online": False,
        "last_seen": None,
        "detections": [],
        "motion": False,
        "led": False,
        "frame_cache": None,
        "prev_gray": None,
        "last_alert": {},
        # per-camera overrides (None = use global)
        "ai_enabled_override": None,
        "cam_settings_override": {},   # keys matching DEFAULT_SETTINGS cam_ prefix
        # recording state
        "recording": False,
        "writer": None,
        "writer_lock": threading.Lock(),
        "record_start": None,
        "record_frames": 0,
    }

def _base_url(stream_url: str) -> str:
    """Turn http://192.168.1.x/stream → http://192.168.1.x"""
    return stream_url.replace("/stream", "").rstrip("/")


# ══════════════════════════════════════════════════════════════════════════════
# Camera hardware control helpers
# ══════════════════════════════════════════════════════════════════════════════

def _cam_hw_settings(cam: dict) -> dict:
    """Merge global cam_ settings with per-camera overrides."""
    merged = {}
    for k, v in settings.items():
        if k.startswith("cam_"):
            hw_key = k[4:]          # strip "cam_" prefix
            merged[hw_key] = v
    merged.update(cam.get("cam_settings_override", {}))
    return merged

def push_cam_settings(cam_id: str, extra: dict = None):
    """Push hardware settings to ESP32-CAM via POST /settings."""
    cam = cameras.get(cam_id)
    if not cam or not cam.get("online"): return False
    base = cam.get("base_url", "")
    if not base: return False
    payload = _cam_hw_settings(cam)
    if extra:
        payload.update(extra)
    try:
        r = requests.post(f"{base}/settings", json=payload, timeout=3)
        return r.status_code == 200
    except Exception as e:
        log.warning(f"[{cam_id}] Settings push failed: {e}")
        return False

def push_led(cam_id: str, on: bool):
    cam = cameras.get(cam_id)
    if not cam: return False
    base = cam.get("base_url", "")
    try:
        r = requests.post(f"{base}/led", json={"on": on}, timeout=3)
        if r.status_code == 200:
            with state_lock:
                cam["led"] = on
        return r.status_code == 200
    except Exception as e:
        log.warning(f"[{cam_id}] LED push failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# YOLO
# ══════════════════════════════════════════════════════════════════════════════

def get_yolo():
    global yolo_model
    if yolo_model is None and YOLO_AVAILABLE:
        mp = settings.get("ai_model", "yolov8n.pt")
        log.info(f"Loading YOLO: {mp}")
        yolo_model = YOLO(mp)
    return yolo_model

def run_detection(frame_bytes: bytes) -> list:
    model = get_yolo()
    if not model: return []
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return []
    conf = settings.get("ai_confidence", 0.5)
    results = model(img, conf=conf, verbose=False)[0]
    out = []
    fc = settings.get("ai_classes", [])
    for box in results.boxes:
        cid = int(box.cls[0])
        cn  = model.names[cid]
        if fc and cn not in fc: continue
        x1,y1,x2,y2 = box.xyxy[0].tolist()
        out.append({"class": cn, "confidence": round(float(box.conf[0]),3),
                    "bbox": [int(x1),int(y1),int(x2),int(y2)]})
    return out

def draw_detections(frame_bytes: bytes, detections: list) -> bytes:
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return frame_bytes
    for det in detections:
        x1,y1,x2,y2 = det["bbox"]
        lbl = f"{det['class']} {det['confidence']:.0%}"
        cv2.rectangle(img,(x1,y1),(x2,y2),(0,255,136),2)
        cv2.putText(img, lbl, (x1, max(y1-8,0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,(0,255,136),2)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes()


# ══════════════════════════════════════════════════════════════════════════════
# Motion
# ══════════════════════════════════════════════════════════════════════════════

def detect_motion(cam: dict, frame_bytes: bytes) -> bool:
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return False
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),(21,21),0)
    if cam["prev_gray"] is None:
        cam["prev_gray"] = gray; return False
    delta = cv2.absdiff(cam["prev_gray"], gray)
    cam["prev_gray"] = gray
    thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
    return np.count_nonzero(thresh) > (settings.get("motion_sensitivity",25) * 100)


# ══════════════════════════════════════════════════════════════════════════════
# Recording
# ══════════════════════════════════════════════════════════════════════════════

def start_recording(cam_id: str):
    cam = cameras.get(cam_id)
    if not cam or cam["recording"]: return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(RECORD_DIR / f"{cam_id}_{ts}.mp4")
    fps = settings.get("recording_fps", 10)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    with cam["writer_lock"]:
        cam["writer"] = cv2.VideoWriter(path, fourcc, fps, (640, 480))
        cam["recording"] = True
        cam["record_start"] = time.time()
        cam["record_path"] = path
        cam["record_frames"] = 0
    log.info(f"[{cam_id}] Recording started: {path}")

def stop_recording(cam_id: str) -> Optional[str]:
    cam = cameras.get(cam_id)
    if not cam or not cam["recording"]: return None
    with cam["writer_lock"]:
        if cam["writer"]:
            cam["writer"].release()
            cam["writer"] = None
        cam["recording"] = False
        path = cam.get("record_path", "")
    log.info(f"[{cam_id}] Recording stopped")
    return path

def write_frame_to_recording(cam: dict, frame_bytes: bytes):
    if not cam["recording"]: return
    max_secs = settings.get("recording_max_seconds", 60)
    elapsed = time.time() - (cam["record_start"] or time.time())
    if elapsed > max_secs:
        stop_recording(cam["id"]); return
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return
    img = cv2.resize(img, (640, 480))
    with cam["writer_lock"]:
        if cam["writer"]:
            cam["writer"].write(img)
            cam["record_frames"] += 1


# ══════════════════════════════════════════════════════════════════════════════
# Alerts + history
# ══════════════════════════════════════════════════════════════════════════════

def fire_alert(cam_id: str, alert_type: str, detail: str,
               frame_bytes: Optional[bytes] = None):
    cam = cameras[cam_id]
    now = time.time()
    cooldown = settings.get("alert_cooldown", 30)
    if now - cam["last_alert"].get(alert_type, 0) < cooldown: return
    cam["last_alert"][alert_type] = now

    alert = {
        "id": f"alert_{int(now*1000)}",
        "cam_id": cam_id,
        "cam_name": cam["name"],
        "type": alert_type,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
        "snapshot": None,
    }
    if frame_bytes and settings.get("snapshot_on_alert", True):
        snap = f"{cam_id}_{alert['id']}.jpg"
        (ALERT_DIR / snap).write_bytes(frame_bytes)
        alert["snapshot"] = snap

    with state_lock:
        alert_history.append(alert)
    save_alerts()
    log.warning(f"ALERT [{cam_id}] {alert_type}: {detail}")
    for p in plugin_registry:
        try: p.on_alert(alert)
        except Exception as e: log.error(f"Plugin {p.name} error: {e}")

def record_detection(cam_id: str, cam_name: str, cls: str, conf: float):
    entry = {
        "ts": datetime.now().isoformat(),
        "cam_id": cam_id,
        "cam_name": cam_name,
        "class": cls,
        "confidence": round(conf, 3),
    }
    with state_lock:
        detection_history.append(entry)
    # async save every 50 entries
    if len(detection_history) % 50 == 0:
        threading.Thread(target=save_history, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
# Camera frame pipeline thread
# ══════════════════════════════════════════════════════════════════════════════

def camera_thread(cam_id: str):
    log.info(f"[{cam_id}] Thread started")
    AI_EVERY = 5

    while True:
        cam = cameras.get(cam_id)
        if not cam: break

        url = cam["stream_url"]
        frame_count = 0

        try:
            r = requests.get(url, stream=True, timeout=10)
            if r.status_code != 200:
                raise ConnectionError(f"HTTP {r.status_code}")

            with state_lock:
                cam["online"] = True
                cam["last_seen"] = datetime.now().isoformat()

            # Push hardware settings on connect
            push_cam_settings(cam_id)

            buf = b""
            for chunk in r.iter_content(chunk_size=4096):
                buf += chunk
                while True:
                    start = buf.find(b"\xff\xd8")
                    end   = buf.find(b"\xff\xd9", start + 2)
                    if start == -1 or end == -1: break
                    frame_bytes = buf[start:end+2]
                    buf = buf[end+2:]
                    frame_count += 1

                    # ── AI detection ──────────────────────────────────────────
                    ai_on = settings.get("ai_enabled", False)
                    ov = cam.get("ai_enabled_override")
                    if ov is not None: ai_on = ov

                    annotated = frame_bytes
                    detections = []

                    if ai_on and YOLO_AVAILABLE and frame_count % AI_EVERY == 0:
                        detections = run_detection(frame_bytes)
                        with state_lock:
                            cam["detections"] = detections
                        ac = settings.get("alert_classes", [])
                        for det in detections:
                            record_detection(cam_id, cam["name"],
                                             det["class"], det["confidence"])
                            if det["class"] in ac:
                                fire_alert(cam_id,
                                           f"detection_{det['class']}",
                                           f"{det['class']} detected "
                                           f"({det['confidence']:.0%})",
                                           frame_bytes)
                        if detections:
                            annotated = draw_detections(frame_bytes, detections)
                    else:
                        with state_lock:
                            cam["detections"] = []

                    # ── Motion ────────────────────────────────────────────────
                    if settings.get("motion_enabled", False):
                        motion = detect_motion(cam, frame_bytes)
                        with state_lock: cam["motion"] = motion
                        if motion:
                            fire_alert(cam_id, "motion", "Motion detected", frame_bytes)
                    else:
                        with state_lock: cam["motion"] = False

                    # ── Recording ─────────────────────────────────────────────
                    if cam["recording"]:
                        write_frame_to_recording(cam, annotated)

                    # ── Store frame ───────────────────────────────────────────
                    with state_lock:
                        cam["frame_cache"] = annotated
                        cam["last_seen"] = datetime.now().isoformat()

                    # ── Plugin hooks ──────────────────────────────────────────
                    for p in plugin_registry:
                        try: p.on_frame(cam_id, frame_bytes, detections)
                        except: pass

        except Exception as e:
            log.warning(f"[{cam_id}] Stream error: {e}")
            with state_lock:
                if cam_id in cameras:
                    cameras[cam_id]["online"] = False
                    cameras[cam_id]["frame_cache"] = None
                    cameras[cam_id]["detections"] = []

        time.sleep(3)


# ══════════════════════════════════════════════════════════════════════════════
# MJPEG proxy
# ══════════════════════════════════════════════════════════════════════════════

def _offline_jpeg() -> bytes:
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(img, "OFFLINE", (60, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,80,40), 3)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()

def generate_stream(cam_id: str):
    off = _offline_jpeg()
    while True:
        cam = cameras.get(cam_id)
        if not cam: break
        frame = cam.get("frame_cache") or off
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(1/15)


# ══════════════════════════════════════════════════════════════════════════════
# Plugin system
# ══════════════════════════════════════════════════════════════════════════════

class PhantomPlugin:
    name        = "unnamed"
    version     = "1.0"
    description = ""
    enabled     = True

    def on_alert(self, alert: dict): pass
    def on_frame(self, cam_id: str, frame_bytes: bytes, detections: list): pass
    def on_startup(self): pass

def register_plugin(plugin: PhantomPlugin):
    plugin_registry.append(plugin)
    try: plugin.on_startup()
    except: pass
    log.info(f"Plugin registered: {plugin.name} v{plugin.version}")

def autoload_plugins():
    """Auto-import all .py files in plugins/ directory."""
    import importlib.util
    for f in PLUGINS_DIR.glob("*.py"):
        if f.name.startswith("_"): continue
        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            log.info(f"Loaded plugin module: {f.name}")
        except Exception as e:
            log.error(f"Plugin load error {f.name}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# API Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html",
                           server_name=settings.get("server_name","Phantom Eye"))

# ── Cameras ───────────────────────────────────────────────────────────────────

@app.route("/api/cameras", methods=["GET"])
def api_cameras():
    with state_lock:
        out = []
        for cam in cameras.values():
            out.append({
                "id": cam["id"], "name": cam["name"],
                "stream_url": cam["stream_url"],
                "base_url": cam.get("base_url",""),
                "online": cam["online"], "last_seen": cam["last_seen"],
                "detections": cam["detections"], "motion": cam["motion"],
                "led": cam.get("led", False),
                "recording": cam.get("recording", False),
                "ai_enabled_override": cam.get("ai_enabled_override"),
                "cam_settings_override": cam.get("cam_settings_override", {}),
            })
    return jsonify(out)

@app.route("/api/cameras", methods=["POST"])
def api_add_camera():
    data = request.get_json()
    name = data.get("name","").strip()
    url  = data.get("stream_url","").strip()
    if not name or not url: abort(400, "name and stream_url required")
    cam_id = re.sub(r"[^a-z0-9_]","", name.lower().replace(" ","_")) or f"cam_{int(time.time())}"
    with state_lock:
        if cam_id in cameras: cam_id += f"_{int(time.time())}"
        cameras[cam_id] = cam_defaults(cam_id, name, url)
    save_cameras()
    threading.Thread(target=camera_thread, args=(cam_id,), daemon=True).start()
    log.info(f"Camera added: {name} ({cam_id})")
    return jsonify({"id": cam_id, "name": name}), 201

@app.route("/api/cameras/<cam_id>", methods=["DELETE"])
def api_delete_camera(cam_id):
    with state_lock:
        if cam_id not in cameras: abort(404)
        stop_recording(cam_id)
        del cameras[cam_id]
    save_cameras()
    return jsonify({"deleted": cam_id})

@app.route("/api/cameras/<cam_id>", methods=["PATCH"])
def api_update_camera(cam_id):
    with state_lock:
        if cam_id not in cameras: abort(404)
        data = request.get_json()
        cam = cameras[cam_id]
        for field in ("name","stream_url","ai_enabled_override"):
            if field in data: cam[field] = data[field]
        if "cam_settings_override" in data:
            cam["cam_settings_override"].update(data["cam_settings_override"])
        if "stream_url" in data:
            cam["base_url"] = _base_url(data["stream_url"])
    save_cameras()
    # Push updated settings to camera immediately if online
    if request.get_json().get("cam_settings_override"):
        threading.Thread(target=push_cam_settings, args=(cam_id,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/cameras/<cam_id>/led", methods=["POST"])
def api_led(cam_id):
    if cam_id not in cameras: abort(404)
    on = request.get_json().get("on", False)
    ok = push_led(cam_id, on)
    return jsonify({"ok": ok, "led": on})

@app.route("/api/cameras/<cam_id>/settings", methods=["POST"])
def api_cam_settings(cam_id):
    """Push settings to a specific camera immediately."""
    if cam_id not in cameras: abort(404)
    data = request.get_json()
    with state_lock:
        cameras[cam_id]["cam_settings_override"].update(data)
    save_cameras()
    ok = push_cam_settings(cam_id)
    return jsonify({"ok": ok})

@app.route("/api/cameras/settings/global", methods=["POST"])
def api_global_cam_settings():
    """Update global camera hardware defaults and push to ALL online cameras."""
    data = request.get_json()
    with state_lock:
        for k, v in data.items():
            if k.startswith("cam_"):
                settings[k] = v
    save_settings()
    pushed = 0
    for cam_id in list(cameras.keys()):
        if push_cam_settings(cam_id): pushed += 1
    return jsonify({"ok": True, "pushed_to": pushed})

@app.route("/api/cameras/<cam_id>/recording", methods=["POST"])
def api_recording(cam_id):
    if cam_id not in cameras: abort(404)
    action = request.get_json().get("action","start")
    if action == "start":
        start_recording(cam_id)
        return jsonify({"ok": True, "recording": True})
    else:
        path = stop_recording(cam_id)
        fname = Path(path).name if path else None
        return jsonify({"ok": True, "recording": False, "file": fname})

# ── Streams ───────────────────────────────────────────────────────────────────

@app.route("/stream/<cam_id>")
def proxy_stream(cam_id):
    if cam_id not in cameras: abort(404)
    return Response(generate_stream(cam_id),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/snapshot/<cam_id>")
def snapshot(cam_id):
    if cam_id not in cameras: abort(404)
    frame = cameras[cam_id].get("frame_cache") or _offline_jpeg()
    return Response(frame, mimetype="image/jpeg")

@app.route("/recordings/<filename>")
def serve_recording(filename):
    return send_from_directory(RECORD_DIR, filename)

# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(settings)

@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    global yolo_model
    data = request.get_json()
    settings.update(data)
    save_settings()
    if "ai_model" in data: yolo_model = None
    return jsonify({"ok": True})

# ── Alerts ────────────────────────────────────────────────────────────────────

@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    limit  = int(request.args.get("limit", 50))
    cam_f  = request.args.get("cam_id")
    type_f = request.args.get("type")
    data   = alert_history
    if cam_f:  data = [a for a in data if a["cam_id"] == cam_f]
    if type_f: data = [a for a in data if a["type"] == type_f]
    return jsonify(data[-limit:][::-1])

@app.route("/api/alerts", methods=["DELETE"])
def api_clear_alerts():
    alert_history.clear(); save_alerts()
    return jsonify({"ok": True})

@app.route("/api/alerts/snapshots/<filename>")
def alert_snapshot(filename):
    return send_from_directory(ALERT_DIR, filename)

# ── Detection history + stats ─────────────────────────────────────────────────

@app.route("/api/history", methods=["GET"])
def api_history():
    cam_id   = request.args.get("cam_id")
    cls      = request.args.get("class")
    date_from = request.args.get("from")   # ISO date string YYYY-MM-DD
    date_to   = request.args.get("to")
    limit    = int(request.args.get("limit", 200))

    data = detection_history
    if cam_id:    data = [d for d in data if d["cam_id"] == cam_id]
    if cls:       data = [d for d in data if d["class"] == cls]
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            data = [d for d in data if datetime.fromisoformat(d["ts"]) >= df]
        except: pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to + "T23:59:59")
            data = [d for d in data if datetime.fromisoformat(d["ts"]) <= dt]
        except: pass

    return jsonify(data[-limit:][::-1])

@app.route("/api/stats", methods=["GET"])
def api_stats():
    cam_id   = request.args.get("cam_id")
    date_from = request.args.get("from")
    date_to   = request.args.get("to")

    data = detection_history
    if cam_id: data = [d for d in data if d["cam_id"] == cam_id]
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            data = [d for d in data if datetime.fromisoformat(d["ts"]) >= df]
        except: pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to + "T23:59:59")
            data = [d for d in data if datetime.fromisoformat(d["ts"]) <= dt]
        except: pass

    # Class counts
    class_counts: dict = {}
    hourly: dict = {}
    for d in data:
        cls = d["class"]
        class_counts[cls] = class_counts.get(cls, 0) + 1
        hour = d["ts"][:13]   # "2024-01-15T14"
        hourly[hour] = hourly.get(hour, 0) + 1

    # Motion events from alerts
    motion_data = alert_history
    if cam_id: motion_data = [a for a in motion_data if a["cam_id"] == cam_id]
    motion_count = sum(1 for a in motion_data if a["type"] == "motion")

    return jsonify({
        "total_detections": len(data),
        "class_counts": class_counts,
        "motion_events": motion_count,
        "hourly": hourly,
        "date_range": {"from": date_from, "to": date_to},
    })

# ── System ────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify({
        "server": settings.get("server_name","Phantom Eye"),
        "cameras_total": len(cameras),
        "cameras_online": sum(1 for c in cameras.values() if c["online"]),
        "cameras_recording": sum(1 for c in cameras.values() if c.get("recording")),
        "ai_available": YOLO_AVAILABLE,
        "ai_enabled": settings.get("ai_enabled", False),
        "motion_enabled": settings.get("motion_enabled", False),
        "alerts_total": len(alert_history),
        "detections_total": len(detection_history),
        "uptime": int(time.time() - START_TIME),
        "time": datetime.now().isoformat(),
        "plugins_count": len(plugin_registry),
    })

@app.route("/api/plugins")
def api_plugins():
    return jsonify([{
        "name": p.name,
        "version": getattr(p,"version","?"),
        "description": getattr(p,"description",""),
        "enabled": getattr(p,"enabled", True),
    } for p in plugin_registry])

@app.route("/api/discover", methods=["POST"])
def api_discover():
    subnet = request.get_json().get("subnet","192.168.1")
    found  = []
    def probe(ip):
        try:
            r = requests.get(f"http://{ip}/status", timeout=1)
            if r.status_code == 200:
                found.append({"ip": ip, **r.json()})
        except: pass
    ts = [threading.Thread(target=probe, args=(f"{subnet}.{i}",), daemon=True)
          for i in range(1,255)]
    for t in ts: t.start()
    for t in ts: t.join(timeout=2)
    return jsonify(found)

@app.route("/api/recordings")
def api_recordings():
    files = sorted(RECORD_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonify([{
        "filename": f.name,
        "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        "cam_id": f.stem.rsplit("_",2)[0] if "_" in f.stem else f.stem,
    } for f in files[:50]])


# ══════════════════════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════════════════════

def startup():
    global settings, alert_history, detection_history
    settings = load_settings()
    save_settings()

    saved = load_cameras()
    for cam_id, cd in saved.items():
        cameras[cam_id] = cam_defaults(cam_id, cd.get("name",cam_id), cd.get("stream_url",""))
        cameras[cam_id]["base_url"] = _base_url(cd.get("stream_url",""))
        cameras[cam_id]["ai_enabled_override"] = cd.get("ai_enabled_override")
        cameras[cam_id]["cam_settings_override"] = cd.get("cam_settings_override", {})
        threading.Thread(target=camera_thread, args=(cam_id,), daemon=True).start()

    alert_history     = load_alerts()
    detection_history = load_history()

    autoload_plugins()
    log.info(f"Phantom Eye v2 started. {len(cameras)} camera(s), {len(plugin_registry)} plugin(s).")

if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
