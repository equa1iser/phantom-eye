# CLAUDE.md — Phantom Eye Project

## Standing Rule

**After every set of changes, update both `README.md` and `CLAUDE.md` to reflect what changed.**
- README.md: user-facing — deployment steps, new features, updated file structure, troubleshooting
- CLAUDE.md: agent-facing — architecture notes, active patterns, constraints, what to avoid

---

## Behavioral Guidelines

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

---

## Project Architecture

### Overview

Phantom Eye is a self-hosted home security system:
- **ESP32-CAM boards** stream MJPEG video over WiFi
- **Python/Flask server** (`server/server.py`) proxies streams, runs AI detection, manages alerts
- **Dashboard** (`server/dashboard/`) — single-page React-style UI served by Flask
- **SigNoz** — self-hosted observability (traces, metrics, logs) via OpenTelemetry

### Deployment (Docker — preferred)

```bash
cp .env.example .env
docker-compose up -d
```

- Phantom Eye dashboard: `http://localhost:5000`
- SigNoz UI: `http://localhost:3301` (login: `admin@signoz.io` / `password`)

Bare-metal (development only): `cd server && python server.py`

### Key Files

| File | Purpose |
|------|---------|
| `esp32/phantom_cam/phantom_cam.ino` | ESP32-CAM Arduino firmware |
| `server/server.py` | Flask backend — 22 routes, camera threads, AI/motion pipeline |
| `server/otel.py` | OpenTelemetry SDK setup (traces, metrics, logs → SigNoz) |
| `server/dashboard/static/js/dashboard.js` | Frontend JS — polling, camera grid, focus view, LED control |
| `server/dashboard/templates/index.html` | Dashboard HTML |
| `server/plugins/` | Drop-in plugin directory (auto-loaded on startup) |
| `Dockerfile` | Phantom Eye container (Python 3.11-slim) |
| `docker-compose.yml` | Full stack: SigNoz (zookeeper, clickhouse, otel-collector, query-service, frontend) + phantom-eye |
| `docker/otel-collector-config.yaml` | OTLP receiver → ClickHouse exporters pipeline |
| `.env.example` | OTEL endpoint template — copy to `.env` before `docker-compose up` |

### Server Threading Model

- **Main thread**: Flask HTTP server
- **One thread per camera**: `camera_thread(cam_id)` — MJPEG parsing, AI inference (every 5th frame), motion detection, recording, plugin hooks
- **Lock**: `state_lock` (threading.Lock) protects `cameras`, `alert_history`, `detection_history`
- **Writer lock**: per-camera `writer_lock` for VideoWriter access

### OpenTelemetry Instrumentation

Auto-instrumented (no spans needed):
- All Flask routes → `FlaskInstrumentor`
- All `requests` library calls → `RequestsInstrumentor` (covers push_cam_settings, push_led, discovery)
- Python `logging` module → `LoggingInstrumentor`

Manual spans in `server.py`:
- `camera.stream_connect` — each connection attempt to an ESP32
- `ai.inference` — YOLO inference run (every 5th frame when AI enabled)
- `alert.pipeline` — includes cooldown suppression tracking
- `recording.start` / `recording.stop`

Custom metrics:
- `phantom.frames.processed`, `phantom.frames.processing_ms` (per camera)
- `phantom.detections.total` (per camera + class)
- `phantom.ai.inference_ms`
- `phantom.motion.events`, `phantom.alerts.fired`, `phantom.alerts.suppressed`, `phantom.stream.errors`
- `phantom.cameras.online`, `phantom.cameras.total` (observable gauges)

OTEL is import-safe: if packages are absent (bare-metal dev), `setup_otel()` returns `(None, None)` and all `if tracer:` guards no-op.

### ESP32 Firmware Patterns

- LED pin: GPIO4 (flash LED). Controlled via `POST /led` or `POST /settings` with `led` key.
- WiFi reconnect: `loop()` checks `WiFi.status()` every 5 seconds and calls `WiFi.reconnect()`.
- Stream stability: `handleStream()` checks `client.write()` return value and breaks on 0; calls `delay(1)` each frame to yield to WiFi stack.
- LED state sync: server queries `GET /status` on every (re)connect to sync `cam["led"]` with actual ESP32 state.

