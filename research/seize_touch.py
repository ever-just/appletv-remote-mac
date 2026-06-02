#!/usr/bin/env python3
"""
Seize the Siri Remote's HID interfaces and register RAW input-report callbacks.

Why this should work where everything else failed:
  - macOS already enabled the remote's input stream (we receive 2-byte button
    reports, which per the BLE protocol only arrive after the 0xAF enable).
  - The touchpad's digitizer report is a raw vendor blob (report_id=255, one
    opaque field) -> an IOHIDManager *value* callback has nothing to fire on.
    We must use a raw input-REPORT callback.
  - macOS's generic driver "kidnaps" the digitizer (shared hidapi opens get
    nothing). Seizing (kIOHIDOptionsTypeSeizeDevice) makes the OS release it so
    the raw reports come to us.
"""
import ctypes
import ctypes.util

IOKit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
CF    = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

# ── types ──
IOHIDManagerRef = ctypes.c_void_p
IOHIDDeviceRef  = ctypes.c_void_p
CFSetRef        = ctypes.c_void_p
CFStringRef     = ctypes.c_void_p
CFTypeRef       = ctypes.c_void_p
CFRunLoopRef    = ctypes.c_void_p
IOOptionBits    = ctypes.c_uint32

kIOHIDOptionsTypeNone        = 0
kIOHIDOptionsTypeSeizeDevice = 1
kIOReturnSuccess             = 0
kCFStringEncodingUTF8        = 0x08000100
kCFNumberSInt32Type          = 3

kCFRunLoopDefaultMode = ctypes.c_void_p.in_dll(CF, "kCFRunLoopDefaultMode")

# ── CF funcs ──
CF.CFStringCreateWithCString.restype  = CFStringRef
CF.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
CF.CFRunLoopGetCurrent.restype  = CFRunLoopRef
CF.CFRunLoopGetCurrent.argtypes = []
CF.CFRunLoopRunInMode.restype  = ctypes.c_int
CF.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
CF.CFSetGetCount.restype  = ctypes.c_long
CF.CFSetGetCount.argtypes = [CFSetRef]
CF.CFSetGetValues.restype  = None
CF.CFSetGetValues.argtypes = [CFSetRef, ctypes.POINTER(ctypes.c_void_p)]
CF.CFNumberGetValue.restype  = ctypes.c_bool
CF.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]

# ── IOKit funcs ──
IOKit.IOHIDManagerCreate.restype  = IOHIDManagerRef
IOKit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, IOOptionBits]
IOKit.IOHIDManagerSetDeviceMatching.restype  = None
IOKit.IOHIDManagerSetDeviceMatching.argtypes = [IOHIDManagerRef, ctypes.c_void_p]
IOKit.IOHIDManagerOpen.restype  = ctypes.c_int
IOKit.IOHIDManagerOpen.argtypes = [IOHIDManagerRef, IOOptionBits]
IOKit.IOHIDManagerCopyDevices.restype  = CFSetRef
IOKit.IOHIDManagerCopyDevices.argtypes = [IOHIDManagerRef]

IOKit.IOHIDDeviceOpen.restype  = ctypes.c_int
IOKit.IOHIDDeviceOpen.argtypes = [IOHIDDeviceRef, IOOptionBits]
IOKit.IOHIDDeviceScheduleWithRunLoop.restype  = None
IOKit.IOHIDDeviceScheduleWithRunLoop.argtypes = [IOHIDDeviceRef, CFRunLoopRef, ctypes.c_void_p]
IOKit.IOHIDDeviceGetProperty.restype  = CFTypeRef
IOKit.IOHIDDeviceGetProperty.argtypes = [IOHIDDeviceRef, CFStringRef]
IOKit.IOHIDDeviceRegisterInputReportCallback.restype  = None
IOKit.IOHIDDeviceRegisterInputReportCallback.argtypes = [
    IOHIDDeviceRef, ctypes.POINTER(ctypes.c_uint8), ctypes.c_long,
    ctypes.c_void_p, ctypes.c_void_p
]
IOKit.IOHIDDeviceSetReport.restype  = ctypes.c_int
IOKit.IOHIDDeviceSetReport.argtypes = [
    IOHIDDeviceRef, ctypes.c_int, ctypes.c_long,
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_long
]


def cfstr(s):
    return CF.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)


def dev_prop_int(dev, key):
    ref = IOKit.IOHIDDeviceGetProperty(dev, cfstr(key))
    if not ref:
        return None
    out = ctypes.c_int32(0)
    CF.CFNumberGetValue(ref, kCFNumberSInt32Type, ctypes.byref(out))
    return out.value


# ── report callback ──
REPORT_CB = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
    ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_long
)

