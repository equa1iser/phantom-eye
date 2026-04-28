#!/bin/bash
# ============================================================
# PHANTOM EYE - Server Setup Script
# Run once on your home server laptop (Ubuntu/Debian/macOS)
# Usage: bash setup_server.sh
# ============================================================

set -e

CYAN="\033[96m"
GREEN="\033[92m"
YELLOW="\033[93m"
RED="\033[91m"
RESET="\033[0m"

echo -e "${CYAN}"
echo "  ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗"
echo "  ██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║"
echo "  ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║"
echo "  ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║"
echo "  ██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║"
echo "  ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝"
echo "                           EYE  ◈  SERVER SETUP"
echo -e "${RESET}"

# ── Detect OS ──────────────────────────────────────────────────────────────────
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
  OS="macos"
fi

echo -e "${GREEN}[1/6] Detected OS: $OS${RESET}"

# ── Python check ───────────────────────────────────────────────────────────────
echo -e "${GREEN}[2/6] Checking Python 3...${RESET}"
if ! command -v python3 &>/dev/null; then
  echo -e "${YELLOW}Python 3 not found. Installing...${RESET}"
  if [[ "$OS" == "linux" ]]; then
    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
  else
    echo -e "${RED}Please install Python 3 from https://python.org${RESET}"
    exit 1
  fi
fi
python3 --version

# ── Create virtual environment ─────────────────────────────────────────────────
echo -e "${GREEN}[3/6] Creating virtual environment...${RESET}"
python3 -m venv venv
source venv/bin/activate

# ── Install dependencies ───────────────────────────────────────────────────────
echo -e "${GREEN}[4/6] Installing dependencies...${RESET}"
pip install --upgrade pip -q
pip install -r requirements.txt

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Optional: AI object detection (YOLO/Ultralytics)"
echo "  This requires ~500MB download and a decent CPU/GPU."
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
read -p "Install AI detection (ultralytics/YOLO)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  pip install ultralytics
  echo -e "${GREEN}✓ YOLO installed${RESET}"
else
  echo "  Skipped. You can install later: pip install ultralytics"
fi

# ── Create systemd service (Linux only) ───────────────────────────────────────
echo ""
echo -e "${GREEN}[5/6] Setting up auto-start service...${RESET}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$OS" == "linux" ]]; then
  SERVICE_FILE="/etc/systemd/system/phantom-eye.service"
  VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"

  sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Phantom Eye Security Dashboard
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$VENV_PYTHON server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable phantom-eye
  echo -e "${GREEN}✓ Service installed and enabled (auto-starts on boot)${RESET}"
  echo "  Manage with:"
  echo "    sudo systemctl start phantom-eye"
  echo "    sudo systemctl stop phantom-eye"
  echo "    sudo systemctl status phantom-eye"
  echo "    journalctl -u phantom-eye -f"
fi

# ── Get server IP ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}[6/6] Detecting server IP address...${RESET}"
if [[ "$OS" == "linux" ]]; then
  SERVER_IP=$(hostname -I | awk '{print $1}')
else
  SERVER_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "unknown")
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ PHANTOM EYE SETUP COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Server IP:    $SERVER_IP"
echo "  Dashboard:    http://$SERVER_IP:5000"
echo ""
echo "  Use this IP when flashing ESP32-CAM boards."
echo ""
echo "  To start the server now:"
echo "    source venv/bin/activate"
echo "    python server.py"
echo ""
if [[ "$OS" == "linux" ]]; then
  echo "  Or via systemd:"
  echo "    sudo systemctl start phantom-eye"
fi
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
