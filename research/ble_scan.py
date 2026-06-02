#!/usr/bin/env python3
"""Scan for Bluetooth LE advertisements and highlight likely Apple remotes.

Run, then put the remote into pairing mode (hold Menu + Volume Up ~5s) while
holding it within a few inches of the Mac. We print every BLE device we see so
we can confirm whether the remote is advertising at all.
"""
import sys
import time

import CoreBluetooth
from Foundation import NSObject

SCAN_SECONDS = 30


class Delegate(NSObject):
    def centralManagerDidUpdateState_(self, central):
        state = central.state()
        names = {0: "Unknown", 1: "Resetting", 2: "Unsupported",
                 3: "Unauthorized", 4: "PoweredOff", 5: "PoweredOn"}
        print(f"[bt] state = {names.get(state, state)}")
        if state == 5:
            print("[bt] scanning for ALL BLE devices... press pairing combo NOW")
            central.scanForPeripheralsWithServices_options_(None, None)
        elif state == 3:
            print("[bt] NOT AUTHORIZED - grant Bluetooth permission to the terminal app")

    def centralManager_didDiscoverPeripheral_advertisementData_RSSI_(
        self, central, peripheral, adv, rssi
    ):
        ident = str(peripheral.identifier().UUIDString())
        name = peripheral.name() or adv.get("kCBAdvDataLocalName") or "(no name)"
        mfg = adv.get("kCBAdvDataManufacturerData")
        is_apple = False
        mfg_hex = ""
        if mfg is not None:
            b = bytes(mfg)
            mfg_hex = b[:8].hex()
            # Apple company id = 0x004C -> little-endian bytes 4c 00
            is_apple = b[:2] == b"\x4c\x00"
        key = ident
        # Print first time, or when name resolves
        prev = self.seen.get(key)
        if prev is None or (prev == "(no name)" and name != "(no name)"):
            self.seen[key] = name
            flag = "  <-- APPLE" if is_apple else ""
            print(f"  {name:24s} rssi={str(rssi):>4}  mfg={mfg_hex}{flag}")


def main():
    delegate = Delegate.alloc().init()
    delegate.seen = {}
    # Pass None -> CoreBluetooth uses the main dispatch queue, driven by the
    # console event loop below.
    central = CoreBluetooth.CBCentralManager.alloc().initWithDelegate_queue_(
        delegate, None
    )
    t = time.time()
    from PyObjCTools import AppHelper  # noqa
    # Run the run loop for SCAN_SECONDS
    import threading

    def stopper():
        time.sleep(SCAN_SECONDS)
        print("\n[bt] scan window closed.")
        unique = [n for n in delegate.seen.values()]
        print(f"[bt] total devices seen: {len(unique)}")
        AppHelper.stopEventLoop()

    threading.Thread(target=stopper, daemon=True).start()
    AppHelper.runConsoleEventLoop()
    _ = central  # keep ref


if __name__ == "__main__":
    main()
