"""
alerts.py — Alert state management and audio output.

On Raspberry Pi: drives GPIO17 (active buzzer) directly.
Falls back to terminal BEL if GPIO is unavailable.
"""

import sys
import os
import time
import threading
import logging
import platform

sys.path.insert(0, os.path.dirname(__file__))
import config

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"
if _IS_WINDOWS:
    import winsound

# Initialise GPIO once at import time
_gpio_ready = False
GPIO = None
try:
    import RPi.GPIO as GPIO
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(config.BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)
    _gpio_ready = True
    logger.info(f"Buzzer: GPIO{config.BUZZER_PIN} initialised OK")
except Exception as e:
    logger.warning(f"Buzzer: GPIO init failed ({e}) — check RPi.GPIO is installed in venv")


class AlertManager:
    """
    Manages drowsiness alert state and audio feedback.
    Thread-safe.
    """

    def __init__(
        self,
        cooldown_seconds: float = None,
        freq: int = None,
        duration_ms: int = None,
        beep_count: int = None,
    ):
        self._cooldown    = cooldown_seconds or config.ALERT_COOLDOWN_SECONDS
        self._freq        = freq             or config.ALERT_BEEP_FREQUENCY
        self._duration_ms = duration_ms      or config.ALERT_BEEP_DURATION_MS
        self._beep_count  = beep_count       or config.ALERT_BEEP_COUNT

        self._alert_active  = False
        self._last_beep_time: float = 0.0
        self._last_sms_time: float  = 0.0
        self._beeping = threading.Event()
        self._lock    = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trigger(self, reason: str = "DROWSINESS"):
        with self._lock:
            if not self._alert_active:
                logger.warning(f"ALERT TRIGGERED — reason: {reason}")
            self._alert_active = True

            now = time.time()
            if not self._beeping.is_set() and (now - self._last_beep_time) >= self._cooldown:
                self._last_beep_time = now
                t = threading.Thread(target=self._beep_async, daemon=True, name="alert-beep")
                t.start()

            if config.SMS_ENABLED:
                mins_elapsed = (now - self._last_sms_time) / 60.0
                if mins_elapsed >= config.SMS_COOLDOWN_MINUTES:
                    self._last_sms_time = now
                    t = threading.Thread(target=self._sms_worker, daemon=True, name="alert-sms")
                    t.start()

    def clear(self):
        with self._lock:
            if self._alert_active:
                logger.info("Alert cleared")
            self._alert_active = False

    def is_active(self) -> bool:
        with self._lock:
            return self._alert_active

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _beep_async(self):
        self._beeping.set()
        try:
            for i in range(self._beep_count):
                if _IS_WINDOWS:
                    winsound.Beep(self._freq, self._duration_ms)
                else:
                    self._pi_beep()
                if i < self._beep_count - 1:
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Beep failed: {e}")
        finally:
            self._beeping.clear()

    def _pi_beep(self):
        """Drive GPIO17 buzzer directly."""
        if _gpio_ready and GPIO is not None:
            try:
                GPIO.output(config.BUZZER_PIN, GPIO.HIGH)
                time.sleep(self._duration_ms / 1000.0)
                GPIO.output(config.BUZZER_PIN, GPIO.LOW)
                logger.debug(f"Buzzer: beeped GPIO{config.BUZZER_PIN}")
                return
            except Exception as e:
                logger.warning(f"Buzzer: GPIO beep error: {e}")
        logger.warning("Buzzer: GPIO not ready — buzzer cannot fire")

    def _sms_worker(self):
        msg = "SmartHelm Alert: Rider drowsiness detected. Please check in immediately."
        try:
            _send_sms_via_at(config.SMS_PORT, config.SMS_BAUD,
                             config.EMERGENCY_CONTACT, msg)
            logger.info(f"SMS sent to {config.EMERGENCY_CONTACT}")
        except Exception as e:
            logger.warning(f"SMS failed: {e}")


# ---------------------------------------------------------------------------
# SMS via raw AT commands (stdlib termios — no pyserial / gsmmodem needed)
# ---------------------------------------------------------------------------

def _send_sms_via_at(port: str, baud: int, number: str, text: str):
    """Send one SMS over the SIM800L using AT commands and stdlib termios."""
    import termios

    bmap = {4800: termios.B4800, 9600: termios.B9600, 19200: termios.B19200,
            38400: termios.B38400, 57600: termios.B57600, 115200: termios.B115200}
    if baud not in bmap:
        raise ValueError(f"unsupported baud {baud}")

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        a = termios.tcgetattr(fd)
        a[0] = 0; a[1] = 0; a[3] = 0
        a[2] |= (termios.CLOCAL | termios.CREAD)
        a[2] &= ~termios.PARENB; a[2] &= ~termios.CSTOPB; a[2] &= ~termios.CSIZE
        a[2] |= termios.CS8
        a[4] = bmap[baud]; a[5] = bmap[baud]
        termios.tcsetattr(fd, termios.TCSANOW, a)
        try:
            termios.tcflush(fd, termios.TCIOFLUSH)
        except (termios.error, OSError):
            pass
        time.sleep(0.3)

        def cmd(data: bytes, wait: float = 1.0) -> str:
            os.write(fd, data)
            time.sleep(wait)
            buf = b""
            for _ in range(60):
                try:
                    c = os.read(fd, 256)
                    if c: buf += c
                    else: break
                except BlockingIOError:
                    time.sleep(0.03)
                except OSError:
                    break
            return buf.decode(errors="ignore")

        if "OK" not in cmd(b"AT\r\n"):
            raise RuntimeError("no AT response from modem")
        cmd(b"AT+CMGF=1\r\n")                                   # text mode
        cmd(b'AT+CMGS="' + number.encode() + b'"\r', wait=1.5)  # wait for '>' prompt
        resp = cmd(text.encode() + b"\x1a", wait=10.0)          # Ctrl-Z sends it
        if "+CMGS" not in resp and "OK" not in resp:
            raise RuntimeError(f"send failed: {resp.strip()!r}")
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------

import atexit

def _cleanup():
    if _gpio_ready:
        try:
            GPIO.output(config.BUZZER_PIN, GPIO.LOW)
            GPIO.cleanup()
        except Exception:
            pass

atexit.register(_cleanup)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mgr = AlertManager()
    print("Testing alert — 3 beeps on GPIO17 ...")
    mgr.trigger(reason="TEST")
    time.sleep(3)
    mgr.clear()
    print("Done.")