_dev_label = {}   # device ptr -> "up:usage"
_buffers   = []   # keep report buffers alive
_cb_refs   = []   # keep callbacks alive
_last = {}

def _on_report(context, result, sender, rtype, report_id, report, length):
    try:
        data = bytes(report[i] for i in range(length))
        label = _dev_label.get(int(sender) if sender else 0, "?")
        hx = " ".join(f"{b:02x}" for b in data)
        key = label
        if _last.get(key) != hx:
            _last[key] = hx
            tag = ""
            if length >= 13:
                # try decode per protocol
                x = data[6] + 255 * (data[7] & 7) if length > 7 else 0
                y = data[8] if length > 8 else 0
                tag = f"  <-- TOUCH? x={x} y={y}"
            print(f"[{label}] id={report_id} len={length}  {hx}{tag}", flush=True)
    except Exception as e:
        print("cb err", e, flush=True)


def main():
    VID, PID = 0x004C, 0x026D
    mgr = IOKit.IOHIDManagerCreate(None, kIOHIDOptionsTypeNone)

    # match by vid/pid
    matching = _make_match(VID, PID)
    IOKit.IOHIDManagerSetDeviceMatching(mgr, matching)

    ret = IOKit.IOHIDManagerOpen(mgr, kIOHIDOptionsTypeNone)
    print(f"IOHIDManagerOpen -> {ret:#x}", flush=True)

    devset = IOKit.IOHIDManagerCopyDevices(mgr)
    if not devset:
        print("No devices.")
        return
    count = CF.CFSetGetCount(devset)
    arr = (ctypes.c_void_p * count)()
    CF.CFSetGetValues(devset, arr)
    print(f"matched {count} device interfaces", flush=True)

    rl = CF.CFRunLoopGetCurrent()
    for i in range(count):
        dev = arr[i]
        up = dev_prop_int(dev, "PrimaryUsagePage")
        u  = dev_prop_int(dev, "PrimaryUsage")
        label = f"{hex(up or 0)}:{hex(u or 0)}"
        _dev_label[int(dev)] = label

        # Only SEIZE the digitizer (touch). Leave the other interfaces to macOS
        # so it keeps the remote connected/awake and volume etc still work.
        if up != 0x0d:
            continue

        # Try SHARED open first (macOS may allow a passive listener); fall back
        # to seize. kIOReturnExclusiveAccess means the OS driver won't share.
        r = IOKit.IOHIDDeviceOpen(dev, kIOHIDOptionsTypeNone)
        if r != 0:
            r = IOKit.IOHIDDeviceOpen(dev, kIOHIDOptionsTypeSeizeDevice)
        buf = (ctypes.c_uint8 * 512)()
        _buffers.append(buf)
        cb = REPORT_CB(_on_report)
        _cb_refs.append(cb)
        IOKit.IOHIDDeviceRegisterInputReportCallback(dev, buf, 512, cb, None)
        IOKit.IOHIDDeviceScheduleWithRunLoop(dev, rl, kCFRunLoopDefaultMode)
        status = "OK" if r == 0 else f"FAIL({r:#x})"
        print(f"  seize {label:12s} open={status}", flush=True)

    print("\nSlide your finger on the touchpad. Ctrl-C to stop.\n", flush=True)
    try:
        while True:
            CF.CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, False)
    except KeyboardInterrupt:
        print("\nDone.")


def _make_match(vid, pid):
    # Build CFDictionary {VendorID:vid, ProductID:pid}
    CF.CFDictionaryCreateMutable.restype = ctypes.c_void_p
    CF.CFDictionaryCreateMutable.argtypes = [ctypes.c_void_p, ctypes.c_long,
                                             ctypes.c_void_p, ctypes.c_void_p]
    kCFTypeDictionaryKeyCallBacks = ctypes.c_void_p.in_dll(CF, "kCFTypeDictionaryKeyCallBacks")
    kCFTypeDictionaryValueCallBacks = ctypes.c_void_p.in_dll(CF, "kCFTypeDictionaryValueCallBacks")
    CF.CFNumberCreate.restype = ctypes.c_void_p
    CF.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    CF.CFDictionarySetValue.restype = None
    CF.CFDictionarySetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

    d = CF.CFDictionaryCreateMutable(None, 0,
                                     ctypes.byref(kCFTypeDictionaryKeyCallBacks),
                                     ctypes.byref(kCFTypeDictionaryValueCallBacks))
    for key, val in (("VendorID", vid), ("ProductID", pid)):
        v = ctypes.c_int32(val)
        num = CF.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(v))
        CF.CFDictionarySetValue(d, cfstr(key), num)
    return d


if __name__ == "__main__":
    main()
