"""
PHANTOM EYE - Telegram Alert Plugin
=====================================
Sends a Telegram message (with snapshot) whenever an alert fires.

Setup:
  1. Create a Telegram bot via @BotFather and get your BOT_TOKEN
  2. Get your CHAT_ID — send a message to the bot then visit:
     https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
  3. Fill in BOT_TOKEN and CHAT_ID below
  4. Place this file in server/plugins/telegram_alerts.py
  5. Restart the server

Note: requires 'requests' (already installed)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import PhantomPlugin, register_plugin
import requests as req
import logging

log = logging.getLogger("phantom.telegram")

class TelegramPlugin(PhantomPlugin):
    name        = "telegram_alerts"
    version     = "1.0"
    description = "Sends Telegram messages on alerts with snapshot photos"

    # ── CONFIGURE THESE ────────────────────────────────────────────────────────
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    CHAT_ID   = "YOUR_CHAT_ID_HERE"
    # ──────────────────────────────────────────────────────────────────────────

    ICON = {
        "motion": "🚶",
        "detection_person": "🧍",
        "detection_car": "🚗",
    }

    def on_alert(self, alert: dict):
        if self.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            return  # Not configured

        icon = self.ICON.get(alert["type"], "⚠️")
        msg = (f"{icon} *PHANTOM EYE ALERT*\n"
               f"Camera: `{alert['cam_name']}`\n"
               f"Event: {alert['detail']}\n"
               f"Time: {alert['timestamp'][:19]}")

        try:
            if alert.get("snapshot"):
                # Send photo with caption
                snap_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "data", "alerts", alert["snapshot"])
                if os.path.exists(snap_path):
                    with open(snap_path, "rb") as f:
                        req.post(
                            f"https://api.telegram.org/bot{self.BOT_TOKEN}/sendPhoto",
                            data={"chat_id": self.CHAT_ID, "caption": msg,
                                  "parse_mode": "Markdown"},
                            files={"photo": f},
                            timeout=10)
                    return

            # Text only
            req.post(
                f"https://api.telegram.org/bot{self.BOT_TOKEN}/sendMessage",
                json={"chat_id": self.CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=10)
        except Exception as e:
            log.error(f"Telegram send failed: {e}")

    def on_startup(self):
        if self.BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":
            log.info("Telegram plugin ready")

register_plugin(TelegramPlugin())
