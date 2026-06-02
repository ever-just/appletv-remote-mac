#!/usr/bin/env python3
"""Talk to an Apple TV Siri Remote (A1962) directly over Bluetooth LE.

This is a from-scratch CoreBluetooth client based on the reverse-engineered
protocol (see PROTOCOL.md). It:
  1. scans for the HID-over-GATT remote,
  2. connects + bonds,
  3. sends the 0xAF "enable input" handshake to the first HID Report char,
  4. subscribes to the input Report char (+ Apple notify char),
  5. decodes button (2-byte bitmask) and touch (13-byte) reports.

Run with --map to also translate buttons into macOS events. Default = log only.

Usage:
  python remote_ble.py            # discover + connect + log raw/decoded reports
  python remote_ble.py --map      # also drive the Mac (volume, play/pause, etc.)
"""
import sys
import time
import threading

import CoreBluetooth
from Foundation import NSObject, NSData
from PyObjCTools import AppHelper

import mac_actions

HID_SERVICE = CoreBluetooth.CBUUID.UUIDWithString_("1812")
APPLE_SERVICE = CoreBluetooth.CBUUID.UUIDWithString_(
    "8341f2b4-c013-4f04-8197-c4cdb42e26dc"
)
REPORT_CHAR = "2A4D"            # HID Report
APPLE_NOTIFY = "30E69638-3752-4FEB-A3AA-3226BCD05ACE"

# CBCharacteristicProperties bit flags
P_WRITE_NO_RESP = 0x04
P_WRITE = 0x08
P_NOTIFY = 0x10

BUTTONS = {
    0x01: "AirPlay/TV",
    0x02: "Vol+",
    0x04: "Vol-",
    0x08: "Play/Pause",
    0x10: "Siri",
    0x20: "Menu",
    0x80: "Touchpad",
}

FALLBACK_SCAN_ALL_AFTER = 12  # seconds


def decode_buttons(b1):
    if b1 == 0:
        return ["(released)"]
    return [name for bit, name in BUTTONS.items() if b1 & bit]


