#!/usr/bin/env python3
"""
Enable the Siri Remote touch stream by sending 0xAF as a FEATURE report with
report ID 0xff (the vendor passthrough channel found in the report descriptor),
then watch the digitizer interface for 13/20-byte touch reports.

Report descriptor findings:
  - 0xc:0x1   INPUT  report_id=250 (0xfa)  -> buttons (fa 00, fa 80, ...)
  - 0xd:0x1   INPUT  report_id=255 (0xff)  -> touch stream target
  - every interface has FEATURE report_id=255 (0xff) -> command channel
"""
import sys
import time

import hid

VID = 0x004C
PID = 0x026D

REPORT_ID = 0xff


def send_af(h, label):
    """Try several payload shapes for the 0xAF enable command on report id 0xff."""
    attempts = [
        bytes([REPORT_ID, 0xAF]),
        bytes([REPORT_ID, 0xAF]) + bytes(206),   # pad toward the 208-byte size
        bytes([REPORT_ID, 0xAF]) + bytes(62),     # pad to 64
    ]
    for k, payload in enumerate(attempts):
        try:
            n = h.send_feature_report(payload)
            print(f"  [{label}] feature 0xff/0xAF attempt{k} len={len(payload)} -> {n}", flush=True)
            if n > 0:
                return True
        except Exception as e:
            print(f"  [{label}] attempt{k} ERR {e}", flush=True)
    # Also try output write on report id 0xff
    try:
        n = h.write(bytes([REPORT_ID, 0xAF]))
        print(f"  [{label}] output 0xff/0xAF -> {n}", flush=True)
    except Exception as e:
        print(f"  [{label}] output ERR {e}", flush=True)
    return False


def main():
    devs = hid.enumerate(VID, PID)
    if not devs:
        print("Remote not found.")
        sys.exit(1)

    handles = []
    for d in devs:
        up, u = d.get("usage_page", 0), d.get("usage", 0)
        label = f"{hex(up)}:{hex(u)}"
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(True)
            handles.append((label, up, u, h))
        except Exception as e:
            print(f"open {label} failed: {e}")

    print("--- sending 0xAF (feature, report id 0xff) to every interface ---", flush=True)
    for label, up, u, h in handles:
        send_af(h, label)

    print("\n--- slide finger on touchpad now; watching 20s for touch reports ---", flush=True)
    last = {}
    t0 = time.time()
    saw = False
    while time.time() - t0 < 20:
        for label, up, u, h in handles:
            try:
                data = h.read(256)
            except OSError:
                continue
            if data:
                # ignore the plain button report (id implied, 2 bytes fa xx)
                hx = " ".join(f"{b:02x}" for b in data)
                if last.get(label) != hx:
                    last[label] = hx
                    tag = ""
                    if len(data) >= 13 and not (len(data) == 2):
                        tag = "  <-- POSSIBLE TOUCH"
                        saw = True
                    print(f"[{label}] len={len(data):3d}  {hx}{tag}", flush=True)
        time.sleep(0.003)

    print(f"\nDone. saw_long_report={saw}", flush=True)
    for _, _, _, h in handles:
        try: h.close()
        except Exception: pass


if __name__ == "__main__":
    main()
