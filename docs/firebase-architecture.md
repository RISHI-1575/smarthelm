# SmartHelm — Firebase Architecture & Helmet Linking

> Reference for wiring the Pi helmet into the fleet dashboard.
> Source of truth: the dashboard listens to **Cloud Firestore** only.

## 1. What it is

| Thing | Value |
|-------|-------|
| Database | **Cloud Firestore** — NOT Realtime Database |
| Project | **smarthelm-99225** — already exists, do not create a new one |
| Auth | Anonymous (app + dashboard), Phone OTP (manager login) |
| Pi auth | Admin SDK + service-account key (bypasses security rules) |

If the Pi writes to Realtime Database, nothing shows up — the dashboard only reads Firestore.

## 2. Collection tree

```
firestore (smarthelm-99225)
├── fleets/{code}              ← one per manager (6-char code, e.g. K6JB5G)
└── riders/{deviceId}          ← one per DEVICE: phone app OR helmet
    ├── alerts/{alertId}       ← append-only drowsiness events
    ├── session/{doc}          ← optional stats
    └── track/{point}          ← optional GPS breadcrumb
```

A helmet is just another `riders/{deviceId}` doc with a stable id like `helmet-001`.

## 3. fleets/{code} — manager registry

`code` = DJB2 hash of the last 10 digits of the manager phone.

| Field | Type | Example |
|-------|------|---------|
| managerPhone | string | "9611604661" (10 digits, no +91) |
| emergencyContact | string | "9876543210" |
| updatedAt | timestamp | — |

## 4. riders/{deviceId} — live telemetry doc

**Identity / linking**

| Field | Type | Purpose |
|-------|------|---------|
| riderName | string | card title |
| managerId | string | **THE LINK** — set to the fleet code |
| emergencyContact | string | for SMS |

**Drowsiness**

| Field | Type | Notes |
|-------|------|-------|
| eyeState | string | OPEN\|CLOSED\|UNKNOWN (enforced) |
| perclos | number | 0–100 (enforced) |
| continuousClosureSec | number | seconds eyes closed |
| alertActive | bool | authoritative drowsy flag |
| alertType | string | CONTINUOUS_CLOSURE, PERCLOS, YAWNING… |
| faceDetected | bool | face-lock meter |
| fatigueScore / fatigueLevel | number / string | 0–100 / OK\|CAUTION\|ALERT |
| yawnCount / blinkRate | number | — |

**Vision overlay (optional)**

| Field | Type | Notes |
|-------|------|-------|
| eyeLandmarksLeft / …Right | array<number> | flat [x1,y1,…], 0–1 normalised |
| snapshot | string | base64 JPEG, NO `data:` prefix |
| snapshotUpdatedAt | timestamp | — |

> ⚠️ Privacy: never push the **face** cam (CAM1) snapshot. Face frames must not leave the helmet. Road/rear cam only, or omit.

**Location**

| Field | Type | Notes |
|-------|------|-------|
| location | GeoPoint | dashboard reads location.latitude/.longitude |
| speedKmph / heading | number | optional |

**Biometrics — Pi/helmet (dashboard already wired)**

| Field | Type | Notes |
|-------|------|-------|
| heartRate | number | MAX30102 BPM |
| spo2 | number | MAX30102 SpO₂ % |

**Liveness / trip**

| Field | Type | Notes |
|-------|------|-------|
| connected | bool | true while active |
| tripActive | bool | true during trip |
| appState | string | FOREGROUND\|BACKGROUND\|ENDED (enforced) |
| tripId | string | per trip |
| lastHeartbeatAt | timestamp | refresh ≤15 s |
| updatedAt | timestamp | **rewrite every ~2s** or dashboard hides helmet (>30s = offline) |

## 5. The linking model

```
Manager logs into dashboard → writes fleets/K6JB5G
        │
   ┌────┴───────────────┬────────────────────┐
   ▼                    ▼                     ▼
Phone rider         Helmet (Pi)         future devices
enters K6JB5G       K6JB5G in config    enter K6JB5G
writes riders/{uuid} writes riders/helmet-001
  managerId=K6JB5G    managerId=K6JB5G
        └─────────┬──────────┘
                  ▼
   Dashboard (manager code = K6JB5G) shows only managerId === K6JB5G
```

## 6. Pi firebase_sync.py (Admin SDK)

```python
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin.firestore import GeoPoint, SERVER_TIMESTAMP

cred = credentials.Certificate("/home/vyrrs/smarthelm/serviceAccount.json")  # gitignored, never share
firebase_admin.initialize_app(cred)
db = firestore.client()

HELMET_ID, FLEET_CODE = "helmet-001", "K6JB5G"
doc = db.collection("riders").document(HELMET_ID)

def push_status(eye_state, perclos, alert, lat, lng, hr, spo2):
    data = {
        "riderName": "Helmet 001",
        "managerId": FLEET_CODE,        # ← THE LINK
        "eyeState": eye_state,          # OPEN|CLOSED|UNKNOWN
        "perclos": float(perclos),      # 0..100
        "alertActive": bool(alert),
        "faceDetected": True,
        "heartRate": float(hr), "spo2": float(spo2),
        "location": GeoPoint(lat, lng),
        "connected": True, "tripActive": True, "appState": "FOREGROUND",
        "lastHeartbeatAt": SERVER_TIMESTAMP, "updatedAt": SERVER_TIMESTAMP,
    }
    doc.set(data, merge=True)            # merge = never wipes other fields

# on shutdown:
# doc.set({"connected": False, "appState": "ENDED", "tripActive": False,
#          "updatedAt": SERVER_TIMESTAMP}, merge=True)
```

## 7. Service-account key rule

1. Console → ⚙ Project Settings → Service accounts → Generate new private key
2. Save JSON **only on the Pi**: `/home/vyrrs/smarthelm/serviceAccount.json`
3. `.gitignore` it: `*serviceAccount*.json`
4. Never commit, never paste it anywhere. If leaked, revoke immediately in console.

## 8. Rendering notes

- Grid has 6 slots; matching `riderName` takes that slot, else next free.
- `location` must be a real GeoPoint, not `{lat,lng}`.
- `snapshot` = raw base64 (no prefix) — and never the face cam.
