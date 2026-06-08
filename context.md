# SmartHelm — Project Context
> Last updated: 2026-06-06
> Always read this file at the start of every session.

---

## What Is SmartHelm

An AI-powered drowsiness detection helmet system for motorcycle riders (primarily delivery riders on long shifts). It monitors the rider's eyes in real-time, tracks vital signs, and triggers audio + SMS alerts the moment drowsiness is detected — before an accident happens.

**GitHub repo:** https://github.com/vishnu-k-dev/HelmNet.git
**Pi IP:** 192.168.1.17
**Pi user:** vyrrs
**Pi hostname:** smarthelm
**Pi model:** Raspberry Pi 4 Model B Rev 1.5
**Python venv:** `~/smarthelm-venv` (Python 3.12 via uv)
**Run command:** `source ~/smarthelm-venv/bin/activate && cd ~/HelmNet/smarthelm/backend && sudo ~/smarthelm-venv/bin/python app.py`
**Dashboard:** `http://192.168.1.17:5000`

---

## Hardware Setup

### Raspberry Pi 4 — GPIO Pin Map

| GPIO | Pin | Connected To | Notes |
|------|-----|-------------|-------|
| GPIO2 | Pin 3 | MAX30102 SDA | I2C data |
| GPIO3 | Pin 5 | MAX30102 SCL | I2C clock |
| GPIO14 | Pin 8 | SIM800L RXD | UART TX from Pi |
| GPIO15 | Pin 10 | SIM800L TXD | UART RX to Pi |
| GPIO17 | Pin 11 | Buzzer signal | Via NPN transistor (2N2222/BC547) |
| Pin 1 | 3.3V | MAX30102 VCC | Must be 3.3V not 5V |
| Pin 2 | 5V | Buzzer (+), SIM800L via diodes | |
| Pin 6 | GND | All module GNDs | Common ground |

### Buzzer Wiring (Safe — with transistor)
```
GPIO17 (Pin 11) ──[1kΩ]──► Transistor BASE
5V     (Pin 2)  ─────────► Buzzer (+)
GND    (Pin 6)  ─────────► Transistor EMITTER
                            Transistor COLLECTOR ──► Buzzer (–)
```
Transistor: 2N2222 or BC547 (any NPN). Protects GPIO from 30-40mA buzzer draw.

### SIM800L Power
```
Pi 5V ──►|──►|──► SIM800L VCC   (2x diodes = 1.4V drop → 3.7V nominal ✓)
1000µF capacitor across SIM800L VCC/GND (handles TX current spikes)
```

### MAX30102 (Heart Rate + SpO2)
- I2C address: 0x57
- Confirmed detected: `sudo i2cdetect -y 1` shows `57`
- Part ID: 0x15 confirmed
- No external pull-up resistors needed (Pi has internal pull-ups)

### Cameras
| Camera | Model | Position | Status |
|--------|-------|----------|--------|
| CAM1 | Pi Camera OV5647 | Inside helmet (rider face) | ✅ Working — CSI ribbon cable |
| CAM2 | ESP32-CAM OV2640 | Front view (road ahead) | ⏳ Not yet wired to Pi hotspot |
| CAM3 | ESP32-CAM OV2640 | Rear view (traffic behind) | ⏳ Not yet wired to Pi hotspot |
| CAM4 | RHYX M21-45 | Wide angle rear | ⏳ Not yet integrated |

### Power
- Adapter: Official Pi 5.1V 3A USB-C
- Peak draw concern: Pi (2A) + SIM800L burst (2A) = 4A peak — monitor for under-voltage
- Check: `vcgencmd get_throttled` (0x0 = healthy, 0x50005 = under-voltage)

---

## Software Architecture

