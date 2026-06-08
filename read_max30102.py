#!/usr/bin/env python3
"""
MAX30102 Live Readings — SmartHelm
====================================
Shows live IR + Red values, Heart Rate estimate, SpO2 estimate.
Place finger firmly on the sensor after starting.

Run:
    sudo python3 read_max30102.py

Press Ctrl+C to stop.
"""

import smbus2
import time
import collections

I2C_ADDR = 0x57
I2C_BUS  = 1

# ── Register Map ──────────────────────────────────────
R_INTR_STATUS_1 = 0x00
R_INTR_EN_1     = 0x02
R_INTR_EN_2     = 0x03
R_FIFO_WR_PTR   = 0x04
R_OVF_COUNTER   = 0x05
R_FIFO_RD_PTR   = 0x06
R_FIFO_DATA     = 0x07
R_FIFO_CFG      = 0x08
R_MODE_CFG      = 0x09
R_SPO2_CFG      = 0x0A
R_LED1_PA       = 0x0C   # Red LED amplitude
R_LED2_PA       = 0x0D   # IR  LED amplitude
R_PILOT_PA      = 0x10
R_PART_ID       = 0xFF

# If IR value is below this — no finger on sensor
FINGER_THRESHOLD = 50000


# ── Initialise sensor ─────────────────────────────────
def init_sensor(bus):
    # Software reset
    bus.write_byte_data(I2C_ADDR, R_MODE_CFG, 0x40)
    time.sleep(0.1)

    # FIFO: sample averaging=4, FIFO rollover enabled, almost-full=17
    bus.write_byte_data(I2C_ADDR, R_FIFO_CFG, 0x4F)

    # Mode: SpO2 (Red + IR LEDs)
    bus.write_byte_data(I2C_ADDR, R_MODE_CFG, 0x03)

    # SpO2 config: ADC range=4096nA, 100 sps, pulse width=411µs (18-bit)
    bus.write_byte_data(I2C_ADDR, R_SPO2_CFG, 0x27)

    # LED brightness (~7mA — increase to 0x3F for stronger signal if needed)
    bus.write_byte_data(I2C_ADDR, R_LED1_PA,  0x24)   # Red
    bus.write_byte_data(I2C_ADDR, R_LED2_PA,  0x24)   # IR
    bus.write_byte_data(I2C_ADDR, R_PILOT_PA, 0x7F)

    # Clear FIFO pointers
    bus.write_byte_data(I2C_ADDR, R_FIFO_WR_PTR, 0x00)
    bus.write_byte_data(I2C_ADDR, R_OVF_COUNTER, 0x00)
    bus.write_byte_data(I2C_ADDR, R_FIFO_RD_PTR, 0x00)

    # Enable FIFO-almost-full interrupt
    bus.write_byte_data(I2C_ADDR, R_INTR_EN_1, 0xC0)
    bus.write_byte_data(I2C_ADDR, R_INTR_EN_2, 0x00)


# ── Read one sample from FIFO ─────────────────────────
def read_fifo(bus):
    # Clear interrupt flag
    bus.read_byte_data(I2C_ADDR, R_INTR_STATUS_1)

    # 6 bytes: [Red 3 bytes] [IR 3 bytes]
    d = bus.read_i2c_block_data(I2C_ADDR, R_FIFO_DATA, 6)
    red = (d[0] << 16 | d[1] << 8 | d[2]) & 0x3FFFF
    ir  = (d[3] << 16 | d[4] << 8 | d[5]) & 0x3FFFF
    return red, ir


# ── Heart rate calculation ────────────────────────────
def calc_heart_rate(ir_buffer, sample_rate=25):
    """Simple peak detection on IR signal."""
    if len(ir_buffer) < 30:
        return None

    ir = list(ir_buffer)
    mean = sum(ir) / len(ir)

    # Find peaks: value rises above mean then falls below
    peaks = 0
    above_mean = False
    for v in ir:
        if v > mean and not above_mean:
            peaks += 1
            above_mean = True
        elif v <= mean:
            above_mean = False

    if peaks < 2:
        return None

    # Duration of buffer in seconds
    duration = len(ir) / sample_rate
    bpm = int((peaks / duration) * 60)

    # Sanity check: human HR range
    if 40 <= bpm <= 200:
        return bpm
    return None


