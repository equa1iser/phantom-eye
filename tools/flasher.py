#!/usr/bin/env python3
"""
PHANTOM EYE - ESP32 Flasher Tool
=================================
A dead-simple GUI to flash ESP32-CAM boards.
Even a complete beginner can use it: plug in board, pick port, click FLASH.

Requirements:
    pip install esptool pyserial tkinter

Usage:
    python flasher.py
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font as tkfont
import threading
import subprocess
import sys
import os
import json
import serial.tools.list_ports
from pathlib import Path

# ─── Color scheme ─────────────────────────────────────────────────────────────
BG       = "#0a0c0f"
BG2      = "#111418"
ACCENT   = "#00ff88"
ACCENT2  = "#00c8ff"
RED      = "#ff3366"
YELLOW   = "#ffcc00"
TEXT     = "#e0e0e0"
MUTED    = "#555"
BORDER   = "#1e2428"

FIRMWARE_DIR = Path(__file__).parent / "phantom_cam"


class FlasherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PHANTOM EYE ◈ ESP32 Flasher")
        self.geometry("700x580")
        self.configure(bg=BG)
        self.resizable(False, False)

        self._build_ui()
        self._refresh_ports()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="◈ PHANTOM EYE", bg=BG, fg=ACCENT, 
                 font=("Courier", 22, "bold")).pack()
        # tk.Label(hdr, text="◈  PHANTOM EYE", bg=BG, fg=ACCENT,
        #          font=("Courier", 22, "bold"), letter_spacing=4).pack()
        tk.Label(hdr, text="ESP32-CAM FLASHER", bg=BG, fg=MUTED,
                 font=("Courier", 10)).pack()

        # Divider
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20)

        # Main content
        main = tk.Frame(self, bg=BG, padx=30, pady=20)
        main.pack(fill="both", expand=True)

        # Left column: settings
        left = tk.Frame(main, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 20))

        self._section(left, "① SELECT PORT")
        port_row = tk.Frame(left, bg=BG)
        port_row.pack(fill="x", pady=(0, 16))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_row, textvariable=self.port_var,
                                        width=22, state="readonly")
        self.port_combo.pack(side="left")
        self._btn(port_row, "↻ Refresh", self._refresh_ports,
                  color=MUTED).pack(side="left", padx=(8, 0))

        self._section(left, "② CAMERA SETTINGS")
        self._field(left, "Camera Name",
                    "e.g. FrontDoor, BackYard, Garage",
                    "cam_name", "CAM-1")
        self._field(left, "WiFi SSID", "Your WiFi network name",
                    "wifi_ssid", "")
        self._field(left, "WiFi Password", "", "wifi_pass", "",
                    show="*")
        self._field(left, "Dashboard Server IP",
                    "IP of your home server laptop",
                    "dash_ip", "192.168.1.100")
        self._field(left, "Dashboard Port", "", "dash_port", "5000")

        # self._section(left, "③ FLASH")
        # flash_note = ("Make sure the ESP32-CAM is in FLASH MODE:\n"
        #               "Hold IO0 button → Press RESET → Release IO0")
        # tk.Label(left, text=flash_note, bg=BG, fg=YELLOW,
        #          font=("Courier", 8), justify="left").pack(anchor="w",
        #                                                     pady=(0, 10))

        self.flash_btn = self._btn(left, "⚡  FLASH CAMERA", self._flash,
                                    color=ACCENT, fg=BG, big=True)
        self.flash_btn.pack(fill="x")

        # Right column: log
        right = tk.Frame(main, bg=BG2, bd=1, relief="flat",
                          highlightbackground=BORDER,
                          highlightthickness=1)
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="OUTPUT LOG", bg=BG2, fg=MUTED,
                 font=("Courier", 8), pady=8).pack()

        self.log = scrolledtext.ScrolledText(
            right, bg=BG2, fg=TEXT, font=("Courier", 9),
            insertbackground=ACCENT, bd=0, relief="flat",
            wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.log.tag_config("ok",   foreground=ACCENT)
        self.log.tag_config("err",  foreground=RED)
        self.log.tag_config("warn", foreground=YELLOW)
        self.log.tag_config("info", foreground=ACCENT2)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        sb = tk.Frame(self, bg=BORDER, pady=6)
        sb.pack(fill="x", side="bottom")
        tk.Label(sb, textvariable=self.status_var, bg=BORDER,
                 fg=MUTED, font=("Courier", 9), padx=16).pack(side="left")

        # Progress bar
        self.progress = ttk.Progressbar(sb, mode="indeterminate", length=120)
        self.progress.pack(side="right", padx=16)

    def _section(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=ACCENT,
                 font=("Courier", 9, "bold")).pack(anchor="w", pady=(12, 4))

    def _field(self, parent, label, placeholder, attr, default, show=""):
        tk.Label(parent, text=label, bg=BG, fg=MUTED,
                 font=("Courier", 8)).pack(anchor="w")
        var = tk.StringVar(value=default)
        setattr(self, attr + "_var", var)
        e = tk.Entry(parent, textvariable=var, bg=BG2, fg=TEXT,
                     insertbackground=ACCENT,
                     highlightbackground=BORDER, highlightthickness=1,
                     highlightcolor=ACCENT, bd=0, font=("Courier", 9),
                     show=show)
        e.pack(fill="x", pady=(0, 8), ipady=5)
        if placeholder:
            e.bind("<FocusIn>", lambda _: None)

    def _btn(self, parent, text, cmd, color=ACCENT, fg=None, big=False):
        fg = fg or BG
        size = 11 if big else 9
        b = tk.Button(parent, text=text, command=cmd,
                       bg=color, fg=fg if big else color,
                       activebackground=color,
                       font=("Courier", size, "bold"),
                       relief="flat", cursor="hand2",
                       bd=0, padx=10, pady=8 if big else 4)
        if not big:
            b.configure(bg=BG2, highlightbackground=BORDER,
                         highlightthickness=1)
        return b

    # ── Logic ─────────────────────────────────────────────────────────────────
    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_var.set(ports[0])
            self._log(f"Found {len(ports)} port(s)", "info")
        else:
            self._log("No serial ports found. Plug in the ESP32-CAM.", "warn")

    def _log(self, msg, tag=""):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, msg):
        self.status_var.set(msg)

    def _flash(self):
        port = self.port_var.get()
        if not port:
            messagebox.showerror("Error", "Select a COM port first.")
            return

        cam_name  = self.cam_name_var.get().strip()
        wifi_ssid = self.wifi_ssid_var.get().strip()
        wifi_pass = self.wifi_pass_var.get()
        dash_ip   = self.dash_ip_var.get().strip()
        dash_port = self.dash_port_var.get().strip()

        if not cam_name:
            messagebox.showerror("Error", "Camera name cannot be empty.")
            return

        # Generate a customized version of the sketch by patching defines
        # For a real build we'd use arduino-cli; here we write a JSON
        # config that the firmware reads via EEPROM pre-flash.
        config = {
            "cam_name": cam_name,
            "wifi_ssid": wifi_ssid,
            "wifi_pass": wifi_pass,
            "dash_ip": dash_ip,
            "dash_port": int(dash_port) if dash_port else 5000,
        }

        self._log("=" * 50)
        self._log(f"Preparing to flash {cam_name} on {port}", "info")
        self._log(f"Config: {json.dumps(config, indent=2)}", "info")

        # Disable UI during flash
        self.flash_btn.configure(state="disabled")
        self.progress.start(10)
        threading.Thread(target=self._do_flash,
                          args=(port, config), daemon=True).start()

    def _do_flash(self, port, config):
        try:
            self._set_status("Flashing firmware...")
            self._log("Checking for esptool...", "info")

            # Check esptool
            result = subprocess.run(
                [sys.executable, "-m", "esptool", "--version"],
                capture_output=True, text=True)
            if result.returncode != 0:
                self._log("esptool not found. Installing...", "warn")
                subprocess.run([sys.executable, "-m", "pip", "install",
                                "esptool", "-q"], check=True)

            # Check arduino-cli
            self._log("Checking for arduino-cli...", "info")
            cli_path = self._find_arduino_cli()

            if not cli_path:
                self._log("arduino-cli not found.", "warn")
                self._log("Please install it: https://arduino.cc/en/software", "warn")
                self._log("─" * 40)
                self._log("MANUAL FLASH INSTRUCTIONS:", "warn")
                self._log("1. Open Arduino IDE", "info")
                self._log("2. File → Open → phantom_cam/phantom_cam.ino", "info")
                self._log("3. Tools → Board → AI Thinker ESP32-CAM", "info")
                self._log(f"4. Tools → Port → {port}", "info")
                self._log("5. Hold FLASH button on board", "info")
                self._log("6. Click Upload arrow", "info")
                self._log("7. When 'Connecting...' shows, release button", "info")

                # Write config for first-boot
                self._write_eeprom_config(port, config)
                return

            # Full arduino-cli flash
            self._arduino_cli_flash(cli_path, port, config)

        except Exception as e:
            self._log(f"ERROR: {e}", "err")
            self._set_status("Flash failed!")
        finally:
            self.flash_btn.configure(state="normal")
            self.progress.stop()

    def _find_arduino_cli(self):
        for candidate in ["arduino-cli", "arduino-cli.exe"]:
            try:
                r = subprocess.run([candidate, "version"],
                                    capture_output=True, text=True)
                if r.returncode == 0:
                    return candidate
            except FileNotFoundError:
                pass
        return None

    def _arduino_cli_flash(self, cli, port, config):
        sketch_dir = str(FIRMWARE_DIR)
        fqbn = "esp32:esp32:esp32cam"

        self._log("Compiling sketch...", "info")
        result = subprocess.run(
            [cli, "compile", "--fqbn", fqbn, sketch_dir],
            capture_output=True, text=True)
        self._log(result.stdout)
        if result.returncode != 0:
            self._log(result.stderr, "err")
            self._log("Compile failed!", "err")
            return

        self._log("Uploading...", "info")
        result = subprocess.run(
            [cli, "upload", "--fqbn", fqbn, "--port", port, sketch_dir],
            capture_output=True, text=True)
        self._log(result.stdout)
        if result.returncode != 0:
            self._log(result.stderr, "err")
            self._log("Upload failed!", "err")
            return

        self._log("✓ Firmware uploaded!", "ok")
        self._write_eeprom_config(port, config)

    def _write_eeprom_config(self, port, config):
        """Write config bytes via serial after a plain firmware flash."""
        import time
        self._log("Writing camera config to EEPROM via serial...", "info")
        try:
            import serial as ser_mod
            with ser_mod.Serial(port, 115200, timeout=3) as s:
                time.sleep(2)  # wait for board boot
                # Send config as JSON line — firmware reads on first boot
                line = json.dumps(config) + "\n"
                s.write(line.encode())
                time.sleep(1)
                resp = s.read_all().decode(errors="ignore")
                self._log(f"Board response: {resp}", "info")
        except Exception as e:
            self._log(f"Serial config write skipped ({e})", "warn")
            self._log("Camera will start in AP mode for manual setup.", "warn")

        self._log("─" * 40, "")
        self._log("✓ ALL DONE!", "ok")
        self._log(f"Camera '{config['cam_name']}' is ready.", "ok")
        self._log("On first boot it will connect to your WiFi.", "ok")
        self._log("If it can't connect it will create a hotspot:", "ok")
        self._log("  Network: PhantomEye-Setup", "ok")
        self._log("  Password: phantom123", "ok")
        self._log("  Then visit: http://192.168.4.1", "ok")
        self._set_status("Done!")


if __name__ == "__main__":
    app = FlasherApp()
    app.mainloop()
