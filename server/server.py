"""
PHANTOM EYE - Dashboard Backend
================================
Flask backend serving the security dashboard.
Handles camera registry, MJPEG proxying, AI detection (YOLO), alerts, and plugins.

Start:
    python server.py

Requirements:
    pip install flask flask-cors requests ultralytics opencv-python-headless
"""

import os
import json
import time
import threading
import logging
import base64
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
import requests
from flask import (Flask, render_template, Response, jsonify,
                   request, abort, send_from_directory)
from flask_cors import CORS

# ─── Optional YOLO import ────────────────────────────────────────────────────
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    YOLO = None

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger("phantom")

# ─── Config ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
SNAP_DIR   = DATA_DIR / "snapshots"
ALERT_DIR  = DATA_DIR / "alerts"

for d in [DATA_DIR, SNAP_DIR, ALERT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CAMERAS_FILE = DATA_DIR / "cameras.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
ALERTS_FILE   = DATA_DIR / "alerts.json"

DEFAULT_SETTINGS = {
    "ai_enabled": False,
    "ai_model": "yolov8n.pt",
    "ai_confidence": 0.5,
    "ai_classes": [],          # empty = all classes
    "alert_classes": ["person", "car"],
    "alert_cooldown": 30,      # seconds between repeated alerts
    "motion_enabled": False,
    "motion_sensitivity": 25,
    "snapshot_on_alert": True,
    "server_name": "Phantom Eye",
}

# ─── In-memory state ─────────────────────────────────────────────────────────
cameras: dict = {}       # {cam_id: {url, name, online, detections, ...}}
settings: dict = {}
yolo_model = None        # loaded on demand
alert_history: list = [] # recent alerts
plugin_registry: list = []  # for future plugin system

state_lock = threading.Lock()

# ─── Flask app ────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="dashboard/templates",
            static_folder="dashboard/static")
CORS(app)


# ─────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_cameras() -> dict:
    if CAMERAS_FILE.exists():
        return json.loads(CAMERAS_FILE.read_text())
    return {}

def save_cameras():
    export = {k: {kk: vv for kk, vv in v.items()
                  if kk not in ("frame_cache",)}
              for k, v in cameras.items()}
    CAMERAS_FILE.write_text(json.dumps(export, indent=2))

def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        s.update(json.loads(SETTINGS_FILE.read_text()))
    return s

def save_settings():
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))

def load_alerts() -> list:
    if ALERTS_FILE.exists():
        return json.loads(ALERTS_FILE.read_text())
    return []

def save_alerts():
    ALERTS_FILE.write_text(json.dumps(alert_history[-500:], indent=2))  # keep last 500


# ─────────────────────────────────────────────────────────────────────────────
# Camera state initializer
# ─────────────────────────────────────────────────────────────────────────────

def cam_defaults(cam_id: str, name: str, stream_url: str) -> dict:
    return {
        "id": cam_id,
        "name": name,
        "stream_url": stream_url,
        "online": False,
        "last_seen": None,
        "detections": [],
        "motion": False,
        "frame_cache": None,     # latest raw JPEG bytes
        "prev_gray": None,       # for motion detection
        "last_alert": {},        # {class: timestamp}
        "ai_enabled_override": None,  # per-cam override
    }


# ─────────────────────────────────────────────────────────────────────────────
# YOLO loader
# ─────────────────────────────────────────────────────────────────────────────

def get_yolo():
    global yolo_model
    if yolo_model is None and YOLO_AVAILABLE:
        model_path = settings.get("ai_model", "yolov8n.pt")
        log.info(f"Loading YOLO model: {model_path}")
        yolo_model = YOLO(model_path)
    return yolo_model


# ─────────────────────────────────────────────────────────────────────────────
# AI detection
# ─────────────────────────────────────────────────────────────────────────────

