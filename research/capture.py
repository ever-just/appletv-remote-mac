#!/usr/bin/env python3
"""Capture raw HID reports from the Apple TV (Siri) Remote over USB.

Run this, then press ONE button at a time when prompted. Every distinct
report the remote sends is printed as hex so we can build a button map.
"""
import sys
import time

import hid

APPLE_VID = 0x05AC
REMOTE_PID = 0x026D


def find_remote():
    for d in hid.enumerate():
        if d["vendor_id"] == APPLE_VID and d["product_id"] == REMOTE_PID:
            return d
    return None


def main():
    info = find_remote()
    if not info:
        print("Remote not found. Is it plugged in via Lightning?")
        print("Devices seen:")
        for d in hid.enumerate(APPLE_VID, 0):
            print(f"  {d['vendor_id']:04x}:{d['product_id']:04x} {d.get('product_string')}")
        sys.exit(1)

    print(f"Found: {info.get('product_string')} path={info['path']}")
    h = hid.device()
    try:
        h.open_path(info["path"])
    except Exception as e:
        print(f"open failed: {e}")
        print("If this is a permissions error, grant Input Monitoring to your terminal app.")
        sys.exit(2)

    h.set_nonblocking(True)
    print("\nReading reports. Press buttons on the remote now. Ctrl-C to stop.\n")
    last = None
    try:
        while True:
            try:
                data = h.read(64)
            except OSError:
                # Device dropped off the bus; wait for it to reappear and reopen.
                print("[info] read error - waiting for remote to reconnect...")
                try:
                    h.close()
                except Exception:
                    pass
                while True:
                    time.sleep(0.5)
                    again = find_remote()
                    if again:
                        try:
                            h = hid.device()
                            h.open_path(again["path"])
                            h.set_nonblocking(True)
                            print("[info] reconnected.")
                            break
                        except Exception:
                            pass
                continue
            if data:
                hx = " ".join(f"{b:02x}" for b in data)
                if hx != last:  # collapse repeats
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] len={len(data):2d}  {hx}")
                    last = hx
            else:
                time.sleep(0.005)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try:
            h.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
