"""
streams.py — Camera stream wrappers for SmartHelm.

Classes:
  PiCameraStream   — Raspberry Pi CSI camera via picamera2 (USE_PI_CAMERA=True)
  MJPEGStream      — ESP32-CAM HTTP MJPEG stream with auto-reconnect
  StaticFrameStream — Offline placeholder frame
"""

import threading
import time
import logging
import urllib.request
import concurrent.futures
import cv2
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pi CSI Camera
# ---------------------------------------------------------------------------

class PiCameraStream:
    """
    Raspberry Pi CSI camera using rpicam-vid subprocess.
    rpicam-vid handles the libcamera pipeline and streams MJPEG over TCP.
    OpenCV connects to that local TCP stream.
    No picamera2 dependency — works in any Python venv.
    """

    TCP_PORT = 8888

    def __init__(self, width: int = None, height: int = None):
        import subprocess as _sp
        w = width  or config.PI_CAMERA_WIDTH
        h = height or config.PI_CAMERA_HEIGHT
        self.name = "PI_CAM"
        self._proc = None

        # Kill any leftover rpicam-vid from a previous run
        _sp.run(['pkill', '-f', 'rpicam-vid'], capture_output=True)
        time.sleep(0.5)

        # Start rpicam-vid as a TCP MJPEG server
        cmd = [
            'rpicam-vid',
            '-t',          '0',
            '--inline',
            '--nopreview',
            '--codec',     'mjpeg',
            '--quality',   '90',      # camera-side JPEG quality (default ~50 = blocky)
            '--listen',
            '--width',     str(w),
            '--height',    str(h),
            '--framerate', '12',      # lower fps → longer exposure → brighter, less gain noise
            '--denoise',   'cdn_hq',  # hardware denoise — kills low-light grain
            '--brightness','0.15',
            '--contrast',  '1.1',
            '--sharpness', '1.5',
            '--saturation','1.1',
            '--awb',       'auto',
            '-o', f'tcp://127.0.0.1:{self.TCP_PORT}',
        ]
        logger.info(f"PiCameraStream: starting rpicam-vid at {w}x{h}")
        self._proc = _sp.Popen(cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        time.sleep(2)   # wait for rpicam-vid to open the TCP port

        # Connect OpenCV to the MJPEG TCP stream
        self._cap = cv2.VideoCapture(
            f'tcp://127.0.0.1:{self.TCP_PORT}',
            cv2.CAP_FFMPEG
        )
        if not self._cap.isOpened():
            self._proc.terminate()
            raise RuntimeError(
                f"Cannot connect to rpicam-vid on TCP {self.TCP_PORT}. "
                "Make sure rpicam-vid is installed: rpicam-vid --version"
            )
        logger.info("PiCameraStream: connected to rpicam-vid stream")

        # Background thread: drain the stream continuously so read()
        # always returns the LATEST frame, eliminating buffer lag
        self._latest     = None
        self._frame_lock = threading.Lock()
        self._running    = True
        self._reader     = threading.Thread(
            target=self._drain, daemon=True, name="picam-drain"
        )
        self._reader.start()

    def _drain(self):
        """Continuously read and keep only the newest frame."""
        while self._running:
            ret, frame = self._cap.read()
            if ret and frame is not None:
                with self._frame_lock:
                    self._latest = frame

    def read(self):
        with self._frame_lock:
            if self._latest is None:
                return False, None
            return True, self._latest.copy()

    def is_connected(self) -> bool:
        return self._running and (self._proc is not None and self._proc.poll() is None)

    def release(self):
        self._running = False
        self._cap.release()
        if self._proc:
            self._proc.terminate()


# ---------------------------------------------------------------------------
# MJPEG stream (ESP32-CAM)
# ---------------------------------------------------------------------------

class MJPEGStream:
    """
    MJPEG stream reader using requests — no FFMPEG needed.
    Parses the multipart HTTP response and extracts JPEG frames directly.
    Auto-reconnects on failure.
    """

    def __init__(self, source: str, name: str = "CAM", reconnect_delay: float = 3.0, flip: bool = False):
        self.source         = source
        self.name           = name
        self.reconnect_delay = reconnect_delay
        self._flip          = flip  # True = rotate 180° (upside-down mount)

        self._frame     = None
        self._lock      = threading.Lock()
        self._connected = False
        self._running   = True

        t = threading.Thread(target=self._fetch_loop, daemon=True, name=f"{name}-fetch")
        t.start()

    # ── Public API ────────────────────────────────────────────────────

    def read(self):
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def release(self):
        self._running = False

    # ── Background fetch loop ─────────────────────────────────────────

    def _fetch_loop(self):
        """
        Polls /capture endpoint (single JPEG per request) instead of
        MJPEG stream — more reliable, supports multiple clients.
        ESP32-CAM capture URL: http://IP/capture  (port 80)
        """
        import urllib.request

        # Convert stream URL to capture URL
        # e.g. http://10.42.0.66:81/stream  →  http://10.42.0.66/capture
        import re
        capture_url = re.sub(r':\d+/.*$', '/capture', self.source)
        if '/capture' not in capture_url:
            capture_url = self.source.split(':81')[0] + '/capture'
        logger.info(f"{self.name}: using capture endpoint {capture_url}")

        while self._running:
            try:
                req  = urllib.request.Request(
                    capture_url,
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                resp = urllib.request.urlopen(req, timeout=5)
                jpg  = resp.read()

                frame = cv2.imdecode(
                    np.frombuffer(jpg, dtype=np.uint8),
                    cv2.IMREAD_COLOR
                )
                if frame is not None:
                    if self._flip:
                        frame = cv2.rotate(frame, cv2.ROTATE_180)
                    with self._lock:
                        self._frame     = frame
                        self._connected = True

                time.sleep(0.2)   # ~5 FPS polling — saves CPU

            except Exception as e:
                with self._lock:
                    self._connected = False
                placeholder = StaticFrameStream(self.name)
                _, pf = placeholder.read()
                with self._lock:
                    self._frame = pf
                logger.warning(f"{self.name}: offline, retry in 15s")
                time.sleep(15)  # don't hammer CPU when camera offline


# ---------------------------------------------------------------------------
# Static placeholder
# ---------------------------------------------------------------------------

class StaticFrameStream:
    """Returns a static OFFLINE placeholder frame."""

    def __init__(self, label: str, width: int = 640, height: int = 480):
        self.name = label
        self._frame = self._make_placeholder(label, width, height)

    def read(self):
        return True, self._frame.copy()

    def is_connected(self) -> bool:
        return True

    def release(self):
        pass

    @staticmethod
    def _make_placeholder(label: str, w: int, h: int) -> np.ndarray:
        img = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.rectangle(img, (2, 2), (w - 2, h - 2), (60, 60, 60), 2)
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw1, _), _ = cv2.getTextSize(label,    font, 1.0, 2)
        (tw2, th2), _ = cv2.getTextSize("OFFLINE", font, 0.7, 1)
        cv2.putText(img, label,     ((w - tw1) // 2, h // 2 - 10), font, 1.0, (120, 120, 120), 2)
        cv2.putText(img, "OFFLINE", ((w - tw2) // 2, h // 2 + th2 + 10), font, 0.7, (80, 80, 80), 1)
        return img


# ---------------------------------------------------------------------------
# Stream factories
# ---------------------------------------------------------------------------

def _probe_url(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False


def make_streams(cam1_url, cam2_url, cam3_url):
    """
    Create all 3 camera streams.
    When USE_PI_CAMERA=True, CAM1 is the Pi CSI camera;
    CAM2 and CAM3 are placeholders until ESP32-CAMs are added.
    """
    if config.USE_PI_CAMERA:
        logger.info("CAM1: using Pi CSI camera (picamera2)")
        cam1 = PiCameraStream()
    else:
        cam1 = _make_mjpeg_or_placeholder(cam1_url, "CAM1", webcam_priority=True)

    # CAM2 and CAM3 — ESP32-CAM streams
    cam2 = _make_mjpeg_or_placeholder(cam2_url, "CAM2", flip=False)
    cam3 = _make_mjpeg_or_placeholder(cam3_url, "CAM3", flip=True)  # mounted upside-down

    return cam1, cam2, cam3


def _make_mjpeg_or_placeholder(url, name, webcam_priority=False, flip=False):
    if not url:
        logger.warning(f"{name}: no URL configured — using placeholder")
        return StaticFrameStream(name)
    logger.info(f"{name}: connecting to {url}")
    return MJPEGStream(url, name=name, flip=flip)


# kept for backward compat with app.py import
def make_streams_parallel(sources: list, names: list) -> list:
    return list(make_streams(*sources))
