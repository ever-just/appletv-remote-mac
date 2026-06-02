#!/usr/bin/env python3
"""
Dump + parse the HID report descriptors of every Siri Remote interface.

Goal: find the report IDs and their types (Input/Output/Feature) so we know
exactly where to send the 0xAF "enable touch" command via a SET_REPORT.
"""
import sys
import hid

VID = 0x004C
PID = 0x026D

# HID main-item tags
TAG_INPUT   = 0x80
TAG_OUTPUT  = 0x90
TAG_FEATURE = 0xB0
TAG_COLL    = 0xA0
TAG_END     = 0xC0
# global
TAG_USAGE_PAGE = 0x04
TAG_REPORT_ID  = 0x84
# local
TAG_USAGE      = 0x08


def parse_descriptor(desc):
    """Very small HID descriptor walker; returns list of (report_id, type, usage_page)."""
    i = 0
    report_id = 0
    usage_page = 0
    out = []
    n = len(desc)
    while i < n:
        b = desc[i]
        size = b & 0x03
        size = {0: 0, 1: 1, 2: 2, 3: 4}[size]
        tag = b & 0xFC
        data = 0
        for k in range(size):
            data |= desc[i + 1 + k] << (8 * k)
        if tag == TAG_USAGE_PAGE:
            usage_page = data
        elif tag == TAG_REPORT_ID:
            report_id = data
        elif tag == TAG_INPUT:
            out.append((report_id, "INPUT", usage_page))
        elif tag == TAG_OUTPUT:
            out.append((report_id, "OUTPUT", usage_page))
        elif tag == TAG_FEATURE:
            out.append((report_id, "FEATURE", usage_page))
        i += 1 + size
    return out


def main():
    devs = hid.enumerate(VID, PID)
    if not devs:
        print("Remote not found.")
        sys.exit(1)

    for d in devs:
        up = d.get("usage_page", 0)
        u = d.get("usage", 0)
        label = f"{hex(up)}:{hex(u)}"
        try:
            h = hid.device()
            h.open_path(d["path"])
        except Exception as e:
            print(f"[{label}] open failed: {e}")
            continue

        print(f"\n=== interface {label} ===")
        try:
            desc = h.get_report_descriptor()
            print(f"  descriptor ({len(desc)} bytes):")
            print("  " + " ".join(f"{b:02x}" for b in desc))
            items = parse_descriptor(desc)
            seen = set()
            for rid, typ, page in items:
                key = (rid, typ, page)
                if key in seen:
                    continue
                seen.add(key)
                print(f"    report_id={rid:3d}  {typ:8s}  usage_page={hex(page)}")
        except Exception as e:
            print(f"  get_report_descriptor failed: {e}")
        finally:
            h.close()


if __name__ == "__main__":
    main()
