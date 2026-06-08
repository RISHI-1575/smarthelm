"""
app.py — SmartHelm Flask server and inference hub.

Start:
    cd HelmNet/smarthelm/backend
    sudo python app.py

Dashboard: http://<PI_IP>:5000

Threading model:
  Thread 0 (main)   : Flask HTTP server
  Thread 1 (daemon) : inference_loop — reads camera, runs detection
  Thread 2 (daemon) : paho-mqtt network loop
"""

import sys
import os
import time
import csv
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

# Configure logging FIRST so all module-level log messages are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smarthelm.app")

import cv2
import numpy as np
from flask import Flask, Response, render_template, jsonify

sys.path.insert(0, os.path.dirname(__file__))

import config
from streams import make_streams
from detector import EyeDetector
from perclos import PerclosTracker
from alerts import AlertManager
from mqtt_client import MQTTPublisher
from sensor import MAX30102Reader


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

@dataclass
class SharedState:
    lock: threading.Lock = field(default_factory=threading.Lock)

    eye_state: str     = "UNKNOWN"
    confidence: float  = 0.0
    ear_smoothed: float = 0.0
    face_detected: bool = False

    perclos: float                   = 0.0
    continuous_closure_seconds: float = 0.0
    alert_active: bool               = False

    fps: float               = 0.0
    inference_latency_ms: float = 0.0

    # MAX30102 sensor
    heart_rate: Optional[int]   = None
    spo2: Optional[int]         = None
    finger_detected: bool       = False

    latest_frame: Optional[np.ndarray] = None
    events: list = field(default_factory=list)
    detection_mode: str = config.DETECTION_MODE


_state       = SharedState()
_cam1_stream = None
_cam2_stream = None
_cam3_stream = None
_sensor      = None
_alert_mgr   = None
_placeholder_jpeg: bytes = b""


def _make_placeholder_jpeg(label: str = "CONNECTING...") -> bytes:
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, label, (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 80, 80), 2)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return buf.tobytes()


# ---------------------------------------------------------------------------
# Inference loop
# ---------------------------------------------------------------------------

def inference_loop(stream, state: SharedState, mqtt_pub: MQTTPublisher, alert_mgr: AlertManager):
    logger.info("Inference loop starting...")
    detector       = EyeDetector(mode=config.DETECTION_MODE)
    perclos_tracker = PerclosTracker()

    fps_alpha      = 0.1
    last_log_time  = 0.0
    last_mqtt_time = 0.0
    frame_start    = time.time()
    mqtt_interval  = 1.0 / config.MQTT_PUBLISH_HZ

    while True:
        try:
            ok, frame = stream.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue

            t0 = time.time()
            result         = detector.process(frame)
            perclos_result = perclos_tracker.update(result.eye_state)

            reason = "CONTINUOUS_CLOSURE" if perclos_result["alert_continuous"] else "PERCLOS"
            if perclos_result["alert_active"]:
                alert_mgr.trigger(reason=reason)
            else:
                alert_mgr.clear()

            t1            = time.time()
            latency_ms    = (t1 - t0) * 1000.0
            frame_interval = t1 - frame_start
            frame_start   = t1
            current_fps   = 1.0 / max(frame_interval, 0.001)

            with state.lock:
                state.fps = (
                    current_fps if state.fps == 0.0
                    else fps_alpha * current_fps + (1 - fps_alpha) * state.fps
                )
                state.eye_state                   = result.eye_state
                state.confidence                  = result.confidence
                state.ear_smoothed                = result.ear_smoothed
                state.face_detected               = result.face_detected
                state.perclos                     = perclos_result["perclos"]
                state.continuous_closure_seconds  = perclos_result["continuous_closure_sec"]
                state.inference_latency_ms        = latency_ms

                prev_alert   = state.alert_active
                state.alert_active = alert_mgr.is_active()

                if state.alert_active and not prev_alert:
                    event = {
                        "ts": int(time.time()),
                        "type": reason,
                        "perclos": perclos_result["perclos"],
                        "continuous_sec": perclos_result["continuous_closure_sec"],
                    }
                    state.events.append(event)
                    state.events = state.events[-20:]

                if result.annotated_frame is not None:
                    state.latest_frame = result.annotated_frame.copy()

            if t1 - last_mqtt_time >= mqtt_interval:
                with state.lock:
                    es, cf, pc, al = state.eye_state, state.confidence, state.perclos, state.alert_active
                mqtt_pub.publish("CAM1", es, cf, pc, al)
                last_mqtt_time = t1

            # MAX30102 sensor update
            if _sensor is not None:
                hr, spo2, finger = _sensor.get()
                with state.lock:
                    state.heart_rate     = hr
                    state.spo2           = spo2
                    state.finger_detected = finger

            if config.LOG_TO_CSV and (t1 - last_log_time) >= config.LOG_INTERVAL_SECONDS:
                _log_csv(state)
                last_log_time = t1

        except Exception as e:
            logger.error(f"Inference loop error: {e}", exc_info=True)
            time.sleep(0.1)


