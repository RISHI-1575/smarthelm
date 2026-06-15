#!/usr/bin/env python3
"""
SmartHelm — Full Hardware Test
================================
Tests every component and prints PASS / FAIL with fix instructions.

Run:
    sudo ~/smarthelm-venv/bin/python test_hardware.py
"""

import time
import sys
import subprocess

# ── CONFIG ────────────────────────────────────────────
BUZZER_PIN   = 17
MAX_I2C_BUS  = 1
MAX_I2C_ADDR = 0x57
SIM_PORT     = "/dev/ttyAMA0"
SIM_BAUD     = 9600
CAM2_IP      = "10.42.0.173"
CAM3_IP      = "10.42.0.79"

# ── Colours ───────────────────────────────────────────
G  = "\033[92m"   # green
R  = "\033[91m"   # red
Y  = "\033[93m"   # yellow
B  = "\033[94m"   # blue
W  = "\033[1m"    # bold
RE = "\033[0m"    # reset

def ok(msg):   print(f"  {G}✓ PASS{RE}  {msg}")
def fail(msg): print(f"  {R}✗ FAIL{RE}  {msg}")
def info(msg): print(f"  {B}ℹ INFO{RE}  {msg}")
def sep(title):
    print(f"\n{W}{'─'*52}")
    print(f"  {title}")
    print(f"{'─'*52}{RE}")


# ─────────────────────────────────────────────────────
# 1. BUZZER  (GPIO17 — direct 2-pin active buzzer)
# ─────────────────────────────────────────────────────
def test_buzzer():
    sep("TEST 1 — BUZZER  (GPIO17 → long pin, GND → short pin)")
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)

        info("Beeping 3 times …")
        for i in range(3):
            print(f"    Beep {i+1}", end=" ", flush=True)
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(0.35)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.25)
            print("✓")

        GPIO.cleanup()
        answer = input("\n  Did you hear 3 beeps? (y/n): ").strip().lower()
        if answer == 'y':
            ok("Buzzer working")
            return True
        else:
            fail("Buzzer silent")
            print("     Wiring: GPIO17 Pin11 → buzzer long(+)   Pin6 GND → buzzer short(–)")
            return False

    except RuntimeError as e:
        fail(f"GPIO error — run with: sudo ~/smarthelm-venv/bin/python test_hardware.py")
        return False
    except ImportError:
        fail("RPi.GPIO not installed — run: pip install RPi.GPIO")
        return False
    except Exception as e:
        fail(str(e))
        try: import RPi.GPIO as G; G.cleanup()
        except: pass
        return False


# ─────────────────────────────────────────────────────
# 2. I2C BUS SCAN
# ─────────────────────────────────────────────────────
def test_i2c_scan():
    sep("TEST 2 — I2C BUS SCAN")
    r = subprocess.run(['i2cdetect', '-y', '1'], capture_output=True, text=True)
    if r.returncode != 0:
        fail("i2cdetect failed — enable I2C: sudo raspi-config → Interface Options → I2C")
        return False
    print(r.stdout)
    if '57' in r.stdout:
        ok("MAX30102 detected at address 0x57")
        return True
    else:
        fail("Nothing at 0x57 — check: SDA→Pin3  SCL→Pin5  VCC→3.3V(Pin1)  GND→Pin6")
        return False


# ─────────────────────────────────────────────────────
# 3. MAX30102  (Heart Rate + SpO2)
# ─────────────────────────────────────────────────────
def test_max30102():
    sep("TEST 3 — MAX30102  (Heart Rate + SpO2)")
    try:
        import smbus2
        bus = smbus2.SMBus(MAX_I2C_BUS)

        part_id = bus.read_byte_data(MAX_I2C_ADDR, 0xFF)
        rev_id  = bus.read_byte_data(MAX_I2C_ADDR, 0xFE)

        if part_id == 0x15:
            ok(f"Part ID = 0x{part_id:02X}  ✓  Rev = 0x{rev_id:02X}")
        else:
            fail(f"Part ID = 0x{part_id:02X}  (expected 0x15) — wrong sensor?")
            bus.close()
            return False

        # Read die temperature
        bus.write_byte_data(MAX_I2C_ADDR, 0x21, 0x01)
        time.sleep(0.15)
        t_int  = bus.read_byte_data(MAX_I2C_ADDR, 0x1F)
        t_frac = bus.read_byte_data(MAX_I2C_ADDR, 0x20)
        temp_c = t_int + (t_frac * 0.0625)
        info(f"Die temperature: {temp_c:.2f} °C")

        # Enable SpO2 mode and read a few FIFO pointers
        bus.write_byte_data(MAX_I2C_ADDR, 0x09, 0x03)   # SpO2 mode
        bus.write_byte_data(MAX_I2C_ADDR, 0x08, 0x40)   # 4 samples avg
        time.sleep(0.3)
        ptr = bus.read_byte_data(MAX_I2C_ADDR, 0x07)
        info(f"FIFO write pointer: {ptr}  (non-zero = sensor clocking data)")

        bus.close()
        ok("MAX30102 fully responding")
        return True

    except FileNotFoundError:
        fail("I2C bus /dev/i2c-1 not found — enable I2C: sudo raspi-config")
        return False
    except OSError as e:
        fail(f"No response at 0x57 — check SDA/SCL wiring and VCC=3.3V  ({e})")
        return False
    except ImportError:
        fail("smbus2 not installed — run: pip install smbus2")
        return False
    except Exception as e:
        fail(str(e))
        return False