class Driver(NSObject):
    # ---- lifecycle ----
    def centralManagerDidUpdateState_(self, central):
        states = {0: "Unknown", 1: "Resetting", 2: "Unsupported",
                  3: "Unauthorized", 4: "PoweredOff", 5: "PoweredOn"}
        s = central.state()
        print(f"[bt] state = {states.get(s, s)}")
        if s == 5:
            # Once UNPAIRED from macOS, the remote advertises its HID service in
            # pairing mode and we can bond to it directly. Scan for it. (If it is
            # still bound to the OS we won't see 1812, hence the unpair step.)
            self._start_filtered_scan(central)
        elif s == 3:
            print("[bt] Bluetooth permission denied. Grant it to your terminal in "
                  "System Settings > Privacy & Security > Bluetooth.")

    def _poll_connected(self, central):
        # macOS may index the remote under any of its advertised services, not
        # just HID. Probe a broad set.
        probe_services = [
            CoreBluetooth.CBUUID.UUIDWithString_(s) for s in (
                "1812", "180A", "180F", "1800", "1801", "181E",
                "8341f2b4-c013-4f04-8197-c4cdb42e26dc",
            )
        ]

        def loop():
            for i in range(240):  # ~120s
                if self.target is not None:
                    return
                conn = list(central.retrieveConnectedPeripheralsWithServices_(
                    probe_services) or [])
                if conn:
                    for p in conn:
                        print(f"[bt] connected-candidate: name={p.name()!r} "
                              f"id={p.identifier().UUIDString()}")
                    # Prefer one whose name looks like a remote.
                    p = next((x for x in conn
                              if "remote" in (x.name() or "").lower()), conn[0])
                    name = p.name() or "(no name)"
                    print(f"\n[bt] CLAIMING: {name!r} id={p.identifier().UUIDString()}")
                    self.target = p
                    p.setDelegate_(self)
                    central.connectPeripheral_options_(p, None)
                    return
                if i % 4 == 0:
                    print(f"[bt] ...waiting for remote (press Menu now) [{i//2}s]")
                time.sleep(0.5)
            print("[bt] Gave up after 60s. Remote never appeared as connected.")
        threading.Thread(target=loop, daemon=True).start()

    def _start_filtered_scan(self, central):
        print("[bt] scanning for HID remote (service 0x1812 / Apple service)...")
        print("     >>> PRESS Menu + Volume Up for 5s NOW, remote held to the Mac <<<")
        central.scanForPeripheralsWithServices_options_(
            [HID_SERVICE, APPLE_SERVICE],
            {CoreBluetooth.CBCentralManagerScanOptionAllowDuplicatesKey: True},
        )
        # Fallback: if nothing matches the service filter, scan everything and
        # connect to strong connectable candidates to inspect them.
        def fallback():
            time.sleep(FALLBACK_SCAN_ALL_AFTER)
            if not self.target:
                print(f"[bt] no HID-advertised remote after {FALLBACK_SCAN_ALL_AFTER}s;"
                      " scanning ALL devices and probing strong ones...")
                self.scan_all = True
                central.stopScan()
                central.scanForPeripheralsWithServices_options_(
                    None,
                    {CoreBluetooth.CBCentralManagerScanOptionAllowDuplicatesKey: True},
                )
        threading.Thread(target=fallback, daemon=True).start()

    def centralManager_didDiscoverPeripheral_advertisementData_RSSI_(
        self, central, peripheral, adv, rssi
    ):
        if self.target is not None:
            return
        svc = adv.get("kCBAdvDataServiceUUIDs") or []
        svc_strs = [str(u.UUIDString()).upper() for u in svc]
        name = peripheral.name() or adv.get("kCBAdvDataLocalName") or "(no name)"
        connectable = bool(adv.get("kCBAdvDataIsConnectable", 0))
        is_hid = any(s.startswith("1812") for s in svc_strs)
        is_apple_svc = any("8341F2B4" in s for s in svc_strs)
        looks_remote = "remote" in name.lower()

        interesting = is_hid or is_apple_svc or looks_remote
        if self.scan_all:
            # In fallback, also probe very strong connectable devices.
            interesting = interesting or (connectable and int(rssi) > -55)

        if interesting:
            print(f"[bt] candidate: name={name!r} rssi={rssi} services={svc_strs} "
                  f"hid={is_hid} apple={is_apple_svc} connectable={connectable}")
            self.target = peripheral
            peripheral.setDelegate_(self)
            central.stopScan()
            print(f"[bt] connecting to {name!r}...")
            central.connectPeripheral_options_(peripheral, None)

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        print(f"[bt] CONNECTED. discovering services...")
        peripheral.discoverServices_(None)

    def centralManager_didFailToConnectPeripheral_error_(self, central, peripheral, err):
        print(f"[bt] connect failed: {err}. rescanning...")
        self.target = None
        self._start_filtered_scan(central)

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, err):
        print(f"[bt] disconnected: {err}. rescanning...")
        self.target = None
        self.reports = []
        self._start_filtered_scan(central)

    # ---- GATT discovery ----
    def peripheral_didDiscoverServices_(self, peripheral, err):
        if err:
            print(f"[bt] service discovery error: {err}")
            return
        for s in peripheral.services():
            print(f"[gatt] service {s.UUID().UUIDString()}")
            peripheral.discoverCharacteristics_forService_(None, s)

    def peripheral_didDiscoverCharacteristicsForService_error_(self, peripheral, service, err):
        if err:
            print(f"[bt] char discovery error: {err}")
            return
        su = str(service.UUID().UUIDString()).upper()
        for c in service.characteristics():
            cu = str(c.UUID().UUIDString()).upper()
            props = c.properties()
            print(f"[gatt]   char {cu} props=0x{props:02x}")
            peripheral.discoverDescriptorsForCharacteristic_(c)
            if cu.startswith(REPORT_CHAR):
                self.reports.append(c)
            if cu == APPLE_NOTIFY and (props & P_NOTIFY):
                print("[bt] subscribing to Apple notify char")
                peripheral.setNotifyValue_forCharacteristic_(True, c)
            # Subscribe to any notifiable report char.
            if cu.startswith(REPORT_CHAR) and (props & P_NOTIFY):
                print("[bt] subscribing to HID Report (notify) char")
                peripheral.setNotifyValue_forCharacteristic_(True, c)
        if su.startswith("1812"):
            self._do_handshake(peripheral)

    def _do_handshake(self, peripheral):
        # Write 0xAF to the first writable HID Report characteristic to enable input.
        payload = NSData.dataWithBytes_length_(bytes([0xAF]), 1)
        wrote = False
        for c in self.reports:
            props = c.properties()
            if props & P_WRITE:
                print("[bt] handshake: writing 0xAF (with response) to a Report char")
                peripheral.writeValue_forCharacteristic_type_(
                    payload, c, CoreBluetooth.CBCharacteristicWriteWithResponse)
                wrote = True
                break
            elif props & P_WRITE_NO_RESP:
                print("[bt] handshake: writing 0xAF (no response) to a Report char")
                peripheral.writeValue_forCharacteristic_type_(
                    payload, c, CoreBluetooth.CBCharacteristicWriteWithoutResponse)
                wrote = True
                break
        if not wrote:
            print("[bt] WARNING: no writable Report char found for 0xAF handshake")

    def peripheral_didDiscoverDescriptorsForCharacteristic_error_(self, peripheral, c, err):
        for d in (c.descriptors() or []):
            if str(d.UUID().UUIDString()).upper().startswith("2908"):
                peripheral.readValueForDescriptor_(d)

    def peripheral_didWriteValueForCharacteristic_error_(self, peripheral, c, err):
        if err:
            print(f"[bt] write error: {err}")
        else:
            print("[bt] handshake write OK (0xAF accepted)")

    def peripheral_didUpdateValueForDescriptor_error_(self, peripheral, d, err):
        val = d.value()
        if val is not None:
            b = bytes(val)
            print(f"[gatt]   report-reference {b.hex()} (id={b[0] if b else '?'},"
                  f" type={b[1] if len(b) > 1 else '?'})")

    # ---- input ----
    def peripheral_didUpdateValueForCharacteristic_error_(self, peripheral, c, err):
        if err:
            print(f"[bt] notify error: {err}")
            return
        v = c.value()
        if v is None:
            return
        data = bytes(v)
        n = len(data)
        if n == 2:
            names = decode_buttons(data[1])
            print(f"[btn] {data.hex()}  -> {', '.join(names)}")
            if self.map_events:
                mac_actions.handle_buttons(data[1])
        elif n in (13, 20):
            x = data[6] + 255 * (data[7] & 7)
            y = data[8] if n > 8 else 0
            print(f"[touch] len={n} x={x} y={y}  raw={data.hex()}")
            if self.map_events:
                mac_actions.handle_touch(x, y, data)
        else:
            print(f"[rpt] len={n} raw={data.hex()}")


def main():
    map_events = "--map" in sys.argv
    driver = Driver.alloc().init()
    driver.target = None
    driver.reports = []
    driver.scan_all = False
    driver.map_events = map_events
    central = CoreBluetooth.CBCentralManager.alloc().initWithDelegate_queue_(driver, None)
    driver.central = central
    print("[bt] starting. (Ctrl-C to stop)  map_events =", map_events)
    try:
        AppHelper.runConsoleEventLoop()
    except KeyboardInterrupt:
        print("\n[bt] stopping.")


if __name__ == "__main__":
    main()
