#!/usr/bin/env python3
"""
SmartHelm — UART Diagnostic (stdlib only, no pyserial)
Run: sudo ~/smarthelm-venv/bin/python test_uart.py

Two modes:
  1. Config check  — verifies UART is enabled and not grabbed by console/BT
  2. Loopback test — jumper GPIO14(Pin8) ↔ GPIO15(Pin10), proves Pi UART works
  3. Baud scan     — tries common SIM800L baud rates for an AT response
"""

import os
import time
import termios
import subprocess
import glob

PORT = "/dev/ttyAMA0"

G  = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[94m"; RE = "\033[0m"
def ok(m):   print(f"  {G}✓{RE} {m}")
def bad(m):  print(f"  {R}✗{RE} {m}")
def info(m): print(f"  {B}ℹ{RE} {m}")
def head(t): print(f"\n{'─'*52}\n  {t}\n{'─'*52}")


def configure(fd, baud):
    bmap = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
            57600: termios.B57600, 115200: termios.B115200}
    a = termios.tcgetattr(fd)
    a[0] = 0; a[1] = 0; a[3] = 0
    a[2] |= (termios.CLOCAL | termios.CREAD)
    a[2] &= ~termios.PARENB; a[2] &= ~termios.CSTOPB; a[2] &= ~termios.CSIZE
    a[2] |= termios.CS8
    a[4] = bmap[baud]; a[5] = bmap[baud]
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIOFLUSH)


def read_all(fd, wait=1.0):
    time.sleep(wait)
    buf = b''
    for _ in range(40):
        try:
            c = os.read(fd, 256)
            if c: buf += c
            else: break
        except BlockingIOError:
            time.sleep(0.03)
    return buf


# ── 1. CONFIG CHECK ────────────────────────────────────────
def config_check():
    head("1 — CONFIG CHECK")

    # config.txt
    cfg = ""
    for p in ("/boot/firmware/config.txt", "/boot/config.txt"):
        if os.path.exists(p):
            cfg = open(p).read(); info(f"Reading {p}")
            break
    if "enable_uart=1" in cfg: ok("enable_uart=1 present")
    else: bad("enable_uart=1 MISSING — add it to config.txt")
    if "disable-bt" in cfg: ok("dtoverlay=disable-bt present (UART freed from Bluetooth)")
    else: bad("dtoverlay=disable-bt MISSING — BT is stealing the good UART")

    # cmdline.txt — serial console must NOT be on this port
    for p in ("/boot/firmware/cmdline.txt", "/boot/cmdline.txt"):
        if os.path.exists(p):
            cl = open(p).read()
            if "serial0" in cl or "ttyAMA0" in cl:
                bad("Serial LOGIN CONSOLE active — it grabs the UART!")
                print("       Fix: sudo raspi-config → Interface → Serial Port")
                print("            → login shell over serial? NO  → hardware enabled? YES")
            else:
                ok("No serial console on cmdline (good)")
            break

    # serial-getty service
    r = subprocess.run(["systemctl", "is-active", "serial-getty@ttyAMA0.service"],
                       capture_output=True, text=True)
    if r.stdout.strip() == "active":
        bad("serial-getty@ttyAMA0 is ACTIVE — grabbing the port")
        print("       Fix: sudo systemctl disable --now serial-getty@ttyAMA0.service")
    else:
        ok("serial-getty not active")

    # symlinks
    info("Serial device map:")
    for s in glob.glob("/dev/serial*"):
        try: info(f"   {s} → {os.path.realpath(s)}")
        except Exception: pass
    for d in ("/dev/ttyAMA0", "/dev/ttyAMA10", "/dev/ttyS0"):
        if os.path.exists(d): info(f"   {d} exists")


# ── 2. LOOPBACK TEST ───────────────────────────────────────
def loopback():
    head("2 — LOOPBACK TEST  (jumper Pin8 ↔ Pin10, SIM800L unplugged)")
    info("Sending 'HELLO' out TX — should come back on RX if Pi UART works")
    try:
        fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        configure(fd, 9600)
        msg = b"HELLO-UART\r\n"
        termios.tcflush(fd, termios.TCIFLUSH)
        os.write(fd, msg)
        echo = read_all(fd, 0.5)
        os.close(fd)
        if b"HELLO-UART" in echo:
            ok(f"Loopback received: {echo!r}")
            ok("Pi UART works perfectly → problem is the SIM800L side (power/wiring/module)")
            return True
        else:
            bad(f"Got back: {echo!r}  (expected HELLO-UART)")
            bad("Pi UART NOT echoing → UART not enabled, or wrong port, or jumper not connected")
            return False
    except Exception as e:
        bad(str(e)); return False


# ── 3. BAUD SCAN ───────────────────────────────────────────
def baud_scan():
    head("3 — SIM800L BAUD SCAN  (reconnect SIM800L for this)")
    info("SIM800L may be fixed at a non-9600 baud. Trying common rates…")
    for baud in (9600, 115200, 57600, 38400, 19200):
        try:
            fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            configure(fd, baud)
            time.sleep(0.3)
            # send AT a few times — SIM800L auto-bauds on first chars
            for _ in range(3):
                termios.tcflush(fd, termios.TCIFLUSH)
                os.write(fd, b"AT\r\n")
                resp = read_all(fd, 0.6)
                if b"OK" in resp:
                    os.close(fd)
                    ok(f"GOT 'OK' AT {baud} BAUD!  → set SIM_BAUD={baud}")
                    return baud
            os.close(fd)
            print(f"    {baud:>6} baud → no response")
        except Exception as e:
            print(f"    {baud:>6} baud → error: {e}")
    bad("No AT response at any baud — module not talking (check LED + power)")
    return None


if __name__ == "__main__":
    print(f"\n{B}SmartHelm — UART / SIM800L Diagnostic{RE}")
    config_check()
    print("\n" + "="*52)
    print("  Choose a test:")
    print("    [L] Loopback  (jumper Pin8↔Pin10, SIM800L OUT)")
    print("    [B] Baud scan (SIM800L plugged IN)")
    print("    [Q] Quit")
    choice = input("  > ").strip().lower()
    if choice == "l":
        loopback()
    elif choice == "b":
        baud_scan()
    print()
