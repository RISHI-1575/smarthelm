#!/usr/bin/env python3
"""
firebase_sync.py — pushes SmartHelm telemetry to Cloud Firestore.

Reads the already-running app's /api/status (localhost:5000) and writes to:
    riders/helmet-001        ← live doc, overwritten each heartbeat
    riders/helmet-001/alerts ← append-only drowsiness events

managerId = K6JB5G links this helmet to the fleet manager's dashboard.
The dashboard shows it only when managerId matches the manager's fleet code.

Design:
  • SEPARATE process from app.py → cloud I/O never blocks drowsiness detection.
  • Lightweight transport: google-auth (OAuth token) + urllib (stdlib HTTPS).
    No grpc / firebase-admin — chosen for the 2GB Pi (≈30MB vs ≈150MB).
  • Heartbeat every 2s (keeps the dashboard from flagging the helmet offline).
  • Instant push on a new alert (drowsiness can't wait for the next tick).
  • Fail-soft: a failed write is logged and retried next tick, never crashes.

Install once (Pi needs internet — ethernet recommended):
    uv pip install google-auth requests --python ~/smarthelm-venv/bin/python

Service account key (NEVER commit / share):
    place serviceAccount.json next to this file, or set SMARTHELM_KEY=/path

Run:
    ~/smarthelm-venv/bin/python firebase_sync.py
"""

import os
import sys
import json
import time
import signal
import logging
import datetime
import urllib.request
import urllib.error

# ── CONFIG ────────────────────────────────────────────────────────────
PROJECT_ID  = "smarthelm-99225"
HELMET_ID   = "helmet-001"
FLEET_CODE  = "K6JB5G"            # ← THE LINK to the fleet dashboard
RIDER_NAME  = "Helmet 001"

STATUS_URL    = "http://127.0.0.1:5000/api/status"
HEARTBEAT_SEC = 2.0              # must be < 30s or dashboard hides the helmet

# Fixed test location until a GPS module (NEO-6M) is wired. Swap for live GPS.
FIXED_LAT, FIXED_LNG = 12.9716, 77.5946   # Bengaluru

# Service account key — next to this script by default, override with SMARTHELM_KEY
KEY_PATH = os.environ.get(
    "SMARTHELM_KEY",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "serviceAccount.json"),
)

SCOPES   = ["https://www.googleapis.com/auth/datastore"]
BASE     = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"
COMMIT   = BASE + ":commit"
DOC_NAME = f"projects/{PROJECT_ID}/databases/(default)/documents/riders/{HELMET_ID}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] firebase_sync: %(message)s")
log = logging.getLogger(__name__)


# ── Auth (google-auth for the token only) ─────────────────────────────
_creds = None

def _get_token():
    global _creds
    from google.oauth2 import service_account
    import google.auth.transport.requests
    if _creds is None:
        _creds = service_account.Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


# ── Firestore REST value encoders ─────────────────────────────────────
def _s(v):   return {"stringValue": str(v)}
def _b(v):   return {"booleanValue": bool(v)}
def _d(v):   return {"doubleValue": float(v)}
def _geo(la, ln): return {"geoPointValue": {"latitude": la, "longitude": ln}}
def _ts(v):  return {"timestampValue": v}

def _now_rfc3339():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _http(url, body, method="POST"):
    token = _get_token()
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


# ── Writes ────────────────────────────────────────────────────────────
def _commit(fields):
    """Merge-write `fields` into riders/helmet-001 with server-side timestamps."""
    body = {"writes": [{
        "update": {"name": DOC_NAME, "fields": fields},
        "updateMask": {"fieldPaths": list(fields.keys())},   # merge: only these fields
        "updateTransforms": [
            {"fieldPath": "updatedAt",       "setToServerValue": "REQUEST_TIME"},
            {"fieldPath": "lastHeartbeatAt", "setToServerValue": "REQUEST_TIME"},
        ],
    }]}
    return _http(COMMIT, body)


def _build_fields(st):
    eye = (st.get("eye_state") or "UNKNOWN").upper()
    if eye not in ("OPEN", "CLOSED", "UNKNOWN"):
        eye = "UNKNOWN"
    perclos = max(0.0, min(100.0, float(st.get("perclos") or 0)))
    closure = float(st.get("continuous_closure_sec") or 0)
    alert   = bool(st.get("alert"))

    fields = {
        "riderName":            _s(RIDER_NAME),
        "managerId":            _s(FLEET_CODE),
        "eyeState":             _s(eye),
        "perclos":              _d(perclos),
        "continuousClosureSec": _d(closure),
        "alertActive":          _b(alert),
        "faceDetected":         _b(st.get("face_detected", False)),
        "location":             _geo(FIXED_LAT, FIXED_LNG),
        "connected":            _b(True),
        "tripActive":           _b(True),
        "appState":             _s("FOREGROUND"),
    }
    if alert:
        fields["alertType"] = _s("CONTINUOUS_CLOSURE" if closure >= 1.5 else "PERCLOS")
    if st.get("heart_rate") is not None:
        fields["heartRate"] = _d(st["heart_rate"])
    if st.get("spo2") is not None:
        fields["spo2"] = _d(st["spo2"])
    return fields


def _push_alert_event(st):
    closure = float(st.get("continuous_closure_sec") or 0)
    body = {"fields": {
        "type":                 _s("CONTINUOUS_CLOSURE" if closure >= 1.5 else "PERCLOS"),
        "perclos":              _d(float(st.get("perclos") or 0)),
        "continuousClosureSec": _d(closure),
        "createdAt":            _ts(_now_rfc3339()),
    }}
    return _http(f"{BASE}/riders/{HELMET_ID}/alerts", body)


def _mark_offline():
    _commit({
        "connected":  _b(False),
        "tripActive": _b(False),
        "appState":   _s("ENDED"),
    })


# ── Local app reader ──────────────────────────────────────────────────
def _get_status():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=3) as r:
            return json.load(r)
    except Exception as e:
        log.warning(f"app /api/status unreachable: {e}")
        return None


# ── Main loop ─────────────────────────────────────────────────────────
_running = True
def _shutdown(*_):
    global _running
    _running = False

def main():
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    if not os.path.exists(KEY_PATH):
        log.error(f"service account key not found: {KEY_PATH}")
        log.error("Download it from Firebase console → Project Settings → "
                  "Service accounts → Generate new private key, and place it there.")
        sys.exit(1)

    log.info(f"starting → riders/{HELMET_ID}  managerId={FLEET_CODE}  project={PROJECT_ID}")
    prev_alert = False

    while _running:
        t0 = time.time()
        st = _get_status()
        if st is not None:
            try:
                _commit(_build_fields(st))
                alert = bool(st.get("alert"))
                if alert and not prev_alert:        # rising edge → instant event
                    _push_alert_event(st)
                    log.info("alert event pushed to Firestore")
                prev_alert = alert
            except urllib.error.HTTPError as e:
                detail = e.read()[:200].decode(errors="ignore")
                log.warning(f"Firestore HTTP {e.code}: {detail}")
            except Exception as e:
                log.warning(f"Firestore write failed (will retry): {e}")

        time.sleep(max(0.0, HEARTBEAT_SEC - (time.time() - t0)))

    log.info("shutting down — marking helmet offline")
    try:
        _mark_offline()
    except Exception as e:
        log.warning(f"could not mark offline: {e}")


if __name__ == "__main__":
    main()
