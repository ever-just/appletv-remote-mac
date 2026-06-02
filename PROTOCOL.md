# Siri Remote (A1962, 2nd gen) — reverse-engineered BLE protocol

Source: https://github.com/Yanndroid/SiriRemote-Linux (+ Jack-R1 for audio)

## Transport
- Bluetooth LE, HID-over-GATT (HOGP). Link is encrypted -> requires bonding/pairing.
- Lightning/USB = charge + vendor-specific HID only. NO usable button stream over USB.
- Must be UNPLUGGED and in pairing mode (hold Menu + Volume Up ~5s) to bond first time.

## GATT layout (key entries)
- Generic Access 0x1800, Generic Attribute 0x1801
- Device Information 0x180A (PnP, serial, firmware)
- Human Interface Device 0x1812:
  - HID Information 0x2A4A
  - Report Map 0x2A4B
  - HID Control Point 0x2A4C
  - Report 0x2A4D  (char handle 0x1c / value 0x1d)   <- write 0xAF HERE (enable input)
  - Report 0x2A4D  (char handle 0x1f / value 0x20)
  - Report 0x2A4D  (char handle 0x22 / value 0x23)   <- INPUT, subscribe for notifications (CCCD 0x24)
- Battery Service 0x180F (Battery Level 0x2A19)
- Bond Management 0x181E
- Apple proprietary service 8341f2b4-c013-4f04-8197-c4cdb42e26dc
  - 9fbf120d-6301-42d9-8c58-25e699a21dbd
  - 2bdcaebe-8746-45df-a841-96b840980fb7
  - 2bdcaebe-8746-45df-a841-96b840980fb8
  - 30e69638-3752-4feb-a3aa-3226bcd05ace  (notify, CCCD 0x3b)

## Enable input handshake (CRITICAL)
1. Write single byte 0xAF to the first Report char (value handle 0x1d).
2. Enable notifications on the input Report char (value handle 0x23) by writing 0x01 0x00 to its CCCD (0x24).
3. Reports then arrive from value handle 0x23 with length 2, 13, 20, or 1011.

CoreBluetooth note: it addresses by UUID, not handle. The three 0x2A4D chars come back
in handle order -> reports[0] = 0x1d (write 0xAF), reports[2] = 0x23 (subscribe).
Disambiguate via the Report Reference descriptor (0x2908) = [reportID, reportType]
(type 1=input, 2=output, 3=feature) when possible.

## Button report (2 bytes) - byte[1] is a bitmask (supports combos)
- 0x00 all released
- 0x01 AirPlay / TV
- 0x02 Volume up
- 0x04 Volume down
- 0x08 Play/Pause
- 0x10 Siri (mic)
- 0x20 Menu
- 0x80 Touchpad click

## Touch report (13 bytes; 20 with two fingers)
- bytes[0:6] general info; bytes[6:] touch data
- X = data[6] + 255 * (data[7] & 7)   (touchpad has 8 vertical "zones")
- Y goes 188..255 then 0..38 (looks like signed byte), low resolution

## Audio/Siri: 101-byte reports, mostly opus-encoded (see Jack-R1). Out of scope for control.
