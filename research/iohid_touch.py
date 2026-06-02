#!/usr/bin/env python3
"""
Use IOHIDManager (via ctypes + IOKit) to intercept digitizer reports
from the Siri Remote touchpad at the kernel level, bypassing hidd's
exclusive claim on the hidapi interface.

Run standalone to verify touch data arrives; controller.py will import
the decoded (x, y) via a queue.
"""
import ctypes
import ctypes.util
import threading
import time
from queue import Queue, Empty

# ── load frameworks ────────────────────────────────────────────────────────────
IOKit   = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
CF      = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

# ── CF types ──────────────────────────────────────────────────────────────────
CFStringRef        = ctypes.c_void_p
CFDictionaryRef    = ctypes.c_void_p
CFNumberRef        = ctypes.c_void_p
CFRunLoopRef       = ctypes.c_void_p
CFRunLoopSourceRef = ctypes.c_void_p

IOHIDManagerRef    = ctypes.c_void_p
IOHIDDeviceRef     = ctypes.c_void_p
IOHIDValueRef      = ctypes.c_void_p
IOHIDElementRef    = ctypes.c_void_p
IOOptionBits       = ctypes.c_uint32

kCFRunLoopDefaultMode = ctypes.c_void_p.in_dll(CF, "kCFRunLoopDefaultMode")

kIOHIDOptionsTypeNone          = 0
kIOHIDOptionsTypeSeizeDevice   = 1
kIOReturnSuccess               = 0

kIOHIDDeviceUsagePageKey = b"DeviceUsagePage"
kIOHIDDeviceUsageKey     = b"DeviceUsage"
kIOHIDVendorIDKey        = b"VendorID"
kIOHIDProductIDKey       = b"ProductID"

VID = 0x004C   # Apple
PID = 0x026D   # Siri Remote A1962

USAGE_PAGE_DIGITIZER = 0x0D
USAGE_TOUCHPAD       = 0x05   # Touchpad usage within digitizer page
USAGE_FINGER         = 0x22

# ── CF helpers ────────────────────────────────────────────────────────────────
CF.CFStringCreateWithCString.restype  = CFStringRef
CF.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]

CF.CFNumberCreate.restype  = CFNumberRef
CF.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]

CF.CFDictionaryCreate.restype  = CFDictionaryRef
CF.CFDictionaryCreate.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_long,
    ctypes.c_void_p, ctypes.c_void_p
]
CF.CFDictionaryGetValue.restype  = ctypes.c_void_p
CF.CFDictionaryGetValue.argtypes = [CFDictionaryRef, CFStringRef]

CF.CFNumberGetValue.restype  = ctypes.c_bool
CF.CFNumberGetValue.argtypes = [CFNumberRef, ctypes.c_int, ctypes.c_void_p]

CF.CFRunLoopGetCurrent.restype  = CFRunLoopRef
CF.CFRunLoopGetCurrent.argtypes = []

CF.CFRunLoopRunInMode.restype  = ctypes.c_int
CF.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]

CF.CFRelease.restype  = None
CF.CFRelease.argtypes = [ctypes.c_void_p]

# ── IOHIDManager ──────────────────────────────────────────────────────────────
IOKit.IOHIDManagerCreate.restype  = IOHIDManagerRef
IOKit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, IOOptionBits]

IOKit.IOHIDManagerSetDeviceMatching.restype  = None
IOKit.IOHIDManagerSetDeviceMatching.argtypes = [IOHIDManagerRef, CFDictionaryRef]

IOKit.IOHIDManagerScheduleWithRunLoop.restype  = None
IOKit.IOHIDManagerScheduleWithRunLoop.argtypes = [IOHIDManagerRef, CFRunLoopRef, ctypes.c_void_p]

IOKit.IOHIDManagerOpen.restype  = ctypes.c_int
IOKit.IOHIDManagerOpen.argtypes = [IOHIDManagerRef, IOOptionBits]

IOKit.IOHIDManagerRegisterInputValueCallback.restype  = None
IOKit.IOHIDManagerRegisterInputValueCallback.argtypes = [
    IOHIDManagerRef, ctypes.c_void_p, ctypes.c_void_p
]

IOKit.IOHIDManagerRegisterInputReportCallback.restype  = None
IOKit.IOHIDManagerRegisterInputReportCallback.argtypes = [
    IOHIDManagerRef, ctypes.c_void_p, ctypes.c_void_p
]

IOKit.IOHIDDeviceRegisterInputReportCallback.restype  = None
IOKit.IOHIDDeviceRegisterInputReportCallback.argtypes = [
    IOHIDDeviceRef, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.c_void_p, ctypes.c_void_p
]

IOKit.IOHIDManagerRegisterDeviceMatchingCallback.restype  = None
IOKit.IOHIDManagerRegisterDeviceMatchingCallback.argtypes = [
    IOHIDManagerRef, ctypes.c_void_p, ctypes.c_void_p
]

IOKit.IOHIDValueGetElement.restype  = IOHIDElementRef
IOKit.IOHIDValueGetElement.argtypes = [IOHIDValueRef]

IOKit.IOHIDValueGetIntegerValue.restype  = ctypes.c_long
IOKit.IOHIDValueGetIntegerValue.argtypes = [IOHIDValueRef]