### LED Button Behaviour

Server state is authoritative for LED:
- `push_led()` updates `cam["led"]` in memory **first**, then attempts the ESP32 HTTP call. The call may silently fail if the camera is offline — server state still updates.
- `api_led` always returns `{"ok": true}` — the UI button always toggles regardless of camera reachability.
- LED state is persisted to `cameras.json` via `save_cameras()` after every toggle, so it survives server restarts.
- On camera (re)connect, `camera_thread` pushes the server-side LED state TO the camera (instead of pulling from it). Server state is the source of truth.

`renderFocusSidebar()` syncs the button on every poll tick from `S.cameras`, which reflects the server-side `cam.led`.

### Plugin System

Drop a `.py` file in `server/plugins/`. It's auto-loaded at startup.

```python
from server import PhantomPlugin, register_plugin

class MyPlugin(PhantomPlugin):
    name = "my-plugin"
    def on_alert(self, alert: dict): ...
    def on_frame(self, cam_id: str, frame_bytes: bytes, detections: list): ...
    def on_startup(self): ...

register_plugin(MyPlugin())
```

### Data Persistence

All runtime data lives under `server/data/` (volume-mounted in Docker):
- `cameras.json` — camera list + per-camera overrides
- `settings.json` — global settings + hardware defaults
- `alerts.json` — last 500 alerts
- `history.json` — last 5000 detections
- `snapshots/` — alert JPEG snapshots
- `recordings/` — MP4 clips

---

## Active Constraints

- **Never commit `.env`** — it's gitignored. `.env.example` is the committed template.
- **YOLO is excluded from the default Docker image** — build with `--build-arg YOLO=true` if needed.
- **ClickHouse uses the `default` user with no password** — internal Docker network only; do not add credentials to connection strings.
- **Do not trace every frame** — use metrics (counters/histograms) for per-frame data. Spans only for connection events, AI inference runs, alert pipeline, and recording lifecycle.
- **ESP32 is 2.4GHz only** — never suggest 5GHz WiFi configs.
- **`server/data/` is gitignored** — never suggest committing runtime data files.
- **SigNoz stack versions (pinned, working)**: `signoz/zookeeper:3.7.1`, `clickhouse/clickhouse-server:25.5.6`, `signoz/signoz-otel-collector:v0.144.4`, `signoz/signoz:v0.124.0`. Do not use `:latest` tags — they break silently across major versions.
- **SigNoz is now a single `signoz` service** — the old split of query-service + frontend + alertmanager is gone. One container, port 8080 internally (mapped to 3301).
- **Schema migrator must run first** — `signoz-schema-migrator` (uses the otel-collector image with `migrate bootstrap/sync up/async up`) creates all ClickHouse tables. Other services `depends_on: service_completed_successfully`.
- **ClickHouse config goes in `config.d/` and `users.d/`** — never mount to `/etc/clickhouse-server/config.xml` directly in 25.x; it replaces the full default config and breaks startup. Use `config.d/overrides.xml` and `users.d/custom.xml` instead.
- **FlaskInstrumentor two-phase pattern** — `FlaskInstrumentor().instrument()` in `otel.py` is the complete registration. Do NOT also call `instrument_app(app)` in `server.py` — it causes double-instrumentation warnings.
- **AI/Motion toggles sync from poll()** — `poll()` calls `setToggle("toggle-ai", status.ai_enabled)` and `setToggle("toggle-motion", status.motion_enabled)` every 2.5s. Do NOT rely on initial HTML state for these toggles; the server state is authoritative.
- **bindToggle uses parent label** — the click listener is attached to `toggle.closest("label") || toggle` so the full toggle-group label area is clickable, not just the knob.
- **Date inputs in focus sidebar** — stacked vertically (`flex-direction: column`) to prevent the native date picker popup from overflowing the right edge of the screen.