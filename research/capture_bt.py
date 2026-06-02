#!/usr/bin/env python3
"""Capture raw HID reports from the Bluetooth-paired Siri Remote, per interface.

The remote (vid 0x004C pid 0x026D over BT) exposes several HID interfaces.
We open each one and label every report by its (usage_page, usage) so we can
decode the touchpad (digitizer 0x0d) and button (vendor 0xff00) formats.
"""
import sys
import time
import threading

import hid

VID = 0x004C
PID = 0x026D


def main():
    devs = [d for d in hid.enumerate(VID, PID)]
    if not devs:
        print("Remote not found over Bluetooth. Is it connected?")
        sys.exit(1)

    handles = []
    for d in devs:
        up = d.get("usage_page", 0)
        u = d.get("usage", 0)
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(True)
            handles.append((up, u, h))
            print(f"opened interface usage_page={hex(up)} usage={hex(u)}")
        except Exception as e:
            print(f"could not open up={hex(up)} u={hex(u)}: {e}")

    print("\nNow: (1) slide your finger across the touchpad, (2) click it, "
          "(3) press Menu, Siri, Play. Ctrl-C to stop.\n")
    last = {}
    try:
        while True:
            any_data = False
            for up, u, h in handles:
                try:
                    data = h.read(64)
                except OSError:
                    continue
                if data:
                    any_data = True
                    key = (up, u)
                    hx = " ".join(f"{b:02x}" for b in data)
                    if last.get(key) != hx:
                        last[key] = hx
                        print(f"[up={hex(up)} u={hex(u)}] len={len(data):2d}  {hx}")
            if not any_data:
                time.sleep(0.004)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for _, _, h in handles:
            try:
                h.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
