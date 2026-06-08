#!/bin/bash
# SmartHelm — Start the system
# Run: bash run_smarthelm.sh

echo ""
echo "========================================"
echo "  SmartHelm Starting..."
echo "========================================"
echo ""
echo "  Dashboard → http://$(hostname -I | awk '{print $1}'):5000"
echo ""

cd "$HOME/HelmNet/smarthelm/backend"
sudo python app.py