def run_detection(cam_id: str, frame_bytes: bytes) -> list:
    """Run YOLO on a JPEG frame. Returns list of detection dicts."""
    model = get_yolo()
    if model is None:
        return []

    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    conf = settings.get("ai_confidence", 0.5)
    results = model(img, conf=conf, verbose=False)[0]

    detections = []
    filter_classes = settings.get("ai_classes", [])

    for box in results.boxes:
        cls_id = int(box.cls[0])
        cls_name = model.names[cls_id]
        if filter_classes and cls_name not in filter_classes:
            continue
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        detections.append({
            "class": cls_name,
            "confidence": round(float(box.conf[0]), 3),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
        })

    return detections


def draw_detections(frame_bytes: bytes, detections: list) -> bytes:
    """Draw bounding boxes on JPEG frame, return new JPEG bytes."""
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return frame_bytes

    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        label = f"{det['class']} {det['confidence']:.0%}"
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 136), 2)
        cv2.putText(img, label, (x1, max(y1 - 8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 136), 2)

    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes()


# ─────────────────────────────────────────────────────────────────────────────
# Motion detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_motion(cam_id: str, frame_bytes: bytes) -> bool:
    cam = cameras[cam_id]
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if cam["prev_gray"] is None:
        cam["prev_gray"] = gray
        return False

    delta = cv2.absdiff(cam["prev_gray"], gray)
    cam["prev_gray"] = gray
    thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
    motion_score = np.count_nonzero(thresh)
    sensitivity = settings.get("motion_sensitivity", 25)
    return motion_score > (sensitivity * 100)


# ─────────────────────────────────────────────────────────────────────────────
# Alerting
# ─────────────────────────────────────────────────────────────────────────────

def fire_alert(cam_id: str, alert_type: str, detail: str,
               frame_bytes: Optional[bytes] = None):
    cam = cameras[cam_id]
    now = time.time()
    cooldown = settings.get("alert_cooldown", 30)

    last = cam["last_alert"].get(alert_type, 0)
    if now - last < cooldown:
        return  # cooldown active

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
        snap_name = f"{cam_id}_{alert['id']}.jpg"
        (ALERT_DIR / snap_name).write_bytes(frame_bytes)
        alert["snapshot"] = snap_name

    with state_lock:
        alert_history.append(alert)
    save_alerts()

    log.warning(f"ALERT [{cam_id}] {alert_type}: {detail}")

    # ── Plugin hooks ──────────────────────────────────────────────────────────
    for plugin in plugin_registry:
        try:
            plugin.on_alert(alert)
        except Exception as e:
            log.error(f"Plugin error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Frame pipeline (per-camera background thread)
# ─────────────────────────────────────────────────────────────────────────────

def camera_thread(cam_id: str):
    """Continuously fetch frames from ESP32-CAM MJPEG stream."""
    log.info(f"[{cam_id}] Thread started")
    AI_EVERY = 5   # run detection every N frames (performance)

    while True:
        cam = cameras.get(cam_id)
        if not cam:
            break

        url = cam["stream_url"]
        frame_count = 0

        try:
            r = requests.get(url, stream=True, timeout=10)
            if r.status_code != 200:
                raise ConnectionError(f"HTTP {r.status_code}")

            with state_lock:
                cam["online"] = True
                cam["last_seen"] = datetime.now().isoformat()

            boundary = b""
            buf = b""

            for chunk in r.iter_content(chunk_size=4096):
                buf += chunk
                # Parse MJPEG multipart
                while True:
                    # Find JPEG start/end markers
                    start = buf.find(b"\xff\xd8")
                    end   = buf.find(b"\xff\xd9", start + 2)
                    if start == -1 or end == -1:
                        break

                    frame_bytes = buf[start:end + 2]
                    buf = buf[end + 2:]
                    frame_count += 1

                    # ── AI detection ──────────────────────────────────────────
                    ai_on = settings.get("ai_enabled", False)
                    ai_override = cam.get("ai_enabled_override")
                    if ai_override is not None:
                        ai_on = ai_override

                    if ai_on and frame_count % AI_EVERY == 0:
                        detections = run_detection(cam_id, frame_bytes)
                        with state_lock:
                            cam["detections"] = detections

                        # Check for alert classes
                        alert_classes = settings.get("alert_classes", [])
                        for det in detections:
                            if det["class"] in alert_classes:
                                fire_alert(cam_id, f"detection_{det['class']}",
                                           f"{det['class']} detected ({det['confidence']:.0%})",
                                           frame_bytes)

                        if detections and ai_on:
                            frame_bytes = draw_detections(frame_bytes, detections)
                    else:
                        with state_lock:
                            cam["detections"] = []

                    # ── Motion detection ──────────────────────────────────────
                    if settings.get("motion_enabled", False):
                        motion = detect_motion(cam_id, frame_bytes)
                        with state_lock:
                            cam["motion"] = motion
                        if motion:
                            fire_alert(cam_id, "motion",
                                       "Motion detected", frame_bytes)

                    # Store latest frame
                    with state_lock:
                        cam["frame_cache"] = frame_bytes
                        cam["last_seen"] = datetime.now().isoformat()

        except Exception as e:
            log.warning(f"[{cam_id}] Stream error: {e}")
            with state_lock:
                if cam_id in cameras:
                    cameras[cam_id]["online"] = False
                    cameras[cam_id]["frame_cache"] = None
                    cameras[cam_id]["detections"] = []

        time.sleep(3)  # retry delay


# ─────────────────────────────────────────────────────────────────────────────
# Proxy stream to browser (MJPEG)
# ─────────────────────────────────────────────────────────────────────────────

def generate_stream(cam_id: str):
    while True:
        cam = cameras.get(cam_id)
        if not cam:
            break

        frame = cam.get("frame_cache")
        if frame:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        else:
            # Serve offline placeholder
            placeholder = _offline_jpeg()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + placeholder + b"\r\n")

        time.sleep(1 / 15)  # ~15 fps to browser


def _offline_jpeg() -> bytes:
    """Generate a small 'OFFLINE' JPEG placeholder."""
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(img, "OFFLINE", (80, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 80, 40), 3)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


# ─────────────────────────────────────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
                           server_name=settings.get("server_name", "Phantom Eye"))