```
Pi Camera (CSI)
    │  rpicam-vid subprocess → MJPEG over TCP:8888
    │
    ▼
app.py (Flask :5000)
    ├── streams.py       → PiCameraStream reads rpicam-vid TCP stream
    ├── detector.py      → MediaPipe 468-point face mesh → EAR calculation
    ├── perclos.py       → 60s rolling window drowsiness tracker
    ├── alerts.py        → GPIO17 buzzer + SMS (SIM800L)
    ├── sensor.py        → MAX30102 heart rate + SpO2 via smbus2
    ├── mqtt_client.py   → Publishes events to localhost:1883
    └── config.py        → All tunable constants
         │
         ▼
    Dashboard (browser)
    /            → index.html
    /api/status  → eye state, PERCLOS, HR, SpO2, FPS, alerts
    /api/events  → last 20 alert events
    /api/test_buzzer → manually trigger buzzer
    /video_feed/cam1 → annotated MJPEG stream
    /video_feed/cam2 → front camera (placeholder)
    /video_feed/cam3 → rear camera (placeholder)
```

### File Locations on Pi
```
~/HelmNet/smarthelm/backend/
    app.py        — Flask server + inference orchestrator
    config.py     — All configuration (IPs, thresholds, pins)
    streams.py    — Camera stream wrappers
    detector.py   — MediaPipe eye detection (EAR method)
    perclos.py    — PERCLOS rolling window tracker
    alerts.py     — Buzzer (GPIO17) + SMS alerts
    sensor.py     — MAX30102 I2C reader
    mqtt_client.py — MQTT publisher
    models/
        face_landmarker.task  — MediaPipe model (~7MB)

~/HelmNet/smarthelm/dashboard/
    templates/index.html  — Dashboard UI
    static/dashboard.js   — 500ms polling frontend
    static/style.css      — Dark theme

~/smarthelm-venv/         — Python 3.12 virtual environment
~/smarthelm/backend/      — Modified source files (Mac copies)
```

---

## What the System Currently Does

### ✅ Working Right Now

| Feature | How | Detail |
|---------|-----|--------|
| Live camera feed | Pi CSI camera → rpicam-vid → TCP → OpenCV | 1296×972 @ 30fps |
| Face detection | MediaPipe 468 landmark model | EAR mode |
| Eye state detection | Eye Aspect Ratio (EAR) | OPEN>0.25, CLOSED<0.20 |
| EAR smoothing | 5-frame rolling average | Reduces blink noise |
| PERCLOS tracking | 60-second rolling window | Alert at 30% |
| Continuous closure alert | Timer | Alert at 1.5s |
| Buzzer alert | GPIO17 → NPN transistor → buzzer | 3 beeps × 300ms |
| Startup beep test | On every app launch | Confirms buzzer works |
| Dashboard UI | Flask + polling JS | Refreshes every 500ms |
| Eye state overlay | On video feed | OPEN/CLOSED/UNKNOWN badge |
| PERCLOS bar | Visual gauge | Red at 30%+ |
| Alert banner | Full-width red banner | On drowsiness detection |
| Event history | Table of last 20 alerts | With timestamp + type |
| Test buzzer button | Dashboard button → /api/test_buzzer | Manual test |
| MQTT publishing | Publishes to localhost:1883 | 2Hz max |
| CSV logging | logs/events.csv | 1Hz |
| SMS alerts | Via SIM800L (gsmmodem) | Disabled — no SIM inserted |
| MAX30102 detection | I2C address 0x57 confirmed | smbus2 installed |
| HR + SpO2 display | Dashboard vital signs card | Needs sensor.py running |

### ⚠️ Partially Working

| Feature | Status | Fix Needed |
|---------|--------|-----------|
| MAX30102 live readings | smbus2 installed, I2C confirmed | Verify sensor.py thread starts correctly |
| Buzzer GPIO init logging | Works but log appeared after fix | Monitor on next restart |
| CAM2 / CAM3 | Shows OFFLINE placeholder | Flash ESP32-CAMs with SmartHelm WiFi creds |

### ❌ Not Yet Done

| Feature | Reason |
|---------|--------|
| ESP32-CAM front/rear view | Cameras not flashed + connected to network |
| SMS alerts | No SIM card inserted in SIM800L |
| CNN eye classifier | ONNX model not trained/downloaded |
| Auto-start on boot | No systemd service created |

