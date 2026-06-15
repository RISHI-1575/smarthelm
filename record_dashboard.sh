#!/bin/bash
# record_dashboard.sh — record the SmartHelm dashboard to an MP4 for documentation.
#
# Renders the live dashboard in a headless Chromium on a virtual display (Xvfb)
# and captures it with ffmpeg. The ?autostart=1 param makes the cameras load
# automatically (no manual "Start Cameras" click needed).
#
# Usage:
#   ./record_dashboard.sh [seconds] [output.mp4] [WIDTHxHEIGHT] [fps]
# Examples:
#   ./record_dashboard.sh                       # 60s, auto-named, 1280x720, 10fps
#   ./record_dashboard.sh 30                     # 30 second clip
#   ./record_dashboard.sh 120 demo.mp4 1280x720 12
#
# One-time install (Pi needs internet):
#   sudo apt install -y xvfb ffmpeg chromium
#
# NOTE: this adds real CPU load on a 2GB Pi. Record short clips, ideally when
# the helmet is not in safety-critical use.

set -e

DURATION="${1:-60}"
OUTPUT="${2:-$HOME/recordings/smarthelm_$(date +%Y%m%d_%H%M%S).mp4}"
RES="${3:-1280x720}"
FPS="${4:-10}"
URL="http://localhost:5000/?autostart=1"
DISP=99

mkdir -p "$(dirname "$OUTPUT")"

# Find the chromium binary (name differs across Pi OS versions)
CHROME=""
for c in chromium-browser chromium chromium-browser-v2 google-chrome; do
  if command -v "$c" >/dev/null 2>&1; then CHROME="$c"; break; fi
done
if [ -z "$CHROME" ]; then
  echo "✗ Chromium not found. Install:  sudo apt install -y chromium xvfb ffmpeg"
  exit 1
fi
command -v Xvfb  >/dev/null || { echo "✗ Xvfb not found:  sudo apt install -y xvfb"; exit 1; }
command -v ffmpeg >/dev/null || { echo "✗ ffmpeg not found: sudo apt install -y ffmpeg"; exit 1; }

echo "▶ Recording ${DURATION}s of dashboard at ${RES}@${FPS}fps → $OUTPUT"

cleanup() {
  kill "$CHROME_PID"  2>/dev/null || true
  kill "$XVFB_PID"    2>/dev/null || true
  rm -rf /tmp/chrome-rec-profile
}
trap cleanup EXIT

# 1. Virtual display
Xvfb ":$DISP" -screen 0 "${RES}x24" >/dev/null 2>&1 &
XVFB_PID=$!
export DISPLAY=":$DISP"
sleep 2

# 2. Chromium in kiosk mode, rendered onto the virtual display
"$CHROME" \
  --no-sandbox --no-first-run --no-default-browser-check \
  --disable-gpu --disable-infobars --hide-scrollbars \
  --kiosk --window-position=0,0 --window-size="${RES/x/,}" \
  --user-data-dir=/tmp/chrome-rec-profile \
  "$URL" >/dev/null 2>&1 &
CHROME_PID=$!

# 3. Let the page + camera feeds load before recording
sleep 6

# 4. Capture the display to MP4
ffmpeg -y -f x11grab -video_size "$RES" -framerate "$FPS" -i ":$DISP" \
  -t "$DURATION" -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -movflags +faststart "$OUTPUT" </dev/null

echo "✓ Saved → $OUTPUT"
echo "  Copy to Mac:  scp vyrrs@10.42.0.1:$OUTPUT ~/Desktop/"
