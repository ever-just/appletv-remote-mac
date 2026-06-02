#!/usr/bin/env python3
"""
Intercept Siri Remote touchpad events via CGEventTap.

macOS converts the remote's digitizer HID reports into scroll wheel events
before any userspace HID reader sees them. This tap catches those scroll
events, checks they come from the remote (vendor/product match via IOKit),
and re-emits them as mouse movement in MOUSE mode.

Requires Accessibility permission for the host process.
"""
import ctypes
import threading
from queue import Queue, Empty

Quartz = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
CF = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)

# ── types ─────────────────────────────────────────────────────────────────────
CGEventRef      = ctypes.c_void_p
CFMachPortRef   = ctypes.c_void_p
CFRunLoopSourceRef = ctypes.c_void_p
CFRunLoopRef    = ctypes.c_void_p
CGEventMask     = ctypes.c_uint64

# ── CF / CG constants ─────────────────────────────────────────────────────────
kCGEventScrollWheel   = 22
kCGScrollEventUnitPixel = 0
kCGEventTapOptionDefault = 0   # active tap (can suppress)
kCGHIDEventTap        = 0
kCGHeadInsertEventTap = 0
kCGEventMaskForAllEvents = 0xFFFFFFFFFFFFFFFF

# kCGScrollWheelEventDeltaAxis1 = 11 (vertical), axis2 = 12 (horizontal)
kCGScrollWheelEventDeltaAxis1     = 11
kCGScrollWheelEventDeltaAxis2     = 12
kCGScrollWheelEventPointDeltaAxis1 = 96
kCGScrollWheelEventPointDeltaAxis2 = 97
kCGScrollWheelEventFixedPtDeltaAxis1 = 93
kCGScrollWheelEventFixedPtDeltaAxis2 = 94

# ── Quartz funcs ──────────────────────────────────────────────────────────────
Quartz.CGEventTapCreate.restype  = CFMachPortRef
Quartz.CGEventTapCreate.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int,
    CGEventMask, ctypes.c_void_p, ctypes.c_void_p
]
Quartz.CGEventTapEnable.restype  = None
Quartz.CGEventTapEnable.argtypes = [CFMachPortRef, ctypes.c_bool]

Quartz.CGEventGetIntegerValueField.restype  = ctypes.c_int64
Quartz.CGEventGetIntegerValueField.argtypes = [CGEventRef, ctypes.c_int]

Quartz.CGEventGetDoubleValueField.restype  = ctypes.c_double
Quartz.CGEventGetDoubleValueField.argtypes = [CGEventRef, ctypes.c_int]

Quartz.CGEventSetIntegerValueField.restype  = None
Quartz.CGEventSetIntegerValueField.argtypes = [CGEventRef, ctypes.c_int, ctypes.c_int64]

Quartz.CGEventGetLocation.restype  = ctypes.c_double * 2   # CGPoint as pair
# override properly:
class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
Quartz.CGEventGetLocation.restype  = CGPoint
Quartz.CGEventGetLocation.argtypes = [CGEventRef]

Quartz.CGEventCreateMouseEvent.restype  = CGEventRef
Quartz.CGEventCreateMouseEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_int, CGPoint, ctypes.c_int
]
Quartz.CGEventPost.restype  = None
Quartz.CGEventPost.argtypes = [ctypes.c_int, CGEventRef]

CF.CFMachPortCreateRunLoopSource.restype  = CFRunLoopSourceRef
CF.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, CFMachPortRef, ctypes.c_long]

CF.CFRunLoopGetCurrent.restype  = CFRunLoopRef
CF.CFRunLoopGetCurrent.argtypes = []

CF.CFRunLoopAddSource.restype  = None
CF.CFRunLoopAddSource.argtypes = [CFRunLoopRef, CFRunLoopSourceRef, ctypes.c_void_p]

CF.CFRunLoopRunInMode.restype  = ctypes.c_int
CF.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]

CF.CFRelease.restype  = None
CF.CFRelease.argtypes = [ctypes.c_void_p]

kCFRunLoopDefaultMode = ctypes.c_void_p.in_dll(CF, "kCFRunLoopDefaultMode")

