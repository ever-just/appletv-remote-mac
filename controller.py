#!/usr/bin/env python3
"""
Siri Remote Controller (button edition)
=======================================
Reads HID button reports from the Bluetooth-paired Siri Remote (vid=0x004C
pid=0x026D) and maps every button to macOS actions, with TAP vs HOLD and two
modes. (The touchpad SLIDE is exclusively claimed by macOS's kernel HID driver
and is unreachable from userspace — see README. The touchpad CLICK works.)

Two modes, toggle by HOLDING Menu (~0.5s):
  MEDIA mode (default) — playback, volume, brightness, Mission Control, Siri
  NAV mode             — buttons become arrow keys + Enter for navigating and
                         selecting menus, windows and the UI.

MEDIA mode:
  Vol+   tap=Volume Up      hold=Brightness Up
  Vol-   tap=Volume Down    hold=Brightness Down
  Play   tap=Play/Pause     hold=Next Track
  Click  tap=Left Click     hold=Right Click
  Menu   tap=Escape         hold=switch to NAV mode
  TV     tap=Mission Control hold=Show Desktop
  Siri   tap=Spotlight      hold=App Switcher (Cmd-Tab)

NAV mode:
  Vol+   tap=Up arrow       hold=Page Up
  Vol-   tap=Down arrow     hold=Page Down
  TV     tap=Left arrow
  Play   tap=Right arrow
  Click  tap=Enter/Select   hold=Left Click
  Menu   tap=Escape         hold=switch to MEDIA mode
  Siri   tap=Spotlight

Run:
  python3 controller.py

Requires:
  pip install hidapi pyobjc-framework-Quartz pyobjc-framework-AppKit
  macOS permissions: Input Monitoring + Accessibility for the host process.
"""

import sys
import time
import signal

import hid

VID = 0x004C
PID = 0x026D

# ── interface selectors ────────────────────────────────────────────────────────
# Button bitmask report  (usage_page=0x0c, usage=0x01)
IFACE_BTN = (0x0c, 0x01)
# Digitizer / touch      (usage_page=0x0d, usage=0x01)
IFACE_TOUCH = (0x0d, 0x01)
# Vendor / extra buttons (usage_page=0xff00)
IFACE_VENDOR_10 = (0xff00, 0x10)
IFACE_VENDOR_0B = (0xff00, 0x0b)

# ── button bitmask constants ───────────────────────────────────────────────────
BIT_AIRPLAY  = 0x01
BIT_VOL_UP   = 0x02
BIT_VOL_DOWN = 0x04
BIT_PLAY     = 0x08
BIT_SIRI     = 0x10
BIT_MENU     = 0x20
BIT_TOUCH_CK = 0x80   # touchpad physical click

# ── modes ─────────────────────────────────────────────────────────────────────
MEDIA_MODE = "MEDIA"
NAV_MODE   = "NAV"
mode = MEDIA_MODE

HOLD_THRESHOLD = 0.5   # seconds; press longer than this = HOLD

# ── state ─────────────────────────────────────────────────────────────────────
_last_mask   = 0
_press_time  = {}      # bit -> timestamp when pressed

# ── mac_actions import (lazy so we can enumerate first) ───────────────────────
import mac_actions as M

# Map of bit -> friendly name (for logging)
BTN_NAMES = {
    BIT_AIRPLAY: "TV", BIT_VOL_UP: "Vol+", BIT_VOL_DOWN: "Vol-",
    BIT_PLAY: "Play", BIT_SIRI: "Siri", BIT_MENU: "Menu",
    BIT_TOUCH_CK: "Click",
}


# ══════════════════════════════════════════════════════════════════════════════
#  HID open helpers
# ══════════════════════════════════════════════════════════════════════════════

def open_interfaces():
    devs = hid.enumerate(VID, PID)
    if not devs:
        print("[ERROR] Remote not found. Make sure it's connected via Bluetooth.", flush=True)
        sys.exit(1)

    handles = {}
    for d in devs:
        key = (d.get("usage_page", 0), d.get("usage", 0))
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(True)
            handles[key] = h
            print(f"  opened {hex(key[0])}:{hex(key[1])}", flush=True)
        except Exception as e:
            print(f"  could not open {hex(key[0])}:{hex(key[1])}: {e}", flush=True)
    return handles


# ══════════════════════════════════════════════════════════════════════════════
#  Report decoders
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  Action handlers (tap / hold) per mode
# ══════════════════════════════════════════════════════════════════════════════

def _do_media(bit, held):
    """Dispatch a MEDIA-mode action for a button bit. Returns label for logging."""
    global mode
    if bit == BIT_VOL_UP:
        M._post_media_key(M.NX_BRIGHTNESS_UP if held else M.NX_SOUND_UP)
        return "Brightness Up" if held else "Volume Up"
    if bit == BIT_VOL_DOWN:
        M._post_media_key(M.NX_BRIGHTNESS_DOWN if held else M.NX_SOUND_DOWN)
        return "Brightness Down" if held else "Volume Down"
    if bit == BIT_PLAY:
        M._post_media_key(M.NX_NEXT if held else M.NX_PLAY)
        return "Next Track" if held else "Play/Pause"
    if bit == BIT_TOUCH_CK:
        M.right_click() if held else M.left_click()
        return "Right Click" if held else "Left Click"
    if bit == BIT_AIRPLAY:
        M.launchpad() if held else M.mission_control()
        return "Launchpad" if held else "Mission Control"
    if bit == BIT_SIRI:
        M.spotlight() if held else M.siri()
        return "Spotlight" if held else "Siri"
    if bit == BIT_MENU:
        if held:
            mode = NAV_MODE
            return "→ NAV mode"
        M._tap_key(M.KEY_ESC)
        return "Escape"
    return None


