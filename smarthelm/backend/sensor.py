"""
sensor.py — MAX30102 heart rate and SpO2 reader.
Runs in a background daemon thread, updates shared readings continuously.
"""

import time
import threading
import collections
import logging

logger = logging.getLogger(__name__)

# MAX30102 registers
_ADDR         = 0x57
_R_INTR_EN_1  = 0x02
_R_INTR_EN_2  = 0x03
_R_FIFO_WR    = 0x04
_R_OVF_CTR    = 0x05
_R_FIFO_RD    = 0x06
_R_FIFO_DATA  = 0x07
_R_FIFO_CFG   = 0x08
_R_MODE_CFG   = 0x09
_R_SPO2_CFG   = 0x0A
_R_LED1_PA    = 0x0C
_R_LED2_PA    = 0x0D
_R_PILOT_PA   = 0x10
_R_INTR_ST_1  = 0x00
_R_PART_ID    = 0xFF

FINGER_THRESHOLD = 50000   # IR below this = no finger


class MAX30102Reader:
    """
    Reads heart rate and SpO2 from MAX30102 in a background thread.
    Usage:
        sensor = MAX30102Reader()
        hr, spo2, finger = sensor.get()
    """

    def __init__(self):
        self._hr    = None
        self._spo2  = None
        self._finger = False
        self._lock   = threading.Lock()
        self._ok     = False

        t = threading.Thread(target=self._loop, daemon=True, name="max30102")
        t.start()

    def get(self):
        """Returns (heart_rate_bpm, spo2_percent, finger_detected)."""
        with self._lock:
            return self._hr, self._spo2, self._finger

    def is_available(self) -> bool:
        return self._ok

    # ── Internal ──────────────────────────────────────────────────────────

    def _loop(self):
        try:
            import smbus2
        except ImportError:
            logger.warning("smbus2 not installed — MAX30102 disabled")
            return

        try:
            bus = smbus2.SMBus(1)
            pid = bus.read_byte_data(_ADDR, _R_PART_ID)
            if pid != 0x15:
                logger.warning(f"MAX30102 unexpected Part ID 0x{pid:02X}")
                return
            self._init(bus)
            self._ok = True
            logger.info("MAX30102 ready")
        except Exception as e:
            logger.warning(f"MAX30102 init failed: {e}")
            return

        ir_buf  = collections.deque(maxlen=100)
        red_buf = collections.deque(maxlen=100)

        while True:
            try:
                bus.read_byte_data(_ADDR, _R_INTR_ST_1)   # clear interrupt
                d = bus.read_i2c_block_data(_ADDR, _R_FIFO_DATA, 6)
                red = (d[0] << 16 | d[1] << 8 | d[2]) & 0x3FFFF
                ir  = (d[3] << 16 | d[4] << 8 | d[5]) & 0x3FFFF

                finger = ir > FINGER_THRESHOLD
                ir_buf.append(ir)
                red_buf.append(red)

                hr   = None
                spo2 = None
                if finger and len(ir_buf) >= 50:
                    hr   = self._calc_hr(ir_buf)
                    spo2 = self._calc_spo2(ir_buf, red_buf)

                with self._lock:
                    self._finger = finger
                    self._hr     = hr
                    self._spo2   = spo2

            except Exception as e:
                logger.debug(f"MAX30102 read error: {e}")
                time.sleep(1)
                continue

            time.sleep(0.04)   # ~25 sps

    def _init(self, bus):
        bus.write_byte_data(_ADDR, _R_MODE_CFG, 0x40)   # reset
        time.sleep(0.1)
        bus.write_byte_data(_ADDR, _R_FIFO_CFG, 0x4F)   # avg=4, rollover
        bus.write_byte_data(_ADDR, _R_MODE_CFG, 0x03)   # SpO2 mode
        bus.write_byte_data(_ADDR, _R_SPO2_CFG, 0x27)   # 100sps, 18-bit
        bus.write_byte_data(_ADDR, _R_LED1_PA,  0x24)   # Red ~7mA
        bus.write_byte_data(_ADDR, _R_LED2_PA,  0x24)   # IR  ~7mA
        bus.write_byte_data(_ADDR, _R_PILOT_PA, 0x7F)
        bus.write_byte_data(_ADDR, _R_FIFO_WR,  0x00)
        bus.write_byte_data(_ADDR, _R_OVF_CTR,  0x00)
        bus.write_byte_data(_ADDR, _R_FIFO_RD,  0x00)
        bus.write_byte_data(_ADDR, _R_INTR_EN_1, 0xC0)
        bus.write_byte_data(_ADDR, _R_INTR_EN_2, 0x00)

    @staticmethod
    def _calc_hr(ir_buf):
        ir   = list(ir_buf)
        mean = sum(ir) / len(ir)
        peaks, above = 0, False
        for v in ir:
            if v > mean and not above:
                peaks += 1
                above = True
            elif v <= mean:
                above = False
        if peaks < 2:
            return None
        duration = len(ir) / 25.0   # 25 sps effective
        bpm = int((peaks / duration) * 60)
        return bpm if 40 <= bpm <= 200 else None

    @staticmethod
    def _calc_spo2(ir_buf, red_buf):
        ir  = list(ir_buf)
        red = list(red_buf)
        ir_dc  = sum(ir)  / len(ir)
        red_dc = sum(red) / len(red)
        ir_ac  = max(ir)  - min(ir)
        red_ac = max(red) - min(red)
        if ir_dc == 0 or red_dc == 0 or ir_ac == 0:
            return None
        R    = (red_ac / red_dc) / (ir_ac / ir_dc)
        spo2 = int(110 - 25 * R)
        return max(80, min(100, spo2))
