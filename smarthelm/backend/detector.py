"""
detector.py — SmartHelm eye-state detector (EYES-ONLY mode).

Drop-in replacement for the MediaPipe face-mesh detector, for when the
camera sees ONLY the eyes (mounted too close for a full face).

Uses OpenCV Haar cascades, which SHIP WITH OpenCV — no model download,
no internet, no MediaPipe. Pure cv2 + numpy (already installed).

Logic:
  • Detect eyes with haarcascade_eye.xml.
  • Eyes found over the smoothing window  → OPEN.
  • No eyes found                          → CLOSED  (PERCLOS / 1.5s closure
                                              trigger handles the alert).
  • Lightly smoothed to kill blink flicker.

Interface matches app.py exactly:
    EyeDetector(mode=...).process(frame) -> result
    result.eye_state / .confidence / .ear_smoothed / .face_detected / .annotated_frame
"""

import os
import collections
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

try:
    import config
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    import config


@dataclass
class EyeResult:
    eye_state: str = "UNKNOWN"
    confidence: float = 0.0
    ear_smoothed: float = 0.0
    face_detected: bool = False
    annotated_frame: Optional[np.ndarray] = None


class EyeDetector:
    """Eyes-only open/closed detector using OpenCV Haar cascades."""

    def __init__(self, mode: str = "EYES"):
        self.mode = mode
        casc = cv2.data.haarcascades
        self.eye_cascade  = cv2.CascadeClassifier(os.path.join(casc, "haarcascade_eye.xml"))
        self.eye_cascade2 = cv2.CascadeClassifier(
            os.path.join(casc, "haarcascade_eye_tree_eyeglasses.xml"))

        win = getattr(config, "EAR_SMOOTHING_WINDOW", 5)
        self._hist = collections.deque(maxlen=max(3, int(win)))

    # ── eye detection (two cascades for robustness) ───────────────────
    def _detect_eyes(self, gray):
        eyes = self.eye_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(eyes) == 0:
            eyes = self.eye_cascade2.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return eyes

    # ── main entry ────────────────────────────────────────────────────
    def process(self, frame):
        if frame is None:
            return EyeResult()

        annotated = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        eyes  = self._detect_eyes(gray)
        found = len(eyes) > 0
        self._hist.append(1 if found else 0)
        score = sum(self._hist) / len(self._hist)   # fraction of recent frames with eyes

        if len(self._hist) < self._hist.maxlen:
            state = "OPEN" if found else "UNKNOWN"
        else:
            state = "OPEN" if score >= 0.5 else "CLOSED"

        # draw eye boxes + state label
        for (x, y, w, h) in eyes:
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)

        if state == "OPEN":
            color, label = (0, 255, 0), "OPEN"
        elif state == "CLOSED":
            color, label = (0, 0, 255), "CLOSED"
        else:
            color, label = (0, 165, 255), "DETECTING..."
        cv2.putText(annotated, label, (20, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3)

        # synthetic EAR for the dashboard gauge (open≈0.30, closed≈0.08)
        ear = 0.08 + 0.24 * score

        return EyeResult(
            eye_state       = state,
            confidence      = score if state == "OPEN" else (1.0 - score),
            ear_smoothed    = ear,
            face_detected   = found,
            annotated_frame = annotated,
        )