---

## Key Configuration (config.py)

```python
USE_PI_CAMERA        = True
PI_CAMERA_WIDTH      = 1296
PI_CAMERA_HEIGHT     = 972
BUZZER_PIN           = 17
EAR_OPEN_THRESHOLD   = 0.25
EAR_CLOSED_THRESHOLD = 0.20
EAR_SMOOTHING_WINDOW = 5
PERCLOS_THRESHOLD    = 30.0      # % in 60s window
CLOSED_DURATION_THRESHOLD = 1.5  # seconds
ALERT_COOLDOWN_SECONDS    = 3.0
ALERT_BEEP_COUNT     = 3
SMS_ENABLED          = False     # flip True when SIM inserted
SMS_PORT             = '/dev/ttyAMA0'
CAM1_URL             = 'http://192.168.1.101/stream'
CAM2_URL             = 'http://192.168.1.102/stream'
CAM3_URL             = 'http://192.168.1.103/stream'
```

---

## Installation Notes

### Python Environment
- System Python: 3.13.5 (Debian Trixie) — MediaPipe not supported
- Solution: Python 3.12 via `uv` tool in `~/smarthelm-venv`
- picamera2 not used (system-only package) — replaced with `rpicam-vid` subprocess

### Pi OS Notes
- Debian Trixie (Debian 13) — newer than Bookworm
- I2C enabled via raspi-config
- Bluetooth disabled via `dtoverlay=disable-bt` in `/boot/firmware/config.txt`
- `enable_uart=1` added for SIM800L UART on GPIO14/15
- Camera uses libcamera stack (not legacy bcm2835)
- `/dev/video0` = unicam raw Bayer (NOT usable directly by OpenCV)
- Camera accessed via `rpicam-vid` subprocess streaming MJPEG over TCP:8888

### Dependencies (in venv)
```
flask, mediapipe, numpy, paho-mqtt, RPi.GPIO, smbus2,
opencv-python-headless, uv (installer)
```

---

## Product Vision & Users

### Who Uses This
| User | Role | What They See |
|------|------|--------------|
| **Delivery Rider** | Wears helmet | Buzzer alert + voice warning |
| **Fleet Manager** | Swiggy/Zomato/Amazon ops | Dashboard — all riders live |
| **Company** | Swiggy/Zomato HQ | Reports, compliance, liability |
| **Emergency Contact** | Rider's family | SMS if alert fires |

### Why This Matters
- Delivery riders work 10-16 hour shifts, often nights
- India has 5 lakh+ delivery riders (Swiggy, Zomato, Blinkit, Amazon, Dunzo)
- Fatigue is #1 cause of delivery rider accidents
- Company is legally liable for rider safety
- Helmet pays for itself if it prevents one accident

### Privacy Architecture — NON-NEGOTIABLE
```
What NEVER leaves the helmet:
  ❌ Raw video frames
  ❌ Face images or photos
  ❌ Face landmark coordinates (468 points)
  ❌ Biometric identifiers

What goes to cloud (processed metadata only):
  ✅ Eye state score (OPEN/CLOSED — not who)
  ✅ PERCLOS % number
  ✅ Heart rate (BPM number)
  ✅ SpO2 % number
  ✅ GPS coordinates
  ✅ Alert events (timestamp + type + location)
  ✅ Device health stats
```
**All AI runs ON the helmet (edge computing). Video never leaves the device.**

### Rider Identity (Simple)
- Each helmet has a printed QR code sticker (Helmet ID e.g. H-007)
- Rider scans QR with phone → opens web page on Pi hotspot → enters name + employee ID
- Shift starts → manager sees "Raju Kumar — Helmet H-007 — Active"
- Shift ends → rider scans again to check out
- No app needed. Just a phone browser.

### Tamper Detection
- IR proximity sensor inside helmet → detects head wearing
- If system ON but helmet not worn → alert manager "Helmet H-007 not being worn"
- If front camera suddenly goes black → log as "camera covered" tamper attempt
- Magnetic reed switch on helmet clasp → detects if helmet opened/tampered