IOKit.IOHIDElementGetUsagePage.restype  = ctypes.c_uint32
IOKit.IOHIDElementGetUsagePage.argtypes = [IOHIDElementRef]

IOKit.IOHIDElementGetUsage.restype  = ctypes.c_uint32
IOKit.IOHIDElementGetUsage.argtypes = [IOHIDElementRef]

IOKit.IOHIDElementGetLogicalMin.restype  = ctypes.c_long
IOKit.IOHIDElementGetLogicalMin.argtypes = [IOHIDElementRef]

IOKit.IOHIDElementGetLogicalMax.restype  = ctypes.c_long
IOKit.IOHIDElementGetLogicalMax.argtypes = [IOHIDElementRef]

# kCFNumberSInt32Type = 3
kCFNumberSInt32Type = 3
# kCFStringEncodingUTF8 = 0x08000100
kCFStringEncodingUTF8 = 0x08000100

kCFTypeDictionaryKeyCallBacks   = ctypes.c_void_p.in_dll(CF, "kCFTypeDictionaryKeyCallBacks")
kCFTypeDictionaryValueCallBacks = ctypes.c_void_p.in_dll(CF, "kCFTypeDictionaryValueCallBacks")


def _cf_str(s: bytes) -> CFStringRef:
    return CF.CFStringCreateWithCString(None, s, kCFStringEncodingUTF8)


def _cf_int(n: int) -> CFNumberRef:
    v = ctypes.c_int32(n)
    return CF.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(v))


def _make_matching_dict(vid: int, pid: int) -> CFDictionaryRef:
    keys = [
        _cf_str(kIOHIDVendorIDKey),
        _cf_str(kIOHIDProductIDKey),
    ]
    vals = [
        _cf_int(vid),
        _cf_int(pid),
    ]
    k_arr = (ctypes.c_void_p * len(keys))(*keys)
    v_arr = (ctypes.c_void_p * len(vals))(*vals)
    d = CF.CFDictionaryCreate(
        None, k_arr, v_arr, len(keys),
        ctypes.byref(kCFTypeDictionaryKeyCallBacks),
        ctypes.byref(kCFTypeDictionaryValueCallBacks),
    )
    for k in keys: CF.CFRelease(k)
    for v in vals: CF.CFRelease(v)
    return d


# ── touch state ───────────────────────────────────────────────────────────────
# We track X (usage 0x30) and Y (usage 0x31) from usage_page 0x0D
_touch_x = 0
_touch_y = 0
_touch_queue: Queue = Queue()   # emits (x, y) tuples


# ── callback ──────────────────────────────────────────────────────────────────
CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int,
                                 IOHIDDeviceRef, IOHIDValueRef)

def _value_callback(context, result, sender, value):
    global _touch_x, _touch_y
    try:
        elem  = IOKit.IOHIDValueGetElement(value)
        up    = IOKit.IOHIDElementGetUsagePage(elem)
        usage = IOKit.IOHIDElementGetUsage(elem)
        iv    = IOKit.IOHIDValueGetIntegerValue(value)

        if up == 0x0D:   # Digitizer
            if usage == 0x30:   # X
                _touch_x = iv
            elif usage == 0x31:  # Y
                _touch_y = iv
                _touch_queue.put((_touch_x, _touch_y))
        elif up == 0x01 and usage in (0x30, 0x31):
            # Generic Desktop X/Y — also catch these
            if usage == 0x30:
                _touch_x = iv
            else:
                _touch_y = iv
                _touch_queue.put((_touch_x, _touch_y))
    except Exception:
        pass


_cb_ref = CALLBACK_TYPE(_value_callback)   # keep alive


def start(seize=False):
    """Start the IOHIDManager on a background thread. Returns the touch queue."""
    def _run():
        option = kIOHIDOptionsTypeSeizeDevice if seize else kIOHIDOptionsTypeNone
        mgr = IOKit.IOHIDManagerCreate(None, option)
        d   = _make_matching_dict(VID, PID)
        IOKit.IOHIDManagerSetDeviceMatching(mgr, d)
        CF.CFRelease(d)

        rl = CF.CFRunLoopGetCurrent()
        IOKit.IOHIDManagerScheduleWithRunLoop(mgr, rl, kCFRunLoopDefaultMode)
        ret = IOKit.IOHIDManagerOpen(mgr, option)
        if ret != kIOReturnSuccess:
            print(f"[iohid_touch] IOHIDManagerOpen failed: {ret:#x}", flush=True)
            return

        IOKit.IOHIDManagerRegisterInputValueCallback(mgr, _cb_ref, None)
        print("[iohid_touch] listening for touch events…", flush=True)

        while True:
            CF.CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.1, False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return _touch_queue


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("IOHIDManager touch capture test")
    print("Slide your finger on the Siri Remote touchpad. Ctrl-C to quit.\n")
    q = start(seize=True)
    try:
        while True:
            try:
                x, y = q.get(timeout=0.5)
                print(f"  touch  x={x:4d}  y={y:4d}")
            except Empty:
                pass
    except KeyboardInterrupt:
        print("\nDone.")
