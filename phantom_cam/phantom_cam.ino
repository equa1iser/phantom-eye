/*
 * PHANTOM EYE - ESP32-CAM Firmware
 * ================================
 * Drop this onto any ESP32-CAM board using the Phantom Eye Flasher tool.
 * The camera will auto-connect to your WiFi and stream MJPEG to the dashboard.
 *
 * Board: AI Thinker ESP32-CAM (or compatible)
 * Flash Mode: QIO, 4MB, 80MHz
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <EEPROM.h>
#include <ArduinoJson.h>

// ── Camera pin map (AI Thinker module) ──────────────────────────────────────
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define LED_GPIO_NUM       4   // Onboard flash LED

// ── EEPROM layout ────────────────────────────────────────────────────────────
#define EEPROM_SIZE       256
#define ADDR_MAGIC         0   // 2 bytes: 0xBE, 0xEF = config valid
#define ADDR_SSID          2   // 64 bytes
#define ADDR_PASS         66   // 64 bytes
#define ADDR_CAM_NAME    130   // 32 bytes
#define ADDR_DASH_IP     162   // 32 bytes
#define ADDR_DASH_PORT   194   // 2 bytes (uint16)
#define MAGIC_BYTE1     0xBE
#define MAGIC_BYTE2     0xEF

// ── AP mode config (used when no WiFi is configured) ─────────────────────────
#define AP_SSID   "PhantomEye-Setup"
#define AP_PASS   "phantom123"
#define AP_IP     IPAddress(192, 168, 4, 1)

// ── Globals ──────────────────────────────────────────────────────────────────
WebServer server(80);
bool configMode = false;
String camName  = "Front-Door";
String dashIP   = "192.168.0.83";
uint16_t dashPort = 5000;

// ─────────────────────────────────────────────────────────────────────────────
// EEPROM helpers
// ─────────────────────────────────────────────────────────────────────────────
void writeString(int addr, const String& s, int maxLen) {
  int len = min((int)s.length(), maxLen - 1);
  for (int i = 0; i < len; i++) EEPROM.write(addr + i, s[i]);
  EEPROM.write(addr + len, 0);
}

String readString(int addr, int maxLen) {
  String s = "";
  for (int i = 0; i < maxLen; i++) {
    char c = EEPROM.read(addr + i);
    if (c == 0) break;
    s += c;
  }
  return s;
}

bool configValid() {
  return (EEPROM.read(ADDR_MAGIC) == MAGIC_BYTE1 &&
          EEPROM.read(ADDR_MAGIC + 1) == MAGIC_BYTE2);
}

void saveConfig(const String& ssid, const String& pass,
                const String& name, const String& ip, uint16_t port) {
  EEPROM.write(ADDR_MAGIC,     MAGIC_BYTE1);
  EEPROM.write(ADDR_MAGIC + 1, MAGIC_BYTE2);
  writeString(ADDR_SSID,     ssid, 64);
  writeString(ADDR_PASS,     pass, 64);
  writeString(ADDR_CAM_NAME, name, 32);
  writeString(ADDR_DASH_IP,  ip,   32);
  EEPROM.write(ADDR_DASH_PORT,     port & 0xFF);
  EEPROM.write(ADDR_DASH_PORT + 1, (port >> 8) & 0xFF);
  EEPROM.commit();
}

void loadConfig(String& ssid, String& pass) {
  ssid    = readString(ADDR_SSID,     64);
  pass    = readString(ADDR_PASS,     64);
  camName = readString(ADDR_CAM_NAME, 32);
  dashIP  = readString(ADDR_DASH_IP,  32);
  dashPort = EEPROM.read(ADDR_DASH_PORT) |
             (EEPROM.read(ADDR_DASH_PORT + 1) << 8);
  if (camName.length() == 0) camName = "CAM-1";
  if (dashPort == 0 || dashPort == 0xFFFF) dashPort = 5000;
}

// ─────────────────────────────────────────────────────────────────────────────
// Camera init
// ─────────────────────────────────────────────────────────────────────────────
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_VGA;   // 640x480
  config.jpeg_quality = 12;              // 0=best, 63=worst
  config.fb_count     = 2;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  s->set_vflip(s, 0);
  s->set_hmirror(s, 0);
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// MJPEG stream handler
// ─────────────────────────────────────────────────────────────────────────────
void handleStream() {
  WiFiClient client = server.client();
  String response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
  client.print(response);

  while (client.connected()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { delay(10); continue; }

    client.printf("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n", fb->len);
    client.write(fb->buf, fb->len);
    client.print("\r\n");
    esp_camera_fb_return(fb);

    if (!client.connected()) break;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Single JPEG snapshot
// ─────────────────────────────────────────────────────────────────────────────
void handleCapture() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { server.send(500, "text/plain", "Camera capture failed"); return; }
  server.sendHeader("Content-Disposition", "inline; filename=capture.jpg");
  server.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

// ─────────────────────────────────────────────────────────────────────────────
// Status / info endpoint
// ─────────────────────────────────────────────────────────────────────────────
void handleStatus() {
  StaticJsonDocument<256> doc;
  doc["name"]     = camName;
  doc["ip"]       = WiFi.localIP().toString();
  doc["rssi"]     = WiFi.RSSI();
  doc["uptime"]   = millis() / 1000;
  doc["firmware"] = "1.0.0";
  String out;
  serializeJson(doc, out);
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", out);
}

// ─────────────────────────────────────────────────────────────────────────────
// Setup portal (AP mode)
// ─────────────────────────────────────────────────────────────────────────────
const char SETUP_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phantom Eye Setup</title>
<style>
  body{font-family:monospace;background:#0a0a0a;color:#00ff88;display:flex;
       align-items:center;justify-content:center;min-height:100vh;margin:0}
  .box{border:1px solid #00ff8844;padding:2rem;max-width:400px;width:90%}
  h1{color:#00ff88;letter-spacing:.2em;font-size:1.1rem;margin:0 0 1.5rem}
  label{display:block;margin:.8rem 0 .2rem;font-size:.8rem;color:#888}
  input{width:100%;box-sizing:border-box;background:#111;border:1px solid #333;
        color:#00ff88;padding:.6rem;font-family:monospace;font-size:.9rem}
  input:focus{outline:none;border-color:#00ff88}
  button{margin-top:1.5rem;width:100%;padding:.8rem;background:#00ff88;
         color:#000;border:none;font-family:monospace;font-size:1rem;
         cursor:pointer;letter-spacing:.1em}
  .note{margin-top:1rem;font-size:.75rem;color:#555}
</style></head><body><div class="box">
<h1>◈ PHANTOM EYE SETUP</h1>
<form method="POST" action="/save">
  <label>WiFi SSID</label><input name="ssid" required>
  <label>WiFi Password</label><input name="pass" type="password">
  <label>Camera Name (e.g. FrontDoor)</label><input name="name" value="CAM-1" required>
  <label>Dashboard Server IP</label><input name="ip" placeholder="192.168.1.100" required>
  <label>Dashboard Port</label><input name="port" value="5000">
  <button type="submit">SAVE &amp; CONNECT</button>
</form>
<p class="note">After saving, the camera will reboot and connect to your network.</p>
</div></body></html>
)rawliteral";

void handleSetupPage() {
  server.send_P(200, "text/html", SETUP_HTML);
}

void handleSave() {
  if (!server.hasArg("ssid") || !server.hasArg("ip")) {
    server.send(400, "text/plain", "Missing required fields");
    return;
  }
  String ssid = server.arg("ssid");
  String pass = server.arg("pass");
  String name = server.arg("name");
  String ip   = server.arg("ip");
  uint16_t port = server.arg("port").toInt();
  if (port == 0) port = 5000;

  saveConfig(ssid, pass, name, ip, port);
  server.send(200, "text/html",
    "<html><body style='background:#0a0a0a;color:#00ff88;font-family:monospace;"
    "display:flex;align-items:center;justify-content:center;height:100vh'>"
    "<div style='text-align:center'><h2>✓ SAVED</h2><p>Rebooting in 3s...</p></div></body></html>");
  delay(3000);
  ESP.restart();
}

void handleFactory() {
  EEPROM.write(ADDR_MAGIC, 0);
  EEPROM.write(ADDR_MAGIC + 1, 0);
  EEPROM.commit();
  server.send(200, "text/plain", "Config cleared. Rebooting...");
  delay(1000);
  ESP.restart();
}

// ─────────────────────────────────────────────────────────────────────────────
// Setup
// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  EEPROM.begin(EEPROM_SIZE);
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);

  if (!initCamera()) {
    Serial.println("Camera init failed! Check connections.");
  }

  if (!configValid()) {
    // ── No config: start AP for setup ─────────────────────────────────────
    configMode = true;
    WiFi.softAPConfig(AP_IP, AP_IP, IPAddress(255, 255, 255, 0));
    WiFi.softAP(AP_SSID, AP_PASS);
    Serial.printf("AP started: %s  IP: %s\n", AP_SSID, AP_IP.toString().c_str());

    server.on("/",        handleSetupPage);
    server.on("/save",    HTTP_POST, handleSave);
    server.on("/factory", handleFactory);
    server.begin();
    return;
  }

  // ── Has config: connect to WiFi ─────────────────────────────────────────
  String ssid, pass;
  loadConfig(ssid, pass);
  Serial.printf("Connecting to %s ...\n", ssid.c_str());

  WiFi.begin(ssid.c_str(), pass.c_str());
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nWiFi failed. Starting AP for reconfigure...");
    configMode = true;
    EEPROM.write(ADDR_MAGIC, 0);  // invalidate so next boot also tries AP
    EEPROM.commit();
    WiFi.softAPConfig(AP_IP, AP_IP, IPAddress(255, 255, 255, 0));
    WiFi.softAP(AP_SSID, AP_PASS);
    server.on("/",        handleSetupPage);
    server.on("/save",    HTTP_POST, handleSave);
    server.begin();
    return;
  }

  Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());

  // mDNS so the dashboard can find it as e.g. frontdoor.local
  String mdnsName = camName;
  mdnsName.toLowerCase();
  mdnsName.replace(" ", "-");
  MDNS.begin(mdnsName.c_str());

  // ── Stream endpoints ─────────────────────────────────────────────────────
  server.on("/stream",  handleStream);
  server.on("/capture", handleCapture);
  server.on("/status",  handleStatus);
  server.on("/factory", handleFactory);
  server.begin();

  Serial.printf("Stream:  http://%s/stream\n",  WiFi.localIP().toString().c_str());
  Serial.printf("Capture: http://%s/capture\n", WiFi.localIP().toString().c_str());
  Serial.printf("Status:  http://%s/status\n",  WiFi.localIP().toString().c_str());
}

// ─────────────────────────────────────────────────────────────────────────────
// Loop
// ─────────────────────────────────────────────────────────────────────────────
void loop() {
  server.handleClient();
  // if (!configMode) MDNS.update();
}