### Accident Insurance Recording
- CAM2 (front — road ahead) records continuously in a 60s loop
- CAM3 (rear — traffic behind) records continuously in a 60s loop
- On ANY alert → save 30s before + 30s after → "incident clip"
- Clips stored on Pi SD card → uploadable to cloud
- Rider/company submits clip to insurance company as evidence
- NOTE: External cameras only (road view) — rider's face clip stays local/private

### DPDP Consent (India 2023)
- Before first shift: rider connects phone to helmet hotspot → browser opens consent page
- Simple page: "SmartHelm collects drowsiness scores, heart rate, and GPS. Video stays on device. Tap AGREE to start."
- Consent logged with timestamp + employee ID
- Rider can withdraw consent and request data deletion anytime
- One-time setup per rider

### Data Ownership
- Rider owns their biometric data
- Company owns shift/route/alert data
- Driver can request deletion of their data
- Company cannot access raw video — only scores
- India DPDP Act 2023 compliant

---

## System Vision

### Standalone (works with zero internet, zero phone)
```
Helmet (Pi 4)
├── Pi Camera          → eye detection
├── MAX30102           → HR + SpO2
├── IMU MPU6050        → head movement + nodding
├── GPS NEO-6M         → location
├── SIM800L / SIM7600  → SMS emergency alert
├── Buzzer + Speaker   → audio alerts + voice
├── SQLite DB          → local event storage
└── Pi Hotspot         → local dashboard (phone connects to it)
```

### Cloud (syncs when 4G/WiFi available — metadata only, no video)
```
Helmet (Pi)
  │  Edge AI processes video locally
  │  Only sends: scores, HR, GPS, alerts
  ▼
SIM7600 4G (encrypted MQTT over TLS port 8883)
  │
  ▼
MQTT Broker (HiveMQ Cloud / AWS IoT)
  │
  ├──► InfluxDB (time-series: PERCLOS, HR, SpO2, GPS)
  │
  ├──► PostgreSQL (riders, shifts, companies, alerts)
  │
  ├──► Alert Engine ──► Twilio ──► Manager SMS/Call
  │
  └──► Web Dashboard (Fleet Manager sees live map + stats)
            │
            ├── Rider view: own data only
            └── Manager view: team data, anonymised option
```

---

## Upgrade Suggestions

### Standalone System — Must Have

| # | Feature | Hardware Needed | Effort |
|---|---------|----------------|--------|
| 1 | **Auto-start on boot** | None | 30 min |
| 2 | **SMS emergency alert** | SIM card in SIM800L | 10 min |
| 3 | **Voice alerts (TTS)** | USB speaker / 3.5mm speaker | 1 day |
| 4 | **Head nodding detection** | None (use existing MediaPipe) | 1 day |
| 5 | **Yawn detection** | None (use existing MediaPipe) | 1 day |
| 6 | **Helmet on/off detection** | IR proximity sensor (₹50) | 1 day |
| 7 | **Local SQLite database** | None | 1 day |
| 8 | **IMU head movement** | MPU6050 (₹120) via I2C | 2 days |
| 9 | **GPS location** | NEO-6M GPS (₹400) via UART | 2 days |
| 10 | **Panic button** | Momentary push button (₹20) | 2 hours |
| 11 | **Speed gating** | GPS speed OR OBD-II | 1 day |
| 12 | **Night mode** | IR LED ring around Pi cam | 2 days |

### Cloud System — High Value

| # | Feature | Stack | Effort |
|---|---------|-------|--------|
| 1 | **4G connectivity** | SIM7600 module (₹1500) replaces SIM800L | 2 days |
| 2 | **MQTT → Cloud broker** | HiveMQ Cloud (free) or AWS IoT | 1 day |
| 3 | **Time-series database** | InfluxDB Cloud (free tier) | 1 day |
| 4 | **Live fleet dashboard** | Grafana Cloud (free) | 2 days |
| 5 | **Rider fatigue report** | Daily PDF/email | 2 days |
| 6 | **Geofence + route tracking** | GPS + Google Maps API | 3 days |
| 7 | **Remote alert to manager** | Twilio SMS/call API | 1 day |
| 8 | **OTA updates** | Python script + cloud storage | 3 days |
| 9 | **Multi-rider web portal** | Flask/React + PostgreSQL | 1 week |
| 10 | **ML fatigue score** | Combine EAR + HR + HRV + IMU | 2 weeks |

