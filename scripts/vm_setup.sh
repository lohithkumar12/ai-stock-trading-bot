#!/usr/bin/env bash
# GCP Ubuntu VM setup for the AI stock trading bot.
# Run from the repo root AFTER: git clone ... && cd ai-stock-trading-bot
# Usage: bash scripts/vm_setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SERVICE_NAME="trading-bot"
SERVICE_USER="$(whoami)"
VENV_DIR="$REPO_ROOT/venv"
PYTHON_BIN="$VENV_DIR/bin/python"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git

echo "==> Creating virtualenv"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f "$REPO_ROOT/.env" ]]; then
  echo ""
  echo "WARNING: .env is missing."
  echo "Copy your local .env onto this VM before starting the bot:"
  echo "  nano $REPO_ROOT/.env"
  echo "  chmod 600 $REPO_ROOT/.env"
  echo ""
  if [[ -f "$REPO_ROOT/.env.example" ]]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    chmod 600 "$REPO_ROOT/.env"
    echo "Created .env from .env.example — replace placeholder keys before going live."
  fi
else
  chmod 600 "$REPO_ROOT/.env"
  echo "==> Found existing .env (permissions set to 600)"
fi

echo "==> Writing systemd unit: $SERVICE_FILE"
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=AI Stock Trading Bot (US + India)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_ROOT}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin
ExecStart=${PYTHON_BIN} ${REPO_ROOT}/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting ${SERVICE_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo ""
echo "Done."
echo "  Status:  sudo systemctl status ${SERVICE_NAME}"
echo "  Logs:    journalctl -u ${SERVICE_NAME} -f"
echo "  Restart: sudo systemctl restart ${SERVICE_NAME}"
echo "  Update:  git pull && source venv/bin/activate && pip install -r requirements.txt && sudo systemctl restart ${SERVICE_NAME}"
echo ""
echo "Dashboard has no login. Do NOT open port 5000 publicly."
echo "From your PC (with gcloud CLI):"
echo "  gcloud compute ssh trading-bot --zone=asia-south1-a -- -L 5000:localhost:5000"
echo "Then open http://localhost:5000"
