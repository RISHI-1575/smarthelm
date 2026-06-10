# SmartHelm 🪖

SmartHelm is an AI-powered drowsiness detection system built into a motorcycle helmet. It watches the rider's eyes in real time, tracks their heart rate and blood oxygen, and triggers an alert the moment it detects signs of fatigue — before an accident happens.

Built for delivery riders (Swiggy, Zomato, Amazon, etc.) who work long shifts, often through the night.

---

## The Problem It Solves

Delivery riders in India work 10–16 hour shifts. Fatigue is one of the leading causes of accidents among delivery riders, and companies are legally responsible for rider safety. SmartHelm catches drowsiness early and alerts the rider — and optionally their manager — before anything goes wrong.

---

## How It Works

A Raspberry Pi 4 sits inside the helmet and runs everything:

1. **Pi Camera** watches the rider's face continuously
2. **MediaPipe** detects 468 facial landmarks and calculates the Eye Aspect Ratio (EAR)
3. If the rider's eyes are closed for too long, or PERCLOS (% of time eyes are closed in 60s) crosses 30%, an alert fires
4. **Buzzer** beeps loudly inside the helmet
5. **MAX30102 sensor** monitors heart rate and SpO2 (blood oxygen)
6. A **web dashboard** shows live eye state, PERCLOS %, vitals, and alert history

All AI runs on the helmet itself — no video ever leaves the device.

---

## Hardware

| Component | Purpose |
|-----------|---------|
| Raspberry Pi 4 Model B | Main compute unit |
| Pi Camera OV5647 | Eye detection (inside helmet, facing rider) |
| MAX30102 | Heart rate + SpO2 sensor |
| SIM800L | SMS alerts to emergency contact |
| Buzzer (via NPN transistor) | Audio alert inside helmet |
| ESP32-CAM × 2 | Front and rear cameras (road view) — planned |

---

## Software Architecture

```
Pi Camera
    │
    ▼
app.py (Flask server on port 5000)
    ├── streams.py      → reads camera via rpicam-vid
    ├── detector.py     → MediaPipe face mesh + EAR calculation
    ├── alerts.py       → buzzer (GPIO17) + SMS alerts
    ├── sensor.py       → MAX30102 heart rate + SpO2
    └── config.py       → all thresholds and pin config
         │
         ▼
    Dashboard (browser at http://<PI_IP>:5000)
```

---

## Running It

This project runs on a **Raspberry Pi 4** — it won't run on a regular laptop because it needs the GPIO pins, Pi Camera, and I2C sensors.

**On the Pi:**
```bash
source ~/smarthelm-venv/bin/activate
cd ~/HelmNet/smarthelm/backend
sudo python app.py
```

Then open `http://192.168.1.17:5000` on any device connected to the same network.

---

## Key Settings (config.py)

| Setting | Value | Meaning |
|---------|-------|---------|
| `EAR_OPEN_THRESHOLD` | 0.25 | Eye is considered open above this |
| `EAR_CLOSED_THRESHOLD` | 0.20 | Eye is considered closed below this |
| `PERCLOS_THRESHOLD` | 30% | Alert if eyes closed >30% of last 60 seconds |
| `CLOSED_DURATION_THRESHOLD` | 1.5s | Alert if eyes continuously closed for 1.5s |
| `BUZZER_PIN` | GPIO17 | Pin connected to buzzer transistor |
| `SMS_ENABLED` | False | Flip to True when SIM card is inserted |

---

## Privacy

The camera never records or streams video outside the helmet. All processing happens on the Pi itself. Only processed data (eye scores, heart rate, GPS, alert events) is ever sent anywhere — no faces, no raw video.

---

## Project Structure

```
smarthelm/
├── smarthelm/
│   ├── backend/
│   │   ├── app.py          # Flask server + inference orchestrator
│   │   ├── alerts.py       # Buzzer + SMS alerts
│   │   ├── config.py       # All configuration and thresholds
│   │   ├── sensor.py       # MAX30102 heart rate + SpO2
│   │   └── streams.py      # Camera stream wrapper
│   └── dashboard/
│       ├── templates/index.html   # Dashboard UI
│       └── static/dashboard.js   # Live polling frontend
├── setup.sh                # Pi setup script
├── run_smarthelm.sh        # Quick start script
├── read_max30102.py        # Standalone sensor test
└── test_hardware.py        # Hardware diagnostics
```