# ─────────────────────────────────────────────────────
# 4. PI CAMERA  (CSI ribbon)
# ─────────────────────────────────────────────────────
def test_camera():
    sep("TEST 4 — PI CAMERA  (CSI)")
    import os

    # List cameras
    r = subprocess.run(['rpicam-still', '--list-cameras'],
                       capture_output=True, text=True, timeout=8)
    output = r.stdout + r.stderr
    if 'OV5647' in output or 'imx' in output.lower() or 'Available cameras' in output:
        ok("Camera detected by libcamera")
        info(output.strip().splitlines()[0] if output.strip() else "")
    else:
        info(f"libcamera output: {output.strip()[:120]}")

    # Capture test photo
    path = '/tmp/smarthelm_cam_test.jpg'
    info(f"Capturing photo → {path} …")
    r = subprocess.run(
        ['rpicam-still', '-o', path, '--nopreview', '-t', '500'],
        capture_output=True, text=True, timeout=20
    )
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        kb = os.path.getsize(path) // 1024
        ok(f"Photo captured  ({kb} KB)")
        info(f"Copy to Mac:  scp vyrrs@10.42.0.1:{path} ~/Desktop/cam_test.jpg")
        return True
    else:
        fail("Photo capture failed")
        print(f"     stderr: {r.stderr.strip()[:200]}")
        print("     Fix: sudo raspi-config → Interface Options → Legacy Camera (or check ribbon cable)")
        return False


# ─────────────────────────────────────────────────────
# 5. ESP32-CAMs  (CAM2 + CAM3)
# ─────────────────────────────────────────────────────
def test_esp32_cams():
    sep("TEST 5 — ESP32-CAMs  (CAM2 + CAM3)")
    import urllib.request

    # Try /capture on port 80, fallback to port 81
    cams = [
        (CAM2_IP, "CAM2 — Road Ahead"),
        (CAM3_IP, "CAM3 — Rear Traffic"),
    ]
    all_ok = True
    for ip, label in cams:
        endpoints = [
            f"http://{ip}/capture",
            f"http://{ip}:81/capture",
            f"http://{ip}:80/capture",
        ]
        found = False
        for url in endpoints:
            print(f"  {label} — trying {url} …", end=" ", flush=True)
            try:
                r    = urllib.request.urlopen(url, timeout=4)
                data = r.read(64)
                if data[:2] == b'\xff\xd8':
                    print(f"{G}LIVE JPEG ✓{RE}")
                    ok(f"{label} streaming")
                    found = True
                    break
                else:
                    print(f"{Y}reachable, not JPEG{RE}")
                    found = True
                    break
            except urllib.error.HTTPError as e:
                print(f"{Y}HTTP {e.code}{RE}")
                found = True
                break
            except Exception:
                print(f"{R}✗{RE}")

        if not found:
            fail(f"{label} ({ip}) not reachable on any port")
            print(f"     → Is it powered and on Pi hotspot?")
            print(f"     → Confirm IP:  nmap -sn 10.42.0.0/24")
            all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# 6. SIM800L  (GSM UART)  — pure stdlib, no pyserial needed
