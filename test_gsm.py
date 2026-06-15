#!/usr/bin/env python3
"""
test_gsm.py — Full SIM800L / GSM health diagnostic (no SIM needed).

Runs the standard AT-command health battery to prove whether the module's
core is alive BEFORE you buy a SIM:

    AT          → microcontroller alive + serial OK        (expect OK)
    ATI         → manufacturer + model                      (firmware intact)
    AT+CMEE=2   → verbose error reporting on
    AT+CPIN?    → SIM slot detector works  (expect "SIM not inserted")
    AT+CGSN     → 15-digit IMEI            (core processor healthy)
    AT+CSQ      → signal quality           (RF receiver / antenna)
    AT+CREG?    → network registration

Smart: AT is currently silent, so this AUTO-SCANS common baud rates first
and locks onto whichever one the module answers on.

Pure Python stdlib (termios) — no pyserial, works on the offline Pi.

Run:
    sudo ~/smarthelm-venv/bin/python test_gsm.py
"""

import os
import sys
import time
import termios

PORT  = os.environ.get("GSM_PORT", "/dev/ttyAMA0")
BAUDS = [9600, 115200, 57600, 38400, 19200, 4800]

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[94m"; W="\033[1m"; RE="\033[0m"
def ok(m):   print(f"  {G}✓{RE} {m}")
def bad(m):  print(f"  {R}✗{RE} {m}")
def info(m): print(f"  {B}ℹ{RE} {m}")
def head(t): print(f"\n{W}{'─'*54}\n  {t}\n{'─'*54}{RE}")

_BMAP = {4800:termios.B4800, 9600:termios.B9600, 19200:termios.B19200,
         38400:termios.B38400, 57600:termios.B57600, 115200:termios.B115200}


def _safe_flush(fd, which):
    try:
        termios.tcflush(fd, which)
    except (termios.error, OSError):
        pass  # port may be held by a console; drain manually instead


def _drain(fd):
    try:
        while True:
            c = os.read(fd, 256)
            if not c:
                break
    except (BlockingIOError, OSError):
        pass


def open_port(baud):
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0; a[1] = 0; a[3] = 0
    a[2] |= (termios.CLOCAL | termios.CREAD)
    a[2] &= ~termios.PARENB; a[2] &= ~termios.CSTOPB; a[2] &= ~termios.CSIZE
    a[2] |= termios.CS8
    a[4] = _BMAP[baud]; a[5] = _BMAP[baud]
    termios.tcsetattr(fd, termios.TCSANOW, a)
    _safe_flush(fd, termios.TCIOFLUSH)
    return fd


def at(fd, cmd, wait=1.2):
    _drain(fd)
    try:
        os.write(fd, (cmd + "\r\n").encode())
    except OSError as e:
        if e.errno == 5:          # EIO — port held by serial console
            return "__PORT_BUSY__"
        raise
    time.sleep(wait)
    buf = b""
    for _ in range(40):
        try:
            c = os.read(fd, 256)
            if c: buf += c
            else: break
        except BlockingIOError:
            time.sleep(0.03)
        except OSError:
            break
    return buf.decode(errors="ignore").strip()


# ── Step 1: find a baud the module answers on ─────────────────────────
def find_baud():
    head("STEP 1 — FIND WORKING BAUD RATE")
    for baud in BAUDS:
        try:
            fd = open_port(baud)
        except FileNotFoundError:
            bad(f"{PORT} does not exist — set dtoverlay=disable-bt + enable_uart=1, reboot")
            return None, None
        except PermissionError:
            bad(f"Permission denied on {PORT} — run with sudo")
            return None, None

        # SIM800L auto-bauds; send AT a few times to let it sync
        resp = ""
        for _ in range(4):
            resp = at(fd, "AT", 0.6)
            if resp == "__PORT_BUSY__":
                break
            if "OK" in resp or "AT" in resp:
                break
        if resp == "__PORT_BUSY__":
            os.close(fd)
            bad("Serial port is BUSY — the login console is holding /dev/ttyAMA0.")
            print(f"\n   {Y}Free it (permanent fix so it never comes back):{RE}")
            print("     sudo systemctl stop serial-getty@ttyAMA0.service")
            print("     sudo systemctl disable serial-getty@ttyAMA0.service")
            print("     sudo systemctl mask serial-getty@ttyAMA0.service")
            print("   Then check the kernel console isn't on it:")
            print("     cat /boot/firmware/cmdline.txt   # remove any 'console=serial0,115200'")
            print("   Then re-run this test.")
            return None, None
        if "OK" in resp:
            ok(f"Module answered at {W}{baud} baud{RE}")
            return fd, baud
        print(f"    {baud:>6} baud → no response")
        os.close(fd)
    bad("No response at ANY baud rate.")
    return None, None


# ── Step 2: full health battery ───────────────────────────────────────
def diagnose(fd):
    head("STEP 2 — GSM HEALTH BATTERY")
    healthy = True

    # AT
    r = at(fd, "AT")
    if "OK" in r: ok("AT → OK   (microcontroller alive, serial link good)")
    else: bad(f"AT → no OK  ({r!r})"); healthy = False

    # ATI — model
    r = at(fd, "ATI")
    model = next((ln for ln in r.splitlines() if ln and "OK" not in ln and "ATI" not in ln), "")
    info(f"ATI (model)   → {model or r.strip() or '—'}")

    # verbose errors
    at(fd, "AT+CMEE=2")
    info("AT+CMEE=2     → verbose error reporting enabled")

    # SIM slot detector
    r = at(fd, "AT+CPIN?")
    if "not inserted" in r or "10" in r:
        ok("AT+CPIN? → 'SIM not inserted'  (SIM slot detector WORKS ✓ — expected, no SIM)")
    elif "READY" in r:
        ok("AT+CPIN? → READY  (a SIM is present and unlocked)")
    elif "SIM PIN" in r:
        info("AT+CPIN? → SIM PIN required (locked SIM)")
    else:
        info(f"AT+CPIN? → {r.strip() or 'no response'}")

    # IMEI — proves core processor health
    r = at(fd, "AT+CGSN")
    digits = "".join(ch for ch in r if ch.isdigit())
    if len(digits) >= 15:
        ok(f"AT+CGSN (IMEI) → {digits[:15]}  (15-digit IMEI = core processor HEALTHY ✓)")
    else:
        r2 = at(fd, "AT+GSN")
        digits = "".join(ch for ch in r2 if ch.isdigit())
        if len(digits) >= 15:
            ok(f"AT+GSN (IMEI) → {digits[:15]}  (core processor HEALTHY ✓)")
        else:
            bad(f"No valid IMEI  ({r.strip()!r})"); healthy = False

    # signal quality — RF receiver / antenna
    r = at(fd, "AT+CSQ")
    rssi = None
    if "+CSQ:" in r:
        try:
            rssi = int(r.split("+CSQ:")[1].split(",")[0].strip())
        except Exception:
            pass
    if rssi is None:
        info(f"AT+CSQ → {r.strip() or 'no response'}")
    elif rssi == 99:
        info("AT+CSQ → 99 (no signal yet — normal without a SIM/antenna)")
    elif rssi >= 10:
        ok(f"AT+CSQ → {rssi}/31  (RF receiver + antenna WORKING ✓ — catching towers)")
    else:
        info(f"AT+CSQ → {rssi}/31  (weak signal — check antenna)")

    # network registration
    r = at(fd, "AT+CREG?")
    info(f"AT+CREG? (net) → {r.strip() or 'no response'}")

    return healthy


# ── Main ──────────────────────────────────────────────────────────────
def run_simreset():
    """Force the module to reboot and re-read the SIM (no power-cycle needed)."""
    print(f"\n{W}{'═'*54}\n   SIM RE-DETECT — software reset (AT+CFUN=1,1)\n{'═'*54}{RE}")
    fd, _ = find_baud()
    if fd is None:
        return 1
    info("Rebooting the SIM800L to re-read the SIM (AT+CFUN=1,1)...")
    at(fd, "AT+CFUN=1,1", wait=1.0)
    os.close(fd)
    print("   waiting 10s for the module to come back...")
    time.sleep(10)

    fd, _ = find_baud()
    if fd is None:
        bad("Module didn't respond after reset — cut its VCC power, re-power, retry.")
        return 1
    time.sleep(2)
    at(fd, "AT+CMEE=2")          # verbose error reporting ON
    r = at(fd, "AT+CPIN?")
    head("RESULT")
    rl = r.lower()
    if "ready" in rl:
        ok("AT+CPIN? → READY   🎉  SIM DETECTED!")
    elif "not inserted" in rl or "+cme error: 10" in rl:
        bad("AT+CPIN? → 'SIM not inserted' — NO contact at all.")
        print("   → Gold pads face DOWN, chamfer aligned, push FULLY in.")
    elif "sim failure" in rl or "+cme error: 13" in rl:
        bad("AT+CPIN? → 'SIM failure' — partial/dirty contact OR damaged card.")
        print("   → Press SIM firmly, clean gold pads, lift the holder spring-pins.")
        print("   → Test the SIM in a phone to rule out a dead card.")
    elif "sim busy" in rl or "+cme error: 14" in rl:
        info("AT+CPIN? → 'SIM busy' — still initialising. Wait 5s and re-run.")
    elif "sim wrong" in rl or "+cme error: 15" in rl:
        bad("AT+CPIN? → 'SIM wrong' — card not compatible / inserted wrong.")
    elif "error" in rl:
        bad(f"AT+CPIN? → ERROR (intermittent SIM contact). Raw: {r.strip()!r}")
        print("   → Marginal contact: press the SIM in firmly, re-seat, clean pads,")
        print("     and do a REAL power-cycle (cut VCC) with the card seated.")
    else:
        info(f"AT+CPIN? → {r.strip()}")
    info(f"AT+CREG? → {at(fd, 'AT+CREG?').strip()}")
    info(f"AT+CSQ  → {at(fd, 'AT+CSQ').strip()}")
    os.close(fd)
    return 0


if __name__ == "__main__":
    if "--simreset" in sys.argv:
        sys.exit(run_simreset())

    print(f"\n{W}{'═'*54}\n   SmartHelm — GSM / SIM800L Health Test (no SIM)\n{'═'*54}{RE}")
    print(f"   Port: {PORT}\n")

    fd, baud = find_baud()

    if fd is None:
        head("VERDICT")
        bad("Module is NOT communicating over UART.")
        print("   The module may still be ALIVE (LED blinking) — this is a LINK problem.")
        print("   Check, in order:")
        print(f"   {Y}1.{RE} COMMON GROUND — SIM800L GND ↔ Pi Pin 6 must beep on continuity")
        print(f"   {Y}2.{RE} If separate power: battery/buck (–) ↔ Pi Pin 6 must also beep")
        print(f"   {Y}3.{RE} TX/RX crossed — SIM800L TXD→Pi Pin10, SIM800L RXD→Pi Pin8")
        print(f"   {Y}4.{RE} VCC = 3.7–4.2V under load (you measured low before)")
        print(f"   {Y}5.{RE} 1000µF cap across VCC↔GND")
        sys.exit(1)

    healthy = diagnose(fd)
    os.close(fd)

    head("VERDICT")
    if healthy:
        print(f"   {G}{W}GSM MODULE IS HEALTHY ✓{RE}")
        print(f"   Answered at {baud} baud, core processor + serial confirmed working.")
        print(f"   → Safe to buy a SIM. Set SMS_BAUD={baud} in config.py if not 9600.")
    else:
        print(f"   {Y}Module answered but some checks failed — see above.{RE}")
    print()
    sys.exit(0 if healthy else 2)
