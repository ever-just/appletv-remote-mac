#!/usr/bin/env python3
"""
Try to enable the Siri Remote's full input stream (touch + extended buttons)
by sending the 0xAF "enable input" handshake over the HID layer via hidapi,
then watch every interface for the 13/20-byte touch reports.

The BLE protocol says: write 0xAF to a HID Report characteristic. Over the
HID transport that surfaces as either an OUTPUT report (hid_write) or a
FEATURE report (hid_send_feature_report). We try every interface and both
report mechanisms with report IDs 0..7, then listen for touch data.
"""
import sys
import time

import hid

VID = 0x004C
PID = 0x026D


def try_enable(h, label):
    """Try output + feature writes of 0xAF with several report IDs."""
    results = []
    # Output reports: first byte is the report ID (0 = no ID)
    for rid in range(0, 8):
        try:
            n = h.write(bytes([rid, 0xAF]))
            results.append(f"write(id={rid})={n}")
        except Exception as e:
            results.append(f"write(id={rid}) ERR {e}")
    # Feature reports
    for rid in range(0, 8):
        try:
            n = h.send_feature_report(bytes([rid, 0xAF]))
            results.append(f"feat(id={rid})={n}")
        except Exception as e:
            results.append(f"feat(id={rid}) ERR {e}")
    print(f"  [{label}] {' '.join(results)}", flush=True)


def main():
    devs = hid.enumerate(VID, PID)
    if not devs:
        print("Remote not found. Press a button to wake it, then rerun.")
        sys.exit(1)

    handles = []
    for d in devs:
        up = d.get("usage_page", 0)
        u = d.get("usage", 0)
        label = f"{hex(up)}:{hex(u)}"
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(True)
            handles.append((label, h))
            print(f"opened {label}", flush=True)
        except Exception as e:
            print(f"could not open {label}: {e}", flush=True)

    print("\n--- Sending 0xAF enable-input handshake on every interface ---", flush=True)
    for label, h in handles:
        try_enable(h, label)

    print("\n--- Now slide your finger on the touchpad. Watching for touch reports (15s) ---", flush=True)
    last = {}
    t0 = time.time()
    saw_touch = False
    while time.time() - t0 < 15:
        for label, h in handles:
            try:
                data = h.read(64)
            except OSError:
                continue
            if data:
                hx = " ".join(f"{b:02x}" for b in data)
                if last.get(label) != hx:
                    last[label] = hx
                    tag = ""
                    if len(data) in (13, 20):
                        x = data[6] + 255 * (data[7] & 7)
                        y = data[8]
                        tag = f"  <-- TOUCH? x={x} y={y}"
                        saw_touch = True
                    print(f"[{label}] len={len(data):2d}  {hx}{tag}", flush=True)
        time.sleep(0.003)

    print(f"\nDone. saw_touch={saw_touch}", flush=True)
    for _, h in handles:
        try: h.close()
        except Exception: pass


if __name__ == "__main__":
    main()