# ── Camera CRUD ──────────────────────────────────────────────────────────────

@app.route("/api/cameras", methods=["GET"])
def api_cameras():
    with state_lock:
        export = []
        for cam_id, cam in cameras.items():
            export.append({
                "id": cam_id,
                "name": cam["name"],
                "stream_url": cam["stream_url"],
                "online": cam["online"],
                "last_seen": cam["last_seen"],
                "detections": cam["detections"],
                "motion": cam["motion"],
                "ai_enabled_override": cam.get("ai_enabled_override"),
            })
    return jsonify(export)


@app.route("/api/cameras", methods=["POST"])
def api_add_camera():
    data = request.get_json()
    name = data.get("name", "").strip()
    stream_url = data.get("stream_url", "").strip()
    if not name or not stream_url:
        abort(400, "name and stream_url required")

    cam_id = re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))
    if not cam_id:
        cam_id = f"cam_{int(time.time())}"

    with state_lock:
        if cam_id in cameras:
            cam_id += f"_{int(time.time())}"
        cameras[cam_id] = cam_defaults(cam_id, name, stream_url)

    save_cameras()
    t = threading.Thread(target=camera_thread, args=(cam_id,),
                          daemon=True, name=f"cam-{cam_id}")
    t.start()

    log.info(f"Camera added: {name} ({cam_id})")
    return jsonify({"id": cam_id, "name": name}), 201


@app.route("/api/cameras/<cam_id>", methods=["DELETE"])
def api_delete_camera(cam_id):
    with state_lock:
        if cam_id not in cameras:
            abort(404)
        del cameras[cam_id]
    save_cameras()
    return jsonify({"deleted": cam_id})


@app.route("/api/cameras/<cam_id>", methods=["PATCH"])
def api_update_camera(cam_id):
    with state_lock:
        if cam_id not in cameras:
            abort(404)
        data = request.get_json()
        if "name" in data:
            cameras[cam_id]["name"] = data["name"]
        if "stream_url" in data:
            cameras[cam_id]["stream_url"] = data["stream_url"]
        if "ai_enabled_override" in data:
            cameras[cam_id]["ai_enabled_override"] = data["ai_enabled_override"]
    save_cameras()
    return jsonify({"ok": True})