def _log_csv(state: SharedState):
    try:
        log_path = os.path.join(config.LOG_DIR, config.LOG_CSV_FILENAME)
        os.makedirs(config.LOG_DIR, exist_ok=True)
        write_header = not os.path.exists(log_path)
        with state.lock:
            row = [
                int(time.time()), state.eye_state, round(state.confidence, 3),
                round(state.ear_smoothed, 4), round(state.perclos, 2),
                state.alert_active, round(state.continuous_closure_seconds, 2),
                round(state.fps, 1),
            ]
        with open(log_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "timestamp", "eye_state", "confidence", "ear_smoothed",
                    "perclos", "alert", "continuous_closure_sec", "fps",
                ])
            writer.writerow(row)
    except Exception as e:
        logger.warning(f"CSV log error: {e}")


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

_backend_dir   = os.path.dirname(__file__)
_dashboard_dir = os.path.join(_backend_dir, "..", "dashboard")

app = Flask(
    __name__,
    template_folder=os.path.join(_dashboard_dir, "templates"),
    static_folder=os.path.join(_dashboard_dir, "static"),
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed/cam1")
def video_feed_cam1():
    return Response(_gen_cam1_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/snapshot/cam1")
def snapshot_cam1():
    with _state.lock:
        frame = _state.latest_frame.copy() if _state.latest_frame is not None else None
    if frame is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(frame, "No Frame", (240, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (80,80,80), 2)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(buf.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.route("/snapshot/cam2")
def snapshot_cam2():
    return _snapshot_stream(_cam2_stream, "CAM2")


@app.route("/snapshot/cam3")
def snapshot_cam3():
    return _snapshot_stream(_cam3_stream, "CAM3")


def _snapshot_stream(stream, label: str):
    frame = None
    if stream is not None:
        ok, frame = stream.read()
        if not ok:
            frame = None
    if frame is None:
        from streams import StaticFrameStream
        _, frame = StaticFrameStream(label).read()
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(buf.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.route("/video_feed/cam2")
def video_feed_cam2():
    return Response(_gen_raw_frames(_cam2_stream, "CAM2"), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/video_feed/cam3")
def video_feed_cam3():
    return Response(_gen_raw_frames(_cam3_stream, "CAM3"), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def api_status():
    with _state.lock:
        data = {
            "eye_state":              _state.eye_state,
            "confidence":             round(_state.confidence, 3),
            "ear_smoothed":           round(_state.ear_smoothed, 4),
            "perclos":                round(_state.perclos, 2),
            "alert":                  _state.alert_active,
            "continuous_closure_sec": round(_state.continuous_closure_seconds, 2),
            "face_detected":          _state.face_detected,
            "fps":                    round(_state.fps, 1),
            "latency_ms":             round(_state.inference_latency_ms, 1),
            "detection_mode":         _state.detection_mode,
            "heart_rate":             _state.heart_rate,
            "spo2":                   _state.spo2,
            "finger_detected":        _state.finger_detected,
            "timestamp":              int(time.time()),
        }
    return jsonify(data)


@app.route("/api/events")
def api_events():
    with _state.lock:
        events = list(_state.events)
    return jsonify(events)


@app.route("/api/test_buzzer")
def api_test_buzzer():
    """Manually trigger the buzzer for testing."""
    if _alert_mgr:
        _alert_mgr.trigger(reason="MANUAL_TEST")
        return jsonify({"status": "triggered", "gpio_ready": _alert_mgr is not None})
    return jsonify({"status": "alert_mgr not ready"}), 500


# ---------------------------------------------------------------------------
# MJPEG generators
# ---------------------------------------------------------------------------

def _gen_cam1_frames():
    while True:
        with _state.lock:
            frame = _state.latest_frame.copy() if _state.latest_frame is not None else None
        if frame is None:
            jpeg = _placeholder_jpeg
        else:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            jpeg = buf.tobytes() if ok else _placeholder_jpeg
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(config.MJPEG_FRAME_DELAY)


def _gen_raw_frames(stream, name: str):
    while True:
        if stream is None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + _placeholder_jpeg + b"\r\n"
            time.sleep(0.1)
            continue
        ok, frame = stream.read()
        if not ok or frame is None:
            jpeg = _placeholder_jpeg
        else:
            ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            jpeg = buf.tobytes() if ok2 else _placeholder_jpeg
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(config.MJPEG_FRAME_DELAY)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app():
    global _cam1_stream, _cam2_stream, _cam3_stream, _placeholder_jpeg

    logger.info("SmartHelm starting up...")
    _placeholder_jpeg = _make_placeholder_jpeg()

    mqtt_pub  = MQTTPublisher()
    mqtt_pub.connect()

    global _alert_mgr
    _alert_mgr = AlertManager()
    alert_mgr  = _alert_mgr

    # Quick startup beep — non-blocking
    logger.info("Buzzer: startup beep")
    _alert_mgr.trigger(reason="STARTUP_TEST")
    # clear after 1.5s in background
    threading.Thread(
        target=lambda: (time.sleep(1.5), _alert_mgr.clear()),
        daemon=True
    ).start()

    global _sensor
    _sensor = MAX30102Reader()
    logger.info("MAX30102 sensor reader started")

    _cam1_stream, _cam2_stream, _cam3_stream = make_streams(
        config.CAM1_URL, config.CAM2_URL, config.CAM3_URL
    )

    t = threading.Thread(
        target=inference_loop,
        args=(_cam1_stream, _state, mqtt_pub, alert_mgr),
        daemon=True,
        name="inference",
    )
    t.start()
    logger.info("Inference thread started")
    logger.info(f"Dashboard → http://0.0.0.0:{config.FLASK_PORT}")
    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        threaded=True,
        use_reloader=False,
        debug=False,
    )
