#!/usr/bin/env python3
"""
Comprehensive 0xAF enable sweep + listener.

Tries 0xAF as OUTPUT and FEATURE across the real report IDs found in the
descriptors (1, 2, 250, 255) on every interface, also pokes get_input_report
to kickstart streaming, then watches ALL interfaces for any report longer
than the 2-byte button report.
"""
import sys
import time

import hid

VID = 0x004C
PID = 0x026D

REPORT_IDS = [1, 2, 250, 255]


def sweep(h, label):
    for rid in REPORT_IDS:
        # FEATURE
        try:
            n = h.send_feature_report(bytes([rid, 0xAF]))
            if n > 0:
                print(f"  [{label}] FEATURE id={rid} 0xAF -> {n}", flush=True)
        except Exception:
            pass
        # OUTPUT
        try:
            n = h.write(bytes([rid, 0xAF]))
            if n > 0:
                print(f"  [{label}] OUTPUT  id={rid} 0xAF -> {n}", flush=True)
        except Exception:
            pass
    # poke input reports to kickstart streaming
    for rid in REPORT_IDS:
        try:
            r = h.get_input_report(rid, 64)
            if r and any(r):
                hx = " ".join(f"{b:02x}" for b in r)
                print(f"  [{label}] get_input_report({rid}) -> {hx}", flush=True)
        except Exception:
            pass


def main():
    devs = hid.enumerate(VID, PID)
    if not devs:
        print("Remote not found (press a button).")
        sys.exit(1)

    handles = []
    for d in devs:
        up, u = d.get("usage_page", 0), d.get("usage", 0)
        label = f"{hex(up)}:{hex(u)}"
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(True)
            handles.append((label, h))
        except Exception as e:
            print(f"open {label} failed: {e}")

    print("--- comprehensive 0xAF sweep ---", flush=True)
    for label, h in handles:
        sweep(h, label)

    print("\n--- slide finger for 20s; ANY non-button report prints ---", flush=True)
    last = {}
    t0 = time.time()
    saw = False
    while time.time() - t0 < 20:
        for label, h in handles:
            try:
                data = h.read(256)
            except OSError:
                continue
            if data and len(data) != 2:
                hx = " ".join(f"{b:02x}" for b in data)
                if last.get(label) != hx:
                    last[label] = hx
                    saw = True
                    print(f"[{label}] len={len(data):3d}  {hx}  <-- NON-BUTTON", flush=True)
        time.sleep(0.003)

    print(f"\nDone. saw_non_button={saw}", flush=True)
    for _, h in handles:
        try: h.close()
        except Exception: pass


if __name__ == "__main__":
    main()
