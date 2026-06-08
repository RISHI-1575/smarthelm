#!/bin/bash
# SmartHelm — Pi Setup Script
# Run once: bash setup.sh

set -e
echo ""
echo "========================================"
echo "  SmartHelm Setup"
echo "========================================"

# 1. System packages
echo ""
echo "[1] Installing system packages..."
sudo apt update -qq
sudo apt install -y python3-opencv python3-picamera2 python3-pip mosquitto mosquitto-clients nmap

# 2. Start MQTT broker
echo ""
echo "[2] Starting MQTT broker..."
sudo systemctl enable mosquitto
sudo systemctl start mosquitto

# 3. Python packages
echo ""
echo "[3] Installing Python packages..."
pip install flask mediapipe numpy paho-mqtt RPi.GPIO --break-system-packages

# 4. Clone or update repo
echo ""
echo "[4] Getting HelmNet code..."
if [ -d "$HOME/HelmNet" ]; then
    echo "    Repo exists, pulling latest..."
    cd "$HOME/HelmNet" && git pull
else
    git clone https://github.com/vishnu-k-dev/HelmNet.git "$HOME/HelmNet"
fi

# 5. Copy our modified files over the originals
echo ""
echo "[5] Applying Pi camera modifications..."
cp ~/smarthelm/backend/config.py  ~/HelmNet/smarthelm/backend/config.py
cp ~/smarthelm/backend/streams.py ~/HelmNet/smarthelm/backend/streams.py
cp ~/smarthelm/backend/app.py     ~/HelmNet/smarthelm/backend/app.py
cp ~/smarthelm/backend/alerts.py  ~/HelmNet/smarthelm/backend/alerts.py

# 6. Download MediaPipe face model
echo ""
echo "[6] Downloading MediaPipe face landmark model (~7MB)..."
mkdir -p "$HOME/HelmNet/smarthelm/backend/models"
MODEL_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_PATH="$HOME/HelmNet/smarthelm/backend/models/face_landmarker.task"
if [ ! -f "$MODEL_PATH" ]; then
    wget -q --show-progress -O "$MODEL_PATH" "$MODEL_URL"
    echo "    Model downloaded."
else
    echo "    Model already exists, skipping."
fi

echo ""
echo "========================================"
echo "  Setup complete!"
echo "  Run the system with:"
echo "    bash ~/run_smarthelm.sh"
echo "========================================"
echo ""