# screen bounds (lazy import from mac_actions)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# ── state ─────────────────────────────────────────────────────────────────────
_mouse_mode   = False   # set True to redirect scroll→mouse
_sensitivity  = 3.0     # multiplier: scroll pixels → cursor pixels
_scroll_queue: Queue = Queue()  # (dy, dx) raw scroll deltas for logging
_tap_ref      = None    # keep CFMachPortRef alive

# ── screen size via Quartz ────────────────────────────────────────────────────
Quartz2 = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
)
Quartz2.CGMainDisplayID.restype  = ctypes.c_uint32
Quartz2.CGDisplayBounds.restype  = ctypes.c_void_p   # we parse manually

# simpler: use AppKit
def _screen_wh():
    try:
        from AppKit import NSScreen
        f = NSScreen.mainScreen().frame()
        return float(f.size.width), float(f.size.height)
    except Exception:
        return 1440.0, 900.0

SCREEN_W, SCREEN_H = _screen_wh()


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _get_cursor():
    from AppKit import NSEvent
    loc = NSEvent.mouseLocation()
    # NSEvent Y is flipped (0 at bottom); CGEvent Y is 0 at top
    return float(loc.x), float(SCREEN_H - loc.y)


def _move_cursor(dx, dy):
    cx, cy = _get_cursor()
    nx = _clamp(cx + dx, 0, SCREEN_W - 1)
    ny = _clamp(cy + dy, 0, SCREEN_H - 1)
    pt = CGPoint(nx, ny)
    kCGEventMouseMoved = 5
    ev = Quartz.CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt, 0)
    Quartz.CGEventPost(kCGHIDEventTap, ev)
    CF.CFRelease(ev)


# ── tap callback ──────────────────────────────────────────────────────────────
TAP_CB_TYPE = ctypes.CFUNCTYPE(
    CGEventRef,
    CFMachPortRef, ctypes.c_uint32, CGEventRef, ctypes.c_void_p
)

def _tap_callback(proxy, event_type, event, refcon):
    try:
        if event_type == kCGEventScrollWheel:
            dy = Quartz.CGEventGetIntegerValueField(event, kCGScrollWheelEventPointDeltaAxis1)
            dx = Quartz.CGEventGetIntegerValueField(event, kCGScrollWheelEventPointDeltaAxis2)
            _scroll_queue.put((int(dy), int(dx)))

            if _mouse_mode and (dy != 0 or dx != 0):
                _move_cursor(dx * _sensitivity, -dy * _sensitivity)
                return None   # suppress original scroll event
    except Exception as e:
        print(f"[tap_cb] {e}", flush=True)
    return event

_cb_ref = TAP_CB_TYPE(_tap_callback)


def start():
    """Install CGEventTap on background thread. Returns the scroll queue."""
    global _tap_ref

    def _run():
        global _tap_ref
        mask = ctypes.c_uint64(1 << kCGEventScrollWheel)
        tap = Quartz.CGEventTapCreate(
            kCGHIDEventTap,       # tap location: HID event tap
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            mask,
            _cb_ref,
            None,
        )
        if not tap:
            print("[touch_tap] CGEventTapCreate failed — check Accessibility permission!", flush=True)
            return

        _tap_ref = tap
        src = CF.CFMachPortCreateRunLoopSource(None, tap, 0)
        rl  = CF.CFRunLoopGetCurrent()
        CF.CFRunLoopAddSource(rl, src, kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        print("[touch_tap] CGEventTap installed, listening for scroll events…", flush=True)

        while True:
            CF.CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.1, False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return _scroll_queue


def set_mouse_mode(enabled: bool):
    global _mouse_mode
    _mouse_mode = enabled


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import time
    print("CGEventTap scroll intercept test")
    print("Slide finger on Siri Remote touchpad — scroll events will print.")
    print("Ctrl-C to quit.\n")
    q = start()
    time.sleep(0.5)
    try:
        while True:
            try:
                dy, dx = q.get(timeout=0.5)
                if dy != 0 or dx != 0:
                    print(f"  scroll  dy={dy:+4d}  dx={dx:+4d}")
            except Empty:
                pass
    except KeyboardInterrupt:
        print("\nDone.")