def _do_nav(bit, held):
    """Dispatch a NAV-mode action for a button bit. Returns label for logging."""
    global mode
    if bit == BIT_VOL_UP:
        M._tap_key(116) if held else M._tap_key(M.KEY_UP)   # 116 = Page Up
        return "Page Up" if held else "Up"
    if bit == BIT_VOL_DOWN:
        M._tap_key(121) if held else M._tap_key(M.KEY_DOWN)  # 121 = Page Down
        return "Page Down" if held else "Down"
    if bit == BIT_AIRPLAY:
        M._tap_key(M.KEY_LEFT)
        return "Left"
    if bit == BIT_PLAY:
        M._tap_key(M.KEY_RIGHT)
        return "Right"
    if bit == BIT_TOUCH_CK:
        M.left_click() if held else M._tap_key(M.KEY_RETURN)
        return "Left Click" if held else "Enter/Select"
    if bit == BIT_SIRI:
        M.spotlight() if held else M.siri()
        return "Spotlight" if held else "Siri"
    if bit == BIT_MENU:
        if held:
            mode = MEDIA_MODE
            return "→ MEDIA mode"
        M._tap_key(M.KEY_ESC)
        return "Escape"
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Debounced press/hold detection (handles the remote's autorepeat)
# ──────────────────────────────────────────────────────────────────────────────
# The remote AUTOREPEATS held buttons as rapid press/release cycles. We collapse
# those into one logical press: a release is only "real" if no new press of the
# same bit arrives within DEBOUNCE seconds. Hold duration is measured from the
# FIRST press to the final real release.
# ══════════════════════════════════════════════════════════════════════════════

DEBOUNCE = 0.18   # seconds; autorepeat gap is much shorter than this

_btn_down            = {}   # bit -> first_press_time (while logically down)
_btn_release_pending = {}   # bit -> last_release_time (awaiting debounce)


def on_buttons(mask):
    global _last_mask
    newly_pressed  = mask & (~_last_mask & 0xFF)
    newly_released = _last_mask & (~mask & 0xFF)
    _last_mask = mask

    now = time.time()
    for bit in BTN_NAMES:
        if newly_pressed & bit:
            # cancel any pending release (this press is autorepeat continuation)
            _btn_release_pending.pop(bit, None)
            if bit not in _btn_down:
                _btn_down[bit] = now
        if newly_released & bit:
            _btn_release_pending[bit] = now


def poll_releases():
    """Finalize debounced releases; called frequently from the main loop."""
    now = time.time()
    for bit in list(_btn_release_pending):
        rel_t = _btn_release_pending[bit]
        if now - rel_t >= DEBOUNCE:
            press_t = _btn_down.get(bit, rel_t)
            held = (rel_t - press_t) >= HOLD_THRESHOLD
            label = _do_media(bit, held) if mode == MEDIA_MODE else _do_nav(bit, held)
            kind = "HOLD" if held else "tap"
            print(f"  [{mode}] {BTN_NAMES[bit]} ({kind}) -> {label}", flush=True)
            _btn_release_pending.pop(bit, None)
            _btn_down.pop(bit, None)


# ══════════════════════════════════════════════════════════════════════════════
#  Main loop
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global mode

    print("Siri Remote Controller starting …", flush=True)
    print("Opening HID interfaces:", flush=True)
    handles = open_interfaces()

    if IFACE_BTN not in handles:
        print("[ERROR] Button interface not found. Check Input Monitoring permission.", flush=True)
        sys.exit(1)

    print(f"\nRunning in {mode} mode. Tap=quick press, HOLD=press >{HOLD_THRESHOLD}s.", flush=True)
    print("  Menu HOLD       = switch MEDIA <-> NAV mode", flush=True)
    print("  MEDIA: Vol+/-=volume (hold=brightness), Play=play/pause (hold=next),", flush=True)
    print("         Click=left click (hold=right), TV=Mission Control (hold=Launchpad),", flush=True)
    print("         Siri=Siri assistant (hold=Spotlight), Menu tap=Escape", flush=True)
    print("  NAV:   Vol+/-=Up/Down, TV=Left, Play=Right, Click=Enter (hold=click),", flush=True)
    print("         Siri=Siri assistant (hold=Spotlight), Menu tap=Escape", flush=True)
    print("\nCtrl-C to quit.\n", flush=True)

    def _shutdown(sig, frame):
        print("\nShutting down.", flush=True)
        for h in handles.values():
            try: h.close()
            except Exception: pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    btn = handles[IFACE_BTN]
    btn.set_nonblocking(True)
    while True:
        try:
            data = btn.read(64)
        except OSError:
            data = []
        if data:
            mask = data[1] if len(data) >= 2 else 0
            on_buttons(mask)
        poll_releases()
        time.sleep(0.005)


if __name__ == "__main__":
    main()
