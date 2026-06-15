#!/usr/bin/env python3
"""
eye_detect.py — Standalone EYES-ONLY drowsiness detector (laptop test).

Same logic as the Pi's detector.py, but self-contained and pointed at the
laptop webcam so you can verify eyes-only OPEN/CLOSED + drowsiness alert
before deploying to the helmet.

Uses OpenCV Haar cascades (ship with OpenCV) — no model, no MediaPipe.

Run live (opens a window, press Q to quit):
    eyes_test/venv/bin/python eyes_test/eye_detect.py

Headless self-test (no window — for CI / quick verify):
    eyes_test/venv/bin/python eyes_test/eye_detect.py --selftest
"""

import sys
import time
import collections

import cv2
import numpy as np

# ── Tunables (mirror config.py) ───────────────────────────────────────
SMOOTHING_WINDOW          = 5      # frames
CLOSED_DURATION_THRESHOLD = 1.5    # seconds eyes shut → drowsy alert
PERCLOS_WINDOW_SEC        = 60
PERCLOS_THRESHOLD         = 30.0   # %

CASC = cv2.data.haarcascades
EYE1 = cv2.CascadeClassifier(CASC + "haarcascade_eye.xml")
EYE2 = cv2.CascadeClassifier(CASC + "haarcascade_eye_tree_eyeglasses.xml")


class EyesOnlyDetector:
    def __init__(self):
        self.hist = collections.deque(maxlen=SMOOTHING_WINDOW)
        self.closed_since = None
        self.perclos_buf = collections.deque()   # (timestamp, is_closed)

    def detect_eyes(self, gray):
        eyes = EYE1.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(eyes) == 0:
            eyes = EYE2.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return eyes

    def process(self, frame):
        gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        eyes = self.detect_eyes(gray)
        found = len(eyes) > 0
        self.hist.append(1 if found else 0)
        score = sum(self.hist) / len(self.hist)

        if len(self.hist) < self.hist.maxlen:
            state = "OPEN" if found else "DETECTING"
        else:
            state = "OPEN" if score >= 0.5 else "CLOSED"

        now = time.time()
        is_closed = state == "CLOSED"

        # continuous-closure timer
        if is_closed:
            if self.closed_since is None:
                self.closed_since = now
            closure = now - self.closed_since
        else:
            self.closed_since = None
            closure = 0.0

        # PERCLOS over rolling window
        self.perclos_buf.append((now, is_closed))
        while self.perclos_buf and now - self.perclos_buf[0][0] > PERCLOS_WINDOW_SEC:
            self.perclos_buf.popleft()
        closed_frames = sum(1 for _, c in self.perclos_buf if c)
        perclos = 100.0 * closed_frames / max(1, len(self.perclos_buf))

        drowsy = closure >= CLOSED_DURATION_THRESHOLD or perclos >= PERCLOS_THRESHOLD
        return eyes, state, closure, perclos, drowsy


def draw(frame, eyes, state, closure, perclos, drowsy, fps):
    for (x, y, w, h) in eyes:
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

    color = (0, 255, 0) if state == "OPEN" else (0, 0, 255) if state == "CLOSED" else (0, 165, 255)
    cv2.putText(frame, state, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, color, 3)

    cv2.putText(frame, f"Closure: {closure:0.1f}s", (20, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2)
    cv2.putText(frame, f"PERCLOS: {perclos:0.0f}%", (20, 118),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2)
    cv2.putText(frame, f"FPS: {fps:0.0f}", (20, 146),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (160, 160, 160), 2)

    if drowsy:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, h), (0, 0, 255), 12)
        txt = "DROWSINESS ALERT - WAKE UP!"
        (tw, _), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)
        cv2.putText(frame, txt, ((w - tw) // 2, h - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
    return frame


def run_live():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("✗ Could not open webcam (camera permission for your terminal app?)")
        return 1
    print("✓ Webcam open. Look at the camera. Close your eyes ~2s to trigger the alert.")
    print("  Press Q in the window to quit.")
    det = EyesOnlyDetector()
    last = time.time(); fps = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        eyes, state, closure, perclos, drowsy = det.process(frame)
        now = time.time(); dt = now - last; last = now
        fps = 0.9 * fps + 0.1 * (1.0 / dt) if dt > 0 else fps
        if drowsy:
            sys.stdout.write("\a"); sys.stdout.flush()   # terminal bell = "buzzer"
        frame = draw(frame, eyes, state, closure, perclos, drowsy, fps)
        cv2.imshow("SmartHelm — Eyes-Only Test (press Q to quit)", frame)
        if cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q'), 27):
            break
    cap.release()
    cv2.destroyAllWindows()
    return 0


def run_selftest():
    print("=== SELF-TEST (headless) ===")
    if EYE1.empty() or EYE2.empty():
        print("✗ Haar cascades failed to load"); return 1
    print("✓ Haar cascades loaded")

    det = EyesOnlyDetector()
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        print("✓ Webcam opened — grabbing 40 frames...")
        counts = collections.Counter()
        for _ in range(40):
            ok, frame = cap.read()
            if not ok:
                break
            _, state, _, _, _ = det.process(frame)
            counts[state] += 1
            time.sleep(0.03)
        cap.release()
        print(f"  Eye-state distribution over 40 frames: {dict(counts)}")
        print("✓ Pipeline ran end-to-end on live webcam frames")
    else:
        print("ℹ Webcam not accessible here (camera permission) — testing on a synthetic frame")
        synthetic = np.full((480, 640, 3), 30, np.uint8)
        eyes, state, closure, perclos, drowsy = det.process(synthetic)
        print(f"  Synthetic frame → state={state}, closure={closure}, perclos={perclos}")
        print("✓ Pipeline ran without errors (run live in your terminal to see real detection)")
    print("=== SELF-TEST PASSED ===")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    sys.exit(run_live())