### Tier 1 — Quick Wins (1-2 days each)

| Upgrade | What | Why |
|---------|------|-----|
| **Auto-start on boot** | systemd service | Helmet works without SSH |
| **SMS enable** | Insert SIM + flip SMS_ENABLED=True | Emergency contact alerts |
| **Head pose detection** | MediaPipe head pitch tracking | Catches nodding/head drop |
| **Yawn detection** | Mouth aspect ratio (MAR) | Earlier fatigue warning |
| **ESP32-CAM integration** | Flash cams + update stream URLs | Full 3-camera view |
| **Night mode** | Adjust camera exposure/gain at night | Works in dark conditions |

### Tier 2 — Medium Effort (1-2 weeks)

| Upgrade | What | Why |
|---------|------|-----|
| **CNN eye classifier** | Train/use ONNX model instead of EAR | More accurate, handles glasses |
| **Mobile dashboard** | Responsive CSS or PWA | View on phone while riding |
| **GPS module** | Add NEO-6M GPS via UART/I2C | Include location in SMS alert |
| **Helmet on/off detection** | IR proximity or IMU (MPU6050) | Don't alert when not wearing |
| **Speed gating** | OBD-II or GPS speed | Don't alert when stopped at light |
| **Heart rate drowsiness fusion** | Combine HRV + EAR + PERCLOS | Multi-sensor confidence score |

### Tier 3 — Major Features (weeks)

| Upgrade | What | Why |
|---------|------|-----|
| **Cloud dashboard** | MQTT → cloud broker → web app | Fleet monitoring for delivery companies |
| **Fatigue score model** | ML model combining all signals | Single score instead of separate triggers |
| **Emergency call** | SIM800L voice call capability | Call emergency contact, not just SMS |
| **OTA firmware update** | Update Pi remotely | No physical access needed |
| **Battery + solar** | Power bank + solar panel on helmet | Portable, no wiring to bike |
| **IMU integration** | MPU6050 accelerometer/gyro | Detect microsleeps from head movement |
| **Dashcam recording** | Record video on alert trigger | Evidence in case of accident |

### Hardware Upgrades

| Current | Better | Why |
|---------|--------|-----|
| Pi Camera OV5647 (5MP) | Pi Camera v3 (12MP, autofocus) | Better low-light, sharper face detection |
| Active buzzer | Piezo speaker | Variable tones, voice alerts |
| SIM800L | SIM7600 (4G LTE) | Faster SMS, data, GPS built-in |
| 5.1V 3A adapter | 5V 5A adapter | Headroom for SIM800L bursts |
| No IMU | MPU6050 | Head position + vibration sensing |

---

## Troubleshooting Reference

| Problem | Cause | Fix |
|---------|-------|-----|
| SSH timeout | Pi switched to hotspot or rebooted | `ssh vyrrs@192.168.1.17` |
| mediapipe not found | Python 3.13 not supported | Use `~/smarthelm-venv` (Python 3.12) |
| picamera2 not found in venv | System-only package | Use rpicam-vid subprocess (already done) |
| Black camera frames | unicam outputs raw Bayer data | Use rpicam-vid subprocess (already done) |
| No I2C devices | I2C not enabled | `sudo raspi-config → Interface Options → I2C` |
| SIM800L no response | BT on UART | `dtoverlay=disable-bt` in config.txt + reboot |
| Under-voltage | 3A adapter insufficient | `vcgencmd get_throttled` to check |
| apt can't reach internet | Pi in hotspot mode | Connect Pi to WiFi first |