# ── Video stream proxy ────────────────────────────────────────────────────────

@app.route("/stream/<cam_id>")
def proxy_stream(cam_id):
    if cam_id not in cameras:
        abort(404)
    return Response(generate_stream(cam_id),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshot/<cam_id>")
def snapshot(cam_id):
    if cam_id not in cameras:
        abort(404)
    frame = cameras[cam_id].get("frame_cache")
    if not frame:
        frame = _offline_jpeg()
    return Response(frame, mimetype="image/jpeg")


# ── Settings ─────────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    global yolo_model
    data = request.get_json()
    settings.update(data)
    save_settings()

    # Reload YOLO if model changed
    if "ai_model" in data:
        yolo_model = None

    return jsonify({"ok": True})


# ── Alerts ───────────────────────────────────────────────────────────────────

@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    limit = int(request.args.get("limit", 50))
    return jsonify(alert_history[-limit:][::-1])


@app.route("/api/alerts", methods=["DELETE"])
def api_clear_alerts():
    alert_history.clear()
    save_alerts()
    return jsonify({"ok": True})


@app.route("/api/alerts/snapshots/<filename>")
def alert_snapshot(filename):
    return send_from_directory(ALERT_DIR, filename)


# ── System status ─────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify({
        "server": settings.get("server_name", "Phantom Eye"),
        "cameras_total": len(cameras),
        "cameras_online": sum(1 for c in cameras.values() if c["online"]),
        "ai_available": YOLO_AVAILABLE,
        "ai_enabled": settings.get("ai_enabled", False),
        "motion_enabled": settings.get("motion_enabled", False),
        "alerts_total": len(alert_history),
        "uptime": int(time.time() - START_TIME),
        "time": datetime.now().isoformat(),
    })


# ── Camera auto-discovery (mDNS scan) ─────────────────────────────────────────
# Cameras broadcast as <name>.local — scan is optional, user can add manually.

@app.route("/api/discover", methods=["POST"])
def api_discover():
    """Ping common ESP32-CAM IPs on local subnet to find cameras."""
    import socket
    subnet = request.get_json().get("subnet", "192.168.1")
    found = []

    def probe(ip):
        try:
            r = requests.get(f"http://{ip}/status", timeout=1)
            if r.status_code == 200:
                info = r.json()
                found.append({"ip": ip, **info})
        except Exception:
            pass

    threads = []
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        t = threading.Thread(target=probe, args=(ip,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=2)

    return jsonify(found)


# ─────────────────────────────────────────────────────────────────────────────
# Plugin interface (for future expansion)
# ─────────────────────────────────────────────────────────────────────────────

class PhantomPlugin:
    """Subclass this to add custom integrations."""
    name = "unnamed"

    def on_alert(self, alert: dict):
        pass

    def on_frame(self, cam_id: str, frame_bytes: bytes):
        pass


def register_plugin(plugin: PhantomPlugin):
    plugin_registry.append(plugin)
    log.info(f"Plugin registered: {plugin.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────

START_TIME = time.time()

def startup():
    global settings, cameras

    settings = load_settings()
    save_settings()

    # Load saved cameras and start their threads
    saved = load_cameras()
    for cam_id, cam_data in saved.items():
        cameras[cam_id] = cam_defaults(cam_id,
                                        cam_data.get("name", cam_id),
                                        cam_data.get("stream_url", ""))
        if cam_data.get("ai_enabled_override") is not None:
            cameras[cam_id]["ai_enabled_override"] = cam_data["ai_enabled_override"]
        t = threading.Thread(target=camera_thread, args=(cam_id,),
                              daemon=True, name=f"cam-{cam_id}")
        t.start()

    global alert_history
    alert_history = load_alerts()
    log.info(f"Phantom Eye started. {len(cameras)} camera(s) loaded.")


if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
