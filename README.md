# ◈ PHANTOM EYE — Complete Setup Guide

> A modular home security system with ESP32-CAM cameras, a Python/Flask dashboard, AI object detection (YOLO), and an expandable plugin architecture.

---

## Table of Contents

1. [Project Overview](#overview)
2. [What You Need (Hardware & Software)](#requirements)
3. [Step 1 — Set Up Your Home Server Laptop](#step-1)
4. [Step 2 — Flash Your ESP32-CAM Boards](#step-2)
5. [Step 3 — Add Cameras to the Dashboard](#step-3)
6. [Step 4 — Enable AI Detection (Optional)](#step-4)
7. [Step 5 — Alerts & Motion Detection](#step-5)
8. [File Structure Reference](#file-structure)
9. [Adding New Features (Plugin Guide)](#plugins)
10. [Troubleshooting](#troubleshooting)
11. [Future Expansion Ideas](#expansion)

---

## 1. Project Overview {#overview}

```
  ┌─────────────────┐         WiFi          ┌──────────────────────────┐
  │  ESP32-CAM #1   │ ──────────────────────► │                          │
  │  (Front Door)   │                        │   Home Server Laptop     │
  └─────────────────┘                        │   (Python Flask)         │
                                             │                          │
  ┌─────────────────┐         WiFi          │   ┌──────────────────┐   │
  │  ESP32-CAM #2   │ ──────────────────────► │   │ Dashboard UI     │   │
  │  (Back Yard)    │                        │   │ AI Detection     │   │
  └─────────────────┘                        │   │ Motion Alerts    │   │
                                             │   └──────────────────┘   │
  ┌─────────────────┐                        └──────────────┬───────────┘
  │  Any Browser    │ ◄────── http://server-ip:5000 ────────┘
  │  (phone/laptop) │
  └─────────────────┘
```

Each ESP32-CAM streams live MJPEG video over WiFi. The server proxies those
streams to the dashboard and optionally runs YOLO AI detection on each frame.

---

## 2. What You Need {#requirements}

### Hardware
- One or more **AI Thinker ESP32-CAM** boards (~$8-12 each on Amazon/AliExpress)
- A **USB-to-Serial adapter** (FTDI or CH340, ~$5) — used once per board to flash firmware
- Jumper wires (3-4 short ones)
- A laptop to use as your home server (any OS: Windows, macOS, Linux)

### Software
- Python 3.9+ (free, from python.org)
- Arduino IDE 2.x (free, from arduino.cc) — for building ESP32 firmware
- The Phantom Eye files from this package

---

## 3. Step 1 — Set Up Your Home Server Laptop {#step-1}

This laptop will run 24/7 and serve the dashboard to any browser on your network.

### A. Install Python

**Windows:**
1. Go to https://python.org/downloads
2. Download Python 3.11 (or newer)
3. Run installer — **check "Add Python to PATH"**
4. Click Install

**macOS:**
```bash
# Install Homebrew first if you don't have it:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python3
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv -y
```

### B. Copy the server files

Copy the entire `server/` folder to the laptop. You can put it anywhere,
for example: `C:\phantom-eye\` or `/home/yourname/phantom-eye/`

### C. Run the setup script

**Linux/macOS:**
```bash
cd /path/to/phantom-eye/server
bash setup_server.sh
```

The script will:
- Create a Python virtual environment
- Install all dependencies
- Optionally install YOLO AI detection
- Create a systemd service so the server starts on boot (Linux only)

**Windows (manual steps):**
```cmd
cd C:\phantom-eye\server
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### D. Start the server

```bash
# Linux/macOS:
source venv/bin/activate
python server.py

# Windows:
venv\Scripts\activate
python server.py
```

You should see:
```
[INFO] Phantom Eye started. 0 camera(s) loaded.
* Running on http://0.0.0.0:5000
```

### E. Note your server's IP address

You'll need this when flashing cameras.

**Linux/macOS:**
```bash
hostname -I        # Linux
ipconfig getifaddr en0   # macOS
```

**Windows:**
```cmd
ipconfig
# Look for "IPv4 Address" under your WiFi adapter
# Example: 192.168.1.105
```

### F. Open the dashboard

On any device on your home network, go to:
```
http://YOUR-SERVER-IP:5000
```
Example: `http://192.168.1.105:5000`

---

## 4. Step 2 — Flash Your ESP32-CAM Boards {#step-2}

You need to do this once per camera board. After flashing, the board
connects to your WiFi and streams automatically.

### A. Install Arduino IDE

1. Download from https://arduino.cc/en/software
2. Install it
3. Open Arduino IDE

### B. Add ESP32 board support

1. Open Arduino IDE → **File → Preferences**
2. In "Additional boards manager URLs" add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Click OK
4. Go to **Tools → Board → Boards Manager**
5. Search "esp32" → Install **esp32 by Espressif Systems** (takes 2-3 minutes)

### C. Install required libraries

In Arduino IDE → **Tools → Manage Libraries**, install:
- `ArduinoJson` by Benoit Blanchon

### D. Wire the ESP32-CAM for flashing

The ESP32-CAM doesn't have a USB port. You flash it using a USB-to-Serial adapter.

```
ESP32-CAM    →    USB-Serial Adapter
─────────────────────────────────────
5V           →    5V (or VCC)
GND          →    GND
U0R (RX)     →    TX
U0T (TX)     →    RX
IO0          →    GND  ← THIS IS THE FLASH PIN (connect only during flash)
```

⚠️ **Important:** The IO0→GND connection puts it in flash mode. Connect it
before pressing Reset, and disconnect it after flashing.

### E. Use the Phantom Eye Flasher Tool (Easiest Method)

The flasher tool in `tools/flasher.py` provides a simple GUI:

```bash
pip install esptool pyserial
python tools/flasher.py
```

1. Plug in the ESP32-CAM via USB-Serial adapter
2. Make sure IO0 is connected to GND
3. Select the COM port
4. Fill in:
   - Camera Name (e.g., "FrontDoor")
   - Your WiFi SSID and password
   - Your server's IP address
5. Press the RESET button on the board
6. Click **FLASH CAMERA**
7. After upload, disconnect IO0 from GND and press RESET

### F. First boot — camera connects automatically

After flashing, the camera will:
1. Try to connect to your WiFi
2. If successful, it broadcasts on your network
3. Its stream will be at: `http://CAMERA-IP/stream`

**If it can't find your WiFi**, it creates its own hotspot:
- Network: `PhantomEye-Setup`
- Password: `phantom123`
- Connect to it and go to `http://192.168.4.1` to configure manually

### G. Find the camera's IP address

Once connected, check your router's admin panel for a device called
"esp32-cam" or check the Arduino serial monitor at 115200 baud.

---

## 5. Step 3 — Add Cameras to the Dashboard {#step-3}

1. Open the dashboard: `http://YOUR-SERVER-IP:5000`
2. Click **+ ADD CAMERA**
3. Enter the camera name and stream URL: `http://CAMERA-IP/stream`
4. Click **ADD CAMERA**

The live stream appears in the grid immediately.

### Auto-Discovery

If you don't know the camera IPs:
1. Click **⊙ AUTO-DISCOVER**
2. Enter your subnet (e.g., `192.168.1`)
3. Click **SCAN NETWORK**
4. Any Phantom Eye cameras found will appear — click ADD

---

## 6. Step 4 — Enable AI Detection {#step-4}

AI detection uses YOLOv8 to identify people, cars, animals, and 80+ other
objects in real time.

### Install Ultralytics

```bash
# On your server laptop, with venv activated:
pip install ultralytics
```

This downloads ~70MB. On first use, it also downloads the model (~6MB for nano).

### Enable in the dashboard

1. Click **CONFIG** tab
2. Set **Model** (Nano is fastest, Medium is most accurate)
3. Set **Alert on classes** (e.g., `person, car`)
4. Click **SAVE SETTINGS**
5. Toggle **AI DETECT** to ON in the toolbar

### Per-camera control

Right-click any camera cell (⋮ menu) → "Toggle AI for this cam"
This overrides the global AI setting for just that camera.

### Performance notes

| Model | Speed | Accuracy | RAM |
|-------|-------|----------|-----|
| yolov8n.pt | Fast (~15fps on CPU) | Good | ~200MB |
| yolov8s.pt | Medium | Better | ~400MB |
| yolov8m.pt | Slow on old hardware | Best | ~800MB |

On an old laptop, use `yolov8n.pt` (nano). The system runs detection on
every 5th frame by default to reduce CPU load.

---

## 7. Step 5 — Alerts & Motion Detection {#step-5}

### AI Alerts

Automatically triggered when a detected class matches your alert list.
- Configure classes in **CONFIG → Alert on classes**
- Set cooldown to prevent spam (default: 30 seconds)
- Snapshots are saved automatically when an alert fires

### Motion Detection

Pure pixel-difference based (no AI needed):
1. Toggle **MOTION** in the toolbar
2. Adjust sensitivity in CONFIG
3. Higher sensitivity = detects smaller movements

### View Alerts

Click **⚠ ALERTS** in the top nav. Each alert shows:
- Timestamp and camera name
- Detection type and detail
- Thumbnail snapshot (if enabled)

---

## 8. File Structure {#file-structure}

```
phantom-eye/
├── esp32/
│   └── phantom_cam/
│       └── phantom_cam.ino     ← ESP32 firmware (Arduino sketch)
│
├── tools/
│   └── flasher.py              ← GUI flasher tool for ESP32 boards
│
└── server/
    ├── server.py               ← Main Flask backend
    ├── requirements.txt        ← Python dependencies
    ├── setup_server.sh         ← One-click server setup script
    ├── data/                   ← Auto-created: cameras.json, alerts, snapshots
    └── dashboard/
        ├── templates/
        │   └── index.html      ← Dashboard HTML
        └── static/
            ├── css/
            │   └── dashboard.css
            └── js/
                └── dashboard.js
```

---

## 9. Adding New Features (Plugin Guide) {#plugins}

The server has a plugin system. To add a new feature, create a Python file
in `server/plugins/` that subclasses `PhantomPlugin`:

### Example: Telegram alert notifications

```python
# server/plugins/telegram_alerts.py
import requests
from server import PhantomPlugin, register_plugin

class TelegramPlugin(PhantomPlugin):
    name = "telegram"
    BOT_TOKEN = "YOUR_BOT_TOKEN"
    CHAT_ID   = "YOUR_CHAT_ID"

    def on_alert(self, alert):
        msg = f"🚨 {alert['cam_name']}: {alert['detail']}"
        requests.post(
            f"https://api.telegram.org/bot{self.BOT_TOKEN}/sendMessage",
            json={"chat_id": self.CHAT_ID, "text": msg}
        )

register_plugin(TelegramPlugin())
```

Then import it at the bottom of `server.py`:
```python
from plugins.telegram_alerts import *
```

### Other expansion ideas

- **Email alerts** — use Python's smtplib
- **Recording** — save MJPEG streams to MP4 using OpenCV VideoWriter
- **Two-factor auth** — add Flask-Login for dashboard password protection
- **Nightvision mode** — adjust ESP32 sensor settings via the `/status` endpoint
- **PTZ control** — add servo control to the ESP32 firmware and a joystick to the dashboard
- **Multiple users** — add user accounts with different camera permissions
- **Cloud backup** — sync alert snapshots to S3/Dropbox

---

## 10. Troubleshooting {#troubleshooting}

### Camera won't connect to WiFi
- Double-check SSID/password (case sensitive)
- Make sure your router supports 2.4GHz — ESP32 does NOT support 5GHz
- Try the setup portal: connect to `PhantomEye-Setup` hotspot

### Camera shows "OFFLINE" in dashboard
- Make sure the camera and server are on the same WiFi network
- Verify the stream URL is correct: try it in a browser
- Check the server logs for connection errors

### Flash fails ("Could not connect to device")
- Make sure IO0 is connected to GND
- Press RESET right before clicking upload
- Try a different USB cable (some are charge-only)
- Make sure no other program is using the COM port

### AI detection is very slow
- Switch to `yolov8n.pt` (nano model) in CONFIG
- The system processes every 5th frame. You can change `AI_EVERY = 5` in server.py

### "Port already in use" error
- Another process is using port 5000
- Change the port: `app.run(port=5001)` in server.py, or kill the other process

### Multiple cameras lag
- Each camera runs in its own thread
- On low-RAM machines, reduce `jpeg_quality` in the ESP32 firmware (higher number = lower quality/smaller frames)
- Disable AI on cameras you don't need it on

---

## 11. Future Expansion Ideas {#expansion}

The architecture is designed to grow. Here's what's easy to add:

| Feature | Effort | Notes |
|---------|--------|-------|
| Door bell button | Low | GPIO on ESP32 triggers alert |
| Recording clips | Medium | OpenCV VideoWriter in server.py |
| Mobile app | Medium | Flutter app consuming the REST API |
| Face recognition | Medium | Replace YOLO with face_recognition lib |
| License plates | Medium | Add a second YOLO model (LPD) |
| Home automation | Low | Plugin: call Home Assistant webhook on alert |
| VPN access | Low | Tailscale on server = secure remote access |
| Backup power | Hardware | UPS on server + PoE ESP32-CAM |

---

*Phantom Eye is designed to be fully offline — no cloud, no subscriptions, no data leaving your home network.*