# ── SpO2 calculation ──────────────────────────────────
def calc_spo2(ir_buffer, red_buffer):
    """Ratio-of-ratios method."""
    if len(ir_buffer) < 30:
        return None

    ir  = list(ir_buffer)
    red = list(red_buffer)

    ir_dc  = sum(ir)  / len(ir)
    red_dc = sum(red) / len(red)

    ir_ac  = max(ir)  - min(ir)
    red_ac = max(red) - min(red)

    if ir_dc == 0 or red_dc == 0 or ir_ac == 0:
        return None

    R = (red_ac / red_dc) / (ir_ac / ir_dc)

    # Simplified calibration curve (Maxim datasheet approximation)
    spo2 = int(110 - 25 * R)
    return max(80, min(100, spo2))


# ── Visual bar helper ─────────────────────────────────
def bar(value, max_val=262143, width=20):
    filled = int((value / max_val) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


# ── Main loop ─────────────────────────────────────────
def main():
    print()
    print("=" * 54)
    print("   MAX30102 Live Readings")
    print("   Place finger firmly on sensor")
    print("   Press Ctrl+C to stop")
    print("=" * 54)
    print()

    bus = smbus2.SMBus(I2C_BUS)

    # Verify sensor is present
    part_id = bus.read_byte_data(I2C_ADDR, R_PART_ID)
    if part_id != 0x15:
        print(f"   ERROR: Unexpected Part ID 0x{part_id:02X} (expected 0x15)")
        bus.close()
        return

    print(f"   Sensor: MAX30102  Part ID=0x{part_id:02X}  ✓")
    print()

    init_sensor(bus)
    time.sleep(0.5)   # let sensor stabilise

    # Rolling buffers — 100 samples (~4 seconds at effective ~25 sps)
    ir_buf  = collections.deque(maxlen=100)
    red_buf = collections.deque(maxlen=100)

    sample_count = 0
    last_print   = time.time()

    try:
        while True:
            red, ir = read_fifo(bus)
            ir_buf.append(ir)
            red_buf.append(red)
            sample_count += 1

            # Print every 0.25 seconds (every ~6 samples at 25sps)
            now = time.time()
            if now - last_print >= 0.25:
                last_print = now

                finger = ir > FINGER_THRESHOLD

                if not finger:
                    print(
                        f"\r   IR: {ir:>7}  {bar(ir)}  "
                        f"[ No finger detected ]        ",
                        end="", flush=True
                    )
                    continue

                hr   = calc_heart_rate(ir_buf)
                spo2 = calc_spo2(ir_buf, red_buf)

                hr_str   = f"{hr:>3} BPM" if hr   else " -- BPM"
                spo2_str = f"{spo2:>3} %"  if spo2 else " -- %"

                print(
                    f"\r   IR:{ir:>8}  Red:{red:>8}  |  "
                    f"HR: {hr_str}  |  SpO2: {spo2_str}          ",
                    end="", flush=True
                )

            time.sleep(0.04)   # ~25 reads/sec

    except KeyboardInterrupt:
        print("\n")
        print("─" * 54)
        print("   Stopped.")

        if ir_buf:
            hr   = calc_heart_rate(ir_buf)
            spo2 = calc_spo2(ir_buf, red_buf)
            print(f"   Last HR estimate   : {hr if hr else 'N/A'} BPM")
            print(f"   Last SpO2 estimate : {spo2 if spo2 else 'N/A'} %")
            print(f"   Total samples read : {sample_count}")
        print("─" * 54)

    finally:
        bus.close()


if __name__ == "__main__":
    main()
