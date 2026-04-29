/*
 * PHANTOM EYE - ESP32-CAM Firmware v2.0
 * ========================================
 * Full camera settings control via REST API:
 *   GET  /status          — camera info + current settings
 *   GET  /stream          — MJPEG stream
 *   GET  /capture         — single JPEG snapshot
 *   POST /settings        — update camera settings (JSON body)
 *   POST /led             — {"on": true/false} control flash LED
 *   GET  /factory         — reset all config
 *
 * Settings JSON keys (POST /settings):
 *   framesize (0-13), quality (0-63), brightness (-2..2), contrast (-2..2)
 *   saturation (-2..2), sharpness (-2..2), denoise (0-8)
 *   special_effect (0=none,1=neg,2=bw,3=red,4=green,5=blue,6=retro)
 *   wb_mode (0=auto,1=sunny,2=cloudy,3=office,4=home)
 *   awb (0/1), awb_gain (0/1), aec (0/1), aec2 (0/1)
 *   ae_level (-2..2), aec_value (0-1200), agc (0/1), agc_gain (0-30)
 *   gainceiling (0-6), bpc (0/1), wpc (0/1), raw_gma (0/1), lenc (0/1)
 *   vflip (0/1), hmirror (0/1), dcw (0/1), led (0/1)
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <EEPROM.h>
#include <ArduinoJson.h>

// ── Pin map (AI Thinker ESP32-CAM) ────────────────────────────────────────────
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22
#define LED_GPIO_NUM 4

// ── EEPROM ────────────────────────────────────────────────────────────────────
#define EEPROM_SIZE 256
#define ADDR_MAGIC 0
#define ADDR_SSID 2
#define ADDR_PASS 66
#define ADDR_NAME 130
#define ADDR_DASHIP 162
#define ADDR_PORT 194
#define MAGIC1 0xBE
#define MAGIC2 0xEF

#define AP_SSID "PhantomEye-Setup"
#define AP_PASS "phantom123"

WebServer server(80);
bool configMode = false;
String camName = "Front-Door";
String dashIP = "192.168.0.83";
uint16_t dashPort = 5000;
bool ledOn = false;

// ── EEPROM helpers ────────────────────────────────────────────────────────────
void writeStr(int addr, const String &s, int maxLen)
{
  int n = min((int)s.length(), maxLen - 1);
  for (int i = 0; i < n; i++)
    EEPROM.write(addr + i, s[i]);
  EEPROM.write(addr + n, 0);
}
String readStr(int addr, int maxLen)
{
  String s;
  char c;
  for (int i = 0; i < maxLen && (c = EEPROM.read(addr + i)); i++)
    s += c;
  return s;
}
bool cfgValid()
{
  return EEPROM.read(ADDR_MAGIC) == MAGIC1 && EEPROM.read(ADDR_MAGIC + 1) == MAGIC2;
}
void saveCfg(const String &ssid, const String &pass,
             const String &name, const String &ip, uint16_t port)
{
  EEPROM.write(ADDR_MAGIC, MAGIC1);
  EEPROM.write(ADDR_MAGIC + 1, MAGIC2);
  writeStr(ADDR_SSID, ssid, 64);
  writeStr(ADDR_PASS, pass, 64);
  writeStr(ADDR_NAME, name, 32);
  writeStr(ADDR_DASHIP, ip, 32);
  EEPROM.write(ADDR_PORT, port & 0xFF);
  EEPROM.write(ADDR_PORT + 1, (port >> 8) & 0xFF);
  EEPROM.commit();
}
void loadCfg(String &ssid, String &pass)
{
  ssid = readStr(ADDR_SSID, 64);
  pass = readStr(ADDR_PASS, 64);
  camName = readStr(ADDR_NAME, 32);
  dashIP = readStr(ADDR_DASHIP, 32);
  dashPort = EEPROM.read(ADDR_PORT) | (EEPROM.read(ADDR_PORT + 1) << 8);
  if (!camName.length())
    camName = "CAM-1";
  if (!dashPort || dashPort == 0xFFFF)
    dashPort = 5000;
}

// ── Camera init ───────────────────────────────────────────────────────────────
bool initCamera()
{
  camera_config_t cfg = {};
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM;
  cfg.pin_d1 = Y3_GPIO_NUM;
  cfg.pin_d2 = Y4_GPIO_NUM;
  cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM;
  cfg.pin_d5 = Y7_GPIO_NUM;
  cfg.pin_d6 = Y8_GPIO_NUM;
  cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk = XCLK_GPIO_NUM;
  cfg.pin_pclk = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM;
  cfg.pin_href = HREF_GPIO_NUM;
  cfg.pin_sscb_sda = SIOD_GPIO_NUM;
  cfg.pin_sscb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn = PWDN_GPIO_NUM;
  cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size = FRAMESIZE_VGA;
  cfg.jpeg_quality = 12;
  cfg.fb_count = 2;
  if (esp_camera_init(&cfg) != ESP_OK)
    return false;
  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 0);
  s->set_hmirror(s, 0);
  return true;
}

void addCORS()
{
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

// ── /stream ───────────────────────────────────────────────────────────────────
void handleStream()
{
  WiFiClient client = server.client();
  client.print("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n");
  while (client.connected())
  {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
    {
      delay(10);
      continue;
    }
    client.printf("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n", fb->len);
    client.write(fb->buf, fb->len);
    client.print("\r\n");
    esp_camera_fb_return(fb);
  }
}

// ── /capture ──────────────────────────────────────────────────────────────────
void handleCapture()
{
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb)
  {
    server.send(500, "text/plain", "Capture failed");
    return;
  }
  addCORS();
  server.sendHeader("Content-Disposition", "inline; filename=capture.jpg");
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

// ── /status ───────────────────────────────────────────────────────────────────
void handleStatus()
{
  sensor_t *s = esp_camera_sensor_get();
  StaticJsonDocument<600> doc;
  doc["name"] = camName;
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  doc["uptime"] = millis() / 1000;
  doc["firmware"] = "2.0.0";
  doc["led"] = ledOn;
  if (s)
  {
    doc["framesize"] = (int)s->status.framesize;
    doc["quality"] = s->status.quality;
    doc["brightness"] = s->status.brightness;
    doc["contrast"] = s->status.contrast;
    doc["saturation"] = s->status.saturation;
    doc["sharpness"] = s->status.sharpness;
    doc["denoise"] = s->status.denoise;
    doc["special_effect"] = s->status.special_effect;
    doc["wb_mode"] = s->status.wb_mode;
    doc["awb"] = s->status.awb;
    doc["awb_gain"] = s->status.awb_gain;
    doc["aec"] = s->status.aec;
    doc["aec2"] = s->status.aec2;
    doc["ae_level"] = s->status.ae_level;
    doc["aec_value"] = s->status.aec_value;
    doc["agc"] = s->status.agc;
    doc["agc_gain"] = s->status.agc_gain;
    doc["gainceiling"] = (int)s->status.gainceiling;
    doc["bpc"] = s->status.bpc;
    doc["wpc"] = s->status.wpc;
    doc["raw_gma"] = s->status.raw_gma;
    doc["lenc"] = s->status.lenc;
    doc["vflip"] = s->status.vflip;
    doc["hmirror"] = s->status.hmirror;
    doc["dcw"] = s->status.dcw;
  }
  String out;
  serializeJson(doc, out);
  addCORS();
  server.send(200, "application/json", out);
}

// ── /settings POST ────────────────────────────────────────────────────────────
void handleSettingsPost()
{
  if (server.method() == HTTP_OPTIONS)
  {
    addCORS();
    server.send(204);
    return;
  }
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, server.arg("plain")))
  {
    server.send(400, "text/plain", "Bad JSON");
    return;
  }
  sensor_t *s = esp_camera_sensor_get();
  if (!s)
  {
    server.send(500, "text/plain", "No sensor");
    return;
  }

  if (doc.containsKey("framesize"))
    s->set_framesize(s, (framesize_t)(int)doc["framesize"]);
  if (doc.containsKey("quality"))
    s->set_quality(s, doc["quality"]);
  if (doc.containsKey("brightness"))
    s->set_brightness(s, doc["brightness"]);
  if (doc.containsKey("contrast"))
    s->set_contrast(s, doc["contrast"]);
  if (doc.containsKey("saturation"))
    s->set_saturation(s, doc["saturation"]);
  if (doc.containsKey("sharpness"))
    s->set_sharpness(s, doc["sharpness"]);
  if (doc.containsKey("denoise"))
    s->set_denoise(s, doc["denoise"]);
  if (doc.containsKey("special_effect"))
    s->set_special_effect(s, doc["special_effect"]);
  if (doc.containsKey("wb_mode"))
    s->set_wb_mode(s, doc["wb_mode"]);
  if (doc.containsKey("awb"))
    s->set_whitebal(s, (int)doc["awb"]);
  if (doc.containsKey("awb_gain"))
    s->set_awb_gain(s, (int)doc["awb_gain"]);
  if (doc.containsKey("aec"))
    s->set_exposure_ctrl(s, (int)doc["aec"]);
  if (doc.containsKey("aec2"))
    s->set_aec2(s, (int)doc["aec2"]);
  if (doc.containsKey("ae_level"))
    s->set_ae_level(s, doc["ae_level"]);
  if (doc.containsKey("aec_value"))
    s->set_aec_value(s, doc["aec_value"]);
  if (doc.containsKey("agc"))
    s->set_gain_ctrl(s, (int)doc["agc"]);
  if (doc.containsKey("agc_gain"))
    s->set_agc_gain(s, doc["agc_gain"]);
  if (doc.containsKey("gainceiling"))
    s->set_gainceiling(s, (gainceiling_t)(int)doc["gainceiling"]);
  if (doc.containsKey("bpc"))
    s->set_bpc(s, (int)doc["bpc"]);
  if (doc.containsKey("wpc"))
    s->set_wpc(s, (int)doc["wpc"]);
  if (doc.containsKey("raw_gma"))
    s->set_raw_gma(s, (int)doc["raw_gma"]);
  if (doc.containsKey("lenc"))
    s->set_lenc(s, (int)doc["lenc"]);
  if (doc.containsKey("vflip"))
    s->set_vflip(s, (int)doc["vflip"]);
  if (doc.containsKey("hmirror"))
    s->set_hmirror(s, (int)doc["hmirror"]);
  if (doc.containsKey("dcw"))
    s->set_dcw(s, (int)doc["dcw"]);
  if (doc.containsKey("led"))
  {
    ledOn = (bool)doc["led"];
    digitalWrite(LED_GPIO_NUM, ledOn ? HIGH : LOW);
  }
  addCORS();
  server.send(200, "application/json", "{\"ok\":true}");
}

// ── /led POST ─────────────────────────────────────────────────────────────────
void handleLed()
{
  if (server.method() == HTTP_OPTIONS)
  {
    addCORS();
    server.send(204);
    return;
  }
  StaticJsonDocument<64> doc;
  deserializeJson(doc, server.arg("plain"));
  ledOn = doc["on"] | false;
  digitalWrite(LED_GPIO_NUM, ledOn ? HIGH : LOW);
  addCORS();
  server.send(200, "application/json", ledOn ? "{\"led\":true}" : "{\"led\":false}");
}

// ── /factory ──────────────────────────────────────────────────────────────────
void handleFactory()
{
  EEPROM.write(ADDR_MAGIC, 0);
  EEPROM.write(ADDR_MAGIC + 1, 0);
  EEPROM.commit();
  server.send(200, "text/plain", "Wiped. Rebooting...");
  delay(1000);
  ESP.restart();
}

// ── Setup portal ──────────────────────────────────────────────────────────────
const char SETUP_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phantom Eye Setup</title>
<style>
body{font-family:monospace;background:#0a0a0a;color:#00ff88;
     display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{border:1px solid #00ff8833;padding:2rem;max-width:400px;width:92%;box-sizing:border-box}
h1{color:#00ff88;letter-spacing:.15em;font-size:1rem;margin:0 0 1.5rem}
label{display:block;margin:.6rem 0 .15rem;font-size:.75rem;color:#666}
input{width:100%;box-sizing:border-box;background:#111;border:1px solid #333;
      color:#00ff88;padding:.5rem;font-family:monospace;font-size:.85rem}
input:focus{outline:none;border-color:#00ff88}
button{margin-top:1.2rem;width:100%;padding:.75rem;background:#00ff88;
       color:#000;border:none;font-family:monospace;font-size:.9rem;cursor:pointer}
.note{margin-top:.8rem;font-size:.65rem;color:#444}
</style></head><body><div class="box">
<h1>◈ PHANTOM EYE SETUP</h1>
<form method="POST" action="/save">
  <label>WiFi SSID</label><input name="ssid" required>
  <label>WiFi Password</label><input name="pass" type="password">
  <label>Camera Name</label><input name="name" value="CAM-1" required>
  <label>Dashboard IP</label><input name="ip" placeholder="192.168.1.100" required>
  <label>Dashboard Port</label><input name="port" value="5000">
  <button type="submit">SAVE &amp; CONNECT</button>
</form>
<p class="note">Camera reboots and connects automatically after saving.</p>
</div></body></html>
)rawliteral";

void handleSetup() { server.send_P(200, "text/html", SETUP_HTML); }
void handleSave()
{
  if (!server.hasArg("ssid") || !server.hasArg("ip"))
  {
    server.send(400, "text/plain", "Missing fields");
    return;
  }
  uint16_t port = server.arg("port").toInt();
  if (!port)
    port = 5000;
  saveCfg(server.arg("ssid"), server.arg("pass"),
          server.arg("name"), server.arg("ip"), port);
  server.send(200, "text/html",
              "<html><body style='background:#0a0a0a;color:#00ff88;font-family:monospace;"
              "display:flex;align-items:center;justify-content:center;height:100vh'>"
              "<div style='text-align:center'><h2>SAVED</h2><p>Rebooting...</p></div></body></html>");
  delay(2000);
  ESP.restart();
}

// ── setup() / loop() ──────────────────────────────────────────────────────────
void setup()
{
  Serial.begin(115200);
  EEPROM.begin(EEPROM_SIZE);
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);

  if (!initCamera())
    Serial.println("[!] Camera init failed");

  if (!cfgValid())
  {
    configMode = true;
    WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1),
                      IPAddress(255, 255, 255, 0));
    WiFi.softAP(AP_SSID, AP_PASS);
    server.on("/", handleSetup);
    server.on("/save", HTTP_POST, handleSave);
    server.on("/factory", handleFactory);
    server.begin();
    Serial.println("AP: PhantomEye-Setup  Visit http://192.168.4.1");
    return;
  }

  String ssid, pass;
  loadCfg(ssid, pass);
  WiFi.begin(ssid.c_str(), pass.c_str());
  for (int i = 0; i < 30 && WiFi.status() != WL_CONNECTED; i++)
  {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED)
  {
    EEPROM.write(ADDR_MAGIC, 0);
    EEPROM.commit();
    WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1),
                      IPAddress(255, 255, 255, 0));
    WiFi.softAP(AP_SSID, AP_PASS);
    server.on("/", handleSetup);
    server.on("/save", HTTP_POST, handleSave);
    server.begin();
    return;
  }

  Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());
  String mdns = camName;
  mdns.toLowerCase();
  mdns.replace(" ", "-");
  MDNS.begin(mdns.c_str());

  server.on("/stream", handleStream);
  server.on("/capture", handleCapture);
  server.on("/status", handleStatus);
  server.on("/settings", HTTP_POST, handleSettingsPost);
  server.on("/settings", HTTP_OPTIONS, handleSettingsPost);
  server.on("/led", HTTP_POST, handleLed);
  server.on("/led", HTTP_OPTIONS, handleLed);
  server.on("/factory", handleFactory);
  server.begin();
}

void loop()
{
  server.handleClient();
  // if (!configMode)
  //   MDNS.update();
}