# ─────────────────────────────────────────────────────
def test_sim800l():
    sep("TEST 6 — SIM800L  (UART /dev/ttyAMA0)")
    import os, termios

    fd = None
    try:
        info(f"Opening {SIM_PORT} @ {SIM_BAUD} baud  (stdlib termios)…")
        fd = os.open(SIM_PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

        # Configure UART: 8N1, raw mode, given baud
        baud_const = {
            9600: termios.B9600,   19200: termios.B19200,
            38400: termios.B38400, 57600: termios.B57600,
            115200: termios.B115200,
        }[SIM_BAUD]
        attrs = termios.tcgetattr(fd)            # [iflag,oflag,cflag,lflag,ispeed,ospeed,cc]
        attrs[0] = 0                              # iflag: raw input
        attrs[1] = 0                              # oflag: raw output
        attrs[3] = 0                              # lflag: no echo/canonical
        attrs[2] |= (termios.CLOCAL | termios.CREAD)
        attrs[2] &= ~termios.PARENB               # no parity
        attrs[2] &= ~termios.CSTOPB               # 1 stop bit
        attrs[2] &= ~termios.CSIZE
        attrs[2] |= termios.CS8                   # 8 data bits
        attrs[4] = baud_const                     # ispeed
        attrs[5] = baud_const                     # ospeed
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        time.sleep(0.5)

        def at(cmd, wait=1.2):
            termios.tcflush(fd, termios.TCIFLUSH)
            os.write(fd, (cmd + '\r\n').encode())
            time.sleep(wait)
            buf = b''
            for _ in range(20):
                try:
                    chunk = os.read(fd, 256)
                    if chunk:
                        buf += chunk
                    else:
                        break
                except BlockingIOError:
                    time.sleep(0.05)
            return buf.decode(errors='ignore').strip()

        r = at('AT')
        if 'OK' not in r:
            fail(f"No OK from AT  (got: '{r[:60]}')")
            print("     Fix: add to /boot/firmware/config.txt:")
            print("            dtoverlay=disable-bt")
            print("            enable_uart=1")
            print("          then: sudo reboot")
            print("     Also check: TX/RX not swapped, SIM800L has its own power + 1000µF cap")
            return False

        ok("AT → OK  (SIM800L alive)")

        r = at('ATI')
        info(f"Model:  {r.splitlines()[0] if r else '—'}")

        r = at('AT+CSQ')
        info(f"Signal: {r.strip()}" + ("  ⚠ no SIM/signal" if '99,99' in r else ""))

        r = at('AT+CPIN?')
        if 'READY' in r:
            ok("SIM card ready")
        elif 'SIM PIN' in r:
            info("SIM needs PIN — use an unlocked SIM")
        else:
            info(f"SIM status: {r.strip() or 'no SIM inserted'}")

        r = at('AT+CREG?')
        info(f"Network reg: {r.strip()}")

        ok("SIM800L test done")
        return True

    except FileNotFoundError:
        fail(f"{SIM_PORT} does not exist — add dtoverlay=disable-bt + enable_uart=1 then reboot")
        return False
    except PermissionError:
        fail(f"Permission denied on {SIM_PORT} — run with sudo")
        return False
    except Exception as e:
        fail(str(e))
        return False
    finally:
        if fd is not None:
            os.close(fd)


# ─────────────────────────────────────────────────────
# 7. SYSTEM HEALTH
# ─────────────────────────────────────────────────────
def test_system():
    sep("TEST 7 — SYSTEM HEALTH")

    # Throttle / under-voltage
    r = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True)
    val = r.stdout.strip()
    info(f"Throttle: {val}")
    if 'throttled=0x0' in val:
        ok("No under-voltage — power supply healthy")
    else:
        fail("Under-voltage detected!  Use 5.1V 3A+ supply")

    # CPU temp
    r = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True)
    info(f"CPU temp:  {r.stdout.strip()}")

    # Memory
    r = subprocess.run(['free', '-h'], capture_output=True, text=True)
    for line in r.stdout.strip().splitlines()[:2]:
        info(line)

    # Disk
    r = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
    for line in r.stdout.strip().splitlines()[1:]:
        info(f"Disk: {line}")

    return True


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f"\n{W}{'═'*52}")
    print("   SmartHelm — Full Hardware Test")
    print(f"{'═'*52}{RE}")
    print("   Run as:  sudo ~/smarthelm-venv/bin/python test_hardware.py\n")

    results = {
        "Buzzer    (GPIO17)"    : test_buzzer(),
        "I2C Scan"              : test_i2c_scan(),
        "MAX30102  (0x57)"      : test_max30102(),
        "Pi Camera (CSI)"       : test_camera(),
        "ESP32-CAMs (WiFi)"     : test_esp32_cams(),
        "SIM800L  (UART)"       : test_sim800l(),
        "System Health"         : test_system(),
    }

    sep("SUMMARY")
    all_pass = True
    for name, passed in results.items():
        icon = f"{G}✓ PASS{RE}" if passed else f"{R}✗ FAIL{RE}"
        print(f"  {icon}   {name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print(f"  {G}{W}All components OK — SmartHelm is ready!{RE}\n")
    else:
        print(f"  {Y}Fix the FAIL items above, then re-run this script.{RE}\n")

    sys.exit(0 if all_pass else 1)
