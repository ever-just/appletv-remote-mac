#!/usr/bin/env python3
"""Translate decoded Siri Remote events into macOS system events.

Buttons -> media keys / keystrokes via Quartz CGEvent + NSEvent (system-defined
media keys). Requires Accessibility permission for the host process.
"""
import time

import Quartz
from AppKit import NSEvent, NSScreen


def _screen_size():
    f = NSScreen.mainScreen().frame()
    return float(f.size.width), float(f.size.height)


SCREEN_W, SCREEN_H = _screen_size()


def mouse_pos():
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return float(loc.x), float(loc.y)


def _post_mouse(kind, x, y, button=0):
    ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), button)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def move_rel(dx, dy):
    x, y = mouse_pos()
    nx = min(max(0.0, x + dx), SCREEN_W - 1)
    ny = min(max(0.0, y + dy), SCREEN_H - 1)
    _post_mouse(Quartz.kCGEventMouseMoved, nx, ny)


def move_abs(x, y):
    x = min(max(0.0, x), SCREEN_W - 1)
    y = min(max(0.0, y), SCREEN_H - 1)
    _post_mouse(Quartz.kCGEventMouseMoved, x, y)


def left_click():
    x, y = mouse_pos()
    _post_mouse(Quartz.kCGEventLeftMouseDown, x, y, Quartz.kCGMouseButtonLeft)
    _post_mouse(Quartz.kCGEventLeftMouseUp, x, y, Quartz.kCGMouseButtonLeft)


def left_down():
    x, y = mouse_pos()
    _post_mouse(Quartz.kCGEventLeftMouseDown, x, y, Quartz.kCGMouseButtonLeft)


def left_up():
    x, y = mouse_pos()
    _post_mouse(Quartz.kCGEventLeftMouseUp, x, y, Quartz.kCGMouseButtonLeft)


def scroll(dy, dx=0):
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitPixel,
                                              2, int(dy), int(dx))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def key_with_mods(keycode, mods=0):
    down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
    Quartz.CGEventSetFlags(down, mods)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
    Quartz.CGEventSetFlags(up, mods)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)

# NX system-defined media key codes
NX_SOUND_UP = 0
NX_SOUND_DOWN = 1
NX_MUTE = 7
NX_BRIGHTNESS_UP = 2
NX_BRIGHTNESS_DOWN = 3
NX_PLAY = 16
NX_NEXT = 17
NX_PREVIOUS = 18

# Virtual keycodes for normal keys
KEY_ESC = 53
KEY_RETURN = 36
KEY_SPACE = 49
KEY_TAB = 48
KEY_LEFT = 123
KEY_RIGHT = 124
KEY_DOWN = 125
KEY_UP = 126
KEY_F11 = 103          # Show Desktop (depends on settings)

# Modifier flag masks (CGEventFlags)
MOD_CMD = Quartz.kCGEventFlagMaskCommand
MOD_SHIFT = Quartz.kCGEventFlagMaskShift
MOD_OPT = Quartz.kCGEventFlagMaskAlternate
MOD_CTRL = Quartz.kCGEventFlagMaskControl


# ── higher-level desktop actions ────────────────────────────────────────────

def right_click():
    x, y = mouse_pos()
    _post_mouse(Quartz.kCGEventRightMouseDown, x, y, Quartz.kCGMouseButtonRight)
    _post_mouse(Quartz.kCGEventRightMouseUp, x, y, Quartz.kCGMouseButtonRight)


def double_click():
    left_click()
    time.sleep(0.05)
    left_click()


def mission_control():
    # Launch Mission Control as an app — reliable regardless of keyboard
    # shortcut settings (Ctrl+Up can be disabled by the user).
    import subprocess
    subprocess.Popen(["open", "-a", "Mission Control"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launchpad():
    import subprocess
    subprocess.Popen(["open", "-a", "Launchpad"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def app_switcher_next():
    # Cmd+Tab cycle. Hold Cmd, tap Tab, release Cmd.
    cmd_down = Quartz.CGEventCreateKeyboardEvent(None, 55, True)  # 55 = Command
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_down)
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, KEY_TAB, down)
        Quartz.CGEventSetFlags(ev, MOD_CMD)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    cmd_up = Quartz.CGEventCreateKeyboardEvent(None, 55, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_up)


def spotlight():
    # Cmd+Space opens Spotlight
    key_with_mods(KEY_SPACE, MOD_CMD)


def siri():
    # Activate Siri (starts listening). Most reliable cross-config trigger.
    import subprocess
    subprocess.Popen(["open", "-a", "Siri"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_desktop():
    # F11 (Show Desktop) — may require keyboard shortcut enabled
    _tap_key(KEY_F11)

# Button bit -> handler name
BIT_AIRPLAY = 0x01
BIT_VOL_UP = 0x02
BIT_VOL_DOWN = 0x04
BIT_PLAY = 0x08
BIT_SIRI = 0x10
BIT_MENU = 0x20
BIT_TOUCH = 0x80

_last_mask = 0


def _post_media_key(key):
    for down in (True, False):
        flags = 0xA00 if down else 0xB00
        data1 = (key << 16) | ((0xA if down else 0xB) << 8)
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14, (0, 0), flags, 0, 0, None, 8, data1, -1
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())


def _tap_key(keycode):
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def handle_buttons(mask):
    """Edge-triggered: act only on newly pressed bits."""
    global _last_mask
    newly = mask & ~_last_mask
    _last_mask = mask
    if newly & BIT_VOL_UP:
        _post_media_key(NX_SOUND_UP)
    if newly & BIT_VOL_DOWN:
        _post_media_key(NX_SOUND_DOWN)
    if newly & BIT_PLAY:
        _post_media_key(NX_PLAY)
    if newly & BIT_MENU:
        _tap_key(KEY_ESC)
    if newly & BIT_TOUCH:
        _tap_key(KEY_RETURN)
    if newly & BIT_AIRPLAY:
        _tap_key(KEY_SPACE)
    # Siri (0x10) intentionally left unmapped for now.


# --- touchpad -> arrow-key swipes (simple gesture detection) ---
_touch_start = None
_last_touch_t = 0


def handle_touch(x, y, raw):
    """Very simple swipe detection: track first/last point per touch session."""
    global _touch_start, _last_touch_t
    now = time.time()
    if _touch_start is None or (now - _last_touch_t) > 0.4:
        _touch_start = (x, y, now)
    _last_touch_t = now
    sx, sy, _ = _touch_start
    dx = x - sx
    dy = y - sy
    THRESH = 300
    if abs(dx) > abs(dy) and abs(dx) > THRESH:
        _tap_key(KEY_RIGHT if dx > 0 else KEY_LEFT)
        _touch_start = (x, y, now)
    elif abs(dy) > THRESH:
        # Y wraps (188..255 then 0..38); treat raw delta loosely.
        _tap_key(KEY_DOWN if dy > 0 else KEY_UP)
        _touch_start = (x, y, now)
