# ◈ PHANTOM EYE — Complete Setup Guide

> A modular home security system with ESP32-CAM cameras, a Python/Flask dashboard, AI object detection (YOLO), full observability via SigNoz, and an expandable plugin architecture.

---

## Table of Contents

1. [Project Overview](#overview)
2. [What You Need (Hardware & Software)](#requirements)
3. [Step 1 — Deploy with Docker (Recommended)](#step-1-docker)
4. [Step 2 — Flash Your ESP32-CAM Boards](#step-2)
5. [Step 3 — Add Cameras to the Dashboard](#step-3)
6. [Step 4 — Enable AI Detection (Optional)](#step-4)
7. [Step 5 — Alerts & Motion Detection](#step-5)
8. [Step 6 — Observability with SigNoz](#step-6)
9. [Bare-Metal Setup (Development)](#bare-metal)
10. [File Structure Reference](#file-structure)
11. [Adding New Features (Plugin Guide)](#plugins)
12. [Troubleshooting](#troubleshooting)
13. [Future Expansion Ideas](#expansion)

---

## 1. Project Overview {#overview}

```
  ┌─────────────────┐         WiFi          ┌──────────────────────────────┐
  │  ESP32-CAM #1   │ ──────────────────────► │                              │
  │  (Front Door)   │                        │   Home Server / Docker Host  │
  └─────────────────┘                        │                              │
                                             │  ┌────────────────────────┐  │
  ┌─────────────────┐         WiFi           │  │  Phantom Eye (Flask)   │  │
  │  ESP32-CAM #2   │ ──────────────────────► │  │  Dashboard  :5000      │  │
  │  (Back Yard)    │                        │  │  AI Detection          │  │
  └─────────────────┘                        │  │  Motion Alerts         │  │
                                             │  └────────────────────────┘  │
  ┌─────────────────┐                        │  ┌────────────────────────┐  │
  │  Any Browser    │ ◄── http://host:5000   │  │  SigNoz  :3301         │  │
  │  (phone/laptop) │                        │  │  Traces / Metrics / Log│  │
  └─────────────────┘                        │  └────────────────────────┘  │
                                             └──────────────────────────────┘
```

Each ESP32-CAM streams live MJPEG video over WiFi. The server proxies those
streams to the dashboard and optionally runs YOLO AI detection on each frame.
SigNoz provides full visibility into stream health, detection rates, and alert
volume through OpenTelemetry traces, metrics, and logs.

---

## 2. What You Need {#requirements}

### Hardware
- One or more **AI Thinker ESP32-CAM** boards (~$8-12 each)
- A **USB-to-Serial adapter** (FTDI or CH340, ~$5) — used once per board to flash firmware
- Jumper wires (3-4 short ones)
- A server machine (Windows, macOS, or Linux) to run Docker

### Software
- **Docker Desktop** (preferred) — from docker.com
- Arduino IDE 2.x — from arduino.cc (for building ESP32 firmware)
- Python 3.9+ (only if running bare-metal instead of Docker)

---

## 3. Step 1 — Deploy with Docker (Recommended) {#step-1-docker}

Docker brings up the complete stack — Phantom Eye dashboard + SigNoz observability — in a single command.

### A. Install Docker Desktop

Download and install from https://docker.com/products/docker-desktop

### B. Clone or copy the project

```bash
git clone <your-repo-url> phantom-eye
cd phantom-eye
```

### C. Create your environment file

```bash
cp .env.example .env
```

The defaults work out of the box. Edit `.env` only if you need to change the service name or endpoint.

### D. Start everything

```bash
docker-compose up -d
```

Allow 60-90 seconds on first run for ClickHouse (SigNoz's database) to initialise.

### E. Access the services

| Service | URL | Notes |
|---------|-----|-------|
| Phantom Eye dashboard | `http://localhost:5000` | Add cameras here |
| SigNoz UI | `http://localhost:3301` | Traces, metrics, logs |

SigNoz first-run login: `admin@signoz.io` / `password`

### F. Find your server IP (for flashing cameras)

```cmd
# Windows
ipconfig
# Look for "IPv4 Address" — e.g. 192.168.1.105

# Linux/macOS
hostname -I
```

### G. Stop / restart

```bash
docker-compose down       # stop (data persists)
docker-compose down -v    # stop and wipe ALL data (including SigNoz history)
docker-compose up -d      # start again
```

### H. Update after code changes

```bash
docker-compose up -d --build phantom-eye
```

---

## 4. Step 2 — Flash Your ESP32-CAM Boards {#step-2}

You need to do this once per camera board. After flashing, the board connects to your WiFi and streams automatically.

### A. Install Arduino IDE

1. Download from https://arduino.cc/en/software and install

### B. Add ESP32 board support

1. Open Arduino IDE → **File → Preferences**
2. In "Additional boards manager URLs" add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Click OK → **Tools → Board → Boards Manager** → search "esp32" → Install **esp32 by Espressif Systems**

### C. Install required libraries

In Arduino IDE → **Tools → Manage Libraries**, install:
- `ArduinoJson` by Benoit Blanchon

### D. Wire the ESP32-CAM for flashing

The ESP32-CAM doesn't have a USB port — flash it via a USB-to-Serial adapter:

```
ESP32-CAM    →    USB-Serial Adapter
─────────────────────────────────────
5V           →    5V (or VCC)
GND          →    GND
U0R (RX)     →    TX
U0T (TX)     →    RX
IO0          →    GND  ← FLASH PIN (connect only during flash)
```

⚠️ **IO0→GND** puts the board in flash mode. Connect it before pressing Reset, disconnect after flashing.

### E. Use the Phantom Eye Flasher Tool

```bash
pip install esptool pyserial
python tools/flasher.py
```

1. Plug in the ESP32-CAM via USB-Serial adapter (IO0 connected to GND)
2. Select the COM port
3. Fill in: Camera Name, WiFi SSID/password, and your server IP
4. Press RESET on the board → click **FLASH CAMERA**
5. After upload: disconnect IO0 from GND and press RESET

### F. First boot

After flashing the camera will:
1. Connect to your WiFi
2. Be reachable at `http://CAMERA-IP/stream`

**If WiFi fails** the board creates a setup hotspot:
- Network: `PhantomEye-Setup` / Password: `phantom123`
- Connect and open `http://192.168.4.1` to configure manually

> **Note:** ESP32 is **2.4GHz only**. It cannot connect to 5GHz WiFi networks.

### G. Find the camera's IP

Check your router's admin panel for a device named "esp32-cam", or open the Arduino serial monitor at 115200 baud immediately after boot.

---

## 5. Step 3 — Add Cameras to the Dashboard {#step-3}

1. Open `http://localhost:5000` (or `http://YOUR-SERVER-IP:5000`)
2. Click **+ ADD CAMERA**
3. Enter camera name and stream URL: `http://CAMERA-IP/stream`
4. Click **ADD CAMERA**

The live stream appears in the grid immediately.

### Auto-Discovery

1. Click **⊙ AUTO-DISCOVER**
2. Enter your subnet (e.g., `192.168.1`)
3. Click **SCAN NETWORK** — any Phantom Eye cameras found appear with an ADD button

---

## 6. Step 4 — Enable AI Detection (Optional) {#step-4}

AI detection uses YOLOv8 to identify people, cars, animals, and 80+ other objects.

### Enable YOLO in Docker

Rebuild the image with the YOLO build arg:

```bash
docker-compose build --build-arg YOLO=true phantom-eye
docker-compose up -d phantom-eye
```

This adds ~500MB to the image. On first detection run it downloads the model (~6MB for nano).

### Enable YOLO in bare-metal

```bash
pip install ultralytics
```

### Configure in the dashboard

1. Click **CONFIG** tab → set **Model** (Nano is fastest)
2. Set **Alert on classes** (e.g., `person, car`)
3. Click **SAVE SETTINGS**
4. Toggle **AI DETECT** ON in the toolbar

### Performance notes

| Model | Speed | Accuracy | RAM |
|-------|-------|----------|-----|
| yolov8n.pt | Fast (~15fps on CPU) | Good | ~200MB |
| yolov8s.pt | Medium | Better | ~400MB |
| yolov8m.pt | Slow on old hardware | Best | ~800MB |

Detection runs on every 5th frame by default. Change `AI_EVERY = 5` in `server/server.py` to adjust.

---

## 7. Step 5 — Alerts & Motion Detection {#step-5}

### AI Alerts

Triggered when a detected class matches your alert list.
- Configure in **CONFIG → Alert on classes**
- Set cooldown to prevent spam (default: 30 seconds)
- Snapshots are saved automatically when an alert fires

### Motion Detection

Pure pixel-difference (no AI needed):
1. Toggle **MOTION** in the toolbar
2. Adjust sensitivity in CONFIG

### View Alerts

Click **⚠ ALERTS** in the nav — each alert shows timestamp, camera name, type, and snapshot.

---

## 8. Step 6 — Observability with SigNoz {#step-6}

SigNoz is included in the Docker Compose stack. No extra setup required — it starts automatically with `docker-compose up -d`.

### What's instrumented

**Traces** (visible in SigNoz → Traces):
- All 22 HTTP API routes (auto — Flask instrumentation)
- All outbound calls to ESP32s — push_cam_settings, push_led, status sync, discovery probes (auto — requests instrumentation)
- Camera stream connection attempts per camera (`camera.stream_connect`)
- YOLO AI inference runs — every 5th frame (`ai.inference`)
- Alert pipeline including cooldown suppression (`alert.pipeline`)
- Recording start/stop

**Metrics** (visible in SigNoz → Dashboards):

| Metric | Type | Description |
|--------|------|-------------|
| `phantom.cameras.online` | Gauge | Cameras currently streaming |
| `phantom.cameras.total` | Gauge | Total registered cameras |
| `phantom.frames.processed` | Counter | Frames processed per camera |
| `phantom.frames.processing_ms` | Histogram | Frame pipeline latency |
| `phantom.detections.total` | Counter | Detections by camera + class |
| `phantom.ai.inference_ms` | Histogram | YOLO inference latency |
| `phantom.motion.events` | Counter | Motion events per camera |
| `phantom.alerts.fired` | Counter | Alerts fired by type |
| `phantom.alerts.suppressed` | Counter | Cooldown-suppressed alerts |
| `phantom.stream.errors` | Counter | Stream connection errors |

**Logs** (visible in SigNoz → Logs):
- All server `log.info/warning/error` calls forwarded automatically with `trace_id` and `span_id` injected when inside a span.

### Verify data is flowing

1. Open SigNoz at `http://localhost:3301`
2. Go to **Services** — `phantom-eye` should appear within 30 seconds
3. Add a camera, then check **Traces** for `GET /api/cameras` spans
4. Check **Logs** and filter `service.name = phantom-eye`

---

## 9. Bare-Metal Setup (Development) {#bare-metal}

Use this only for local development — Docker is preferred for production.

### Linux/macOS

```bash
cd server
bash setup_server.sh
```

### Windows (manual)

```cmd
cd server
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

> When running bare-metal, OTEL packages are still installed but SigNoz won't be reachable. The server detects this gracefully and runs without telemetry — no errors.

---

## 10. File Structure {#file-structure}

```
phantom-eye/
│
├── Dockerfile                        ← Phantom Eye container image
├── docker-compose.yml                ← Full stack (SigNoz + phantom-eye)
├── .env.example                      ← OTEL config template (copy to .env)
├── .gitignore
│
├── docker/
│   └── otel-collector-config.yaml   ← OTLP → ClickHouse pipeline config
│
├── esp32/
│   └── phantom_cam/
│       └── phantom_cam.ino           ← ESP32 firmware
│           • WiFi auto-reconnect (5s retry loop)
│           • Stream write-failure detection
│           • LED state exposed in /status
│
├── tools/
│   └── flasher.py                    ← GUI flasher for ESP32 boards
│
└── server/
    ├── server.py                     ← Flask backend (22 routes, camera threads)
    ├── otel.py                       ← OpenTelemetry SDK setup
    ├── requirements.txt              ← Python deps incl. OTEL packages
    ├── setup_server.sh               ← Bare-metal setup script
    ├── data/                         ← Runtime data (gitignored, volume-mounted)
    │   ├── cameras.json
    │   ├── settings.json
    │   ├── alerts.json
    │   ├── history.json
    │   ├── snapshots/
    │   └── recordings/
    ├── plugins/
    │   └── telegram_alerts.py        ← Example plugin
    └── dashboard/
        ├── templates/
        │   └── index.html
        └── static/
            ├── css/dashboard.css
            └── js/dashboard.js       ← Camera grid, LED control, polling
```

---

## 11. Adding New Features (Plugin Guide) {#plugins}

Drop a `.py` file in `server/plugins/` — it's auto-loaded at startup.

```python
# server/plugins/my_plugin.py
from server import PhantomPlugin, register_plugin

class MyPlugin(PhantomPlugin):
    name = "my-plugin"
    version = "1.0"
    description = "Does something useful"

    def on_alert(self, alert: dict):
        # Called whenever an alert fires
        pass

    def on_frame(self, cam_id: str, frame_bytes: bytes, detections: list):
        # Called for every processed frame
        pass

    def on_startup(self):
        # Called once when server starts
        pass

register_plugin(MyPlugin())
```

### Example: Telegram alerts

```python
import requests
from server import PhantomPlugin, register_plugin

class TelegramPlugin(PhantomPlugin):
    name = "telegram"
    BOT_TOKEN = "YOUR_BOT_TOKEN"
    CHAT_ID   = "YOUR_CHAT_ID"

    def on_alert(self, alert):
        requests.post(
            f"https://api.telegram.org/bot{self.BOT_TOKEN}/sendMessage",
            json={"chat_id": self.CHAT_ID, "text": f"Alert: {alert['detail']}"}
        )

register_plugin(TelegramPlugin())
```

---

## 12. Troubleshooting {#troubleshooting}

### Camera shows "OFFLINE" / connects then disconnects

- Verify the stream URL opens in a browser: `http://CAMERA-IP/stream`
- Check the camera and server are on the same WiFi network
- The firmware now retries WiFi every 5 seconds — give it 10-15 seconds after a router restart
- Check SigNoz → Metrics → `phantom.stream.errors` to see if errors are spiking on a specific camera

### Camera briefly connects then drops

This was a known firmware bug (write failures weren't detected, WiFi stack was starved). Fixed in the current firmware:
- `handleStream()` now checks `client.write()` return value and exits immediately on failure
- `loop()` now calls `WiFi.reconnect()` every 5 seconds when disconnected

Reflash with the latest `phantom_cam.ino` if you're still seeing this.

### LED button doesn't work or turns on unexpectedly

Fixed in the current release:
- The button now updates immediately on click (no longer waits for next poll)
- Stale LED state after a camera reboot is corrected — the server reads `/status` from the ESP32 on every reconnect and syncs the actual LED state
- A failed LED command (camera offline) now shows an error toast instead of silently failing

### Camera won't connect to WiFi

- Double-check SSID/password (case sensitive)
- ESP32 is **2.4GHz only** — it cannot connect to 5GHz networks
- Try the setup portal: connect to `PhantomEye-Setup` hotspot → `http://192.168.4.1`

### Flash fails ("Could not connect to device")

- Make sure IO0 is connected to GND
- Press RESET right before clicking upload
- Try a different USB cable (some are charge-only)
- Make sure no other program is using the COM port

### AI detection is very slow

- Switch to `yolov8n.pt` (nano) in CONFIG
- Detection runs every 5th frame. Change `AI_EVERY = 5` in `server/server.py`

### Port 5000 already in use

Change the port in `docker-compose.yml`:
```yaml
ports:
  - "5001:5000"
```

### SigNoz not showing data

- Allow 60-90 seconds after `docker-compose up -d` for ClickHouse to initialise
- Check collector logs: `docker-compose logs otel-collector`
- Verify phantom-eye is sending: `docker-compose logs phantom-eye | grep otel`
- If running bare-metal, set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` in your shell

### Multiple cameras lag

- Each camera runs in its own thread
- Reduce `jpeg_quality` in the ESP32 firmware (higher number = lower quality = smaller frames)
- Disable AI on cameras you don't need it on (⋮ menu → "Toggle AI for this cam")

---

## 13. Future Expansion Ideas {#expansion}

| Feature | Effort | Notes |
|---------|--------|-------|
| Doorbell button | Low | GPIO on ESP32 triggers alert |
| Mobile app | Medium | Flutter app consuming the REST API |
| Face recognition | Medium | Replace YOLO with face_recognition lib |
| License plate reader | Medium | Add second YOLO model (LPD) |
| Home automation | Low | Plugin: call Home Assistant webhook on alert |
| VPN access | Low | Tailscale on server = secure remote access |
| Backup power | Hardware | UPS on server + PoE ESP32-CAM variant |
| SigNoz alert rules | Low | Configure alerting rules in SigNoz UI for camera going offline |
| Custom dashboards | Low | Build Phantom Eye metric dashboards in SigNoz |

---

*Phantom Eye is designed to be fully offline — no cloud, no subscriptions, no data leaving your home network.*
