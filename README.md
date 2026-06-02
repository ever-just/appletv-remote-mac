# Siri Remote → Mac Controller

Use a Bluetooth-paired **Apple Siri Remote (A1962)** as a custom input device for
macOS. All physical buttons are mapped to Mac actions with **tap vs hold**
detection and two switchable **modes** (MEDIA / NAV).

> **Touchpad slide-as-mouse is NOT supported** and (from a userspace script)
> not achievable on macOS — see [Limitations](#limitations). The touchpad
> **click** works; the touchpad **slide** does not.

---

## Quick start

```bash
cd appletv-remote-mac
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python controller.py
```

### Required macOS permissions
Grant the program running Python (Terminal / iTerm / your IDE) both:
- **Input Monitoring** — System Settings → Privacy & Security → Input Monitoring
- **Accessibility** — System Settings → Privacy & Security → Accessibility

Without these, the remote won't be read and synthetic events won't post.

### Pairing the remote
1. Unplug the remote from power (BLE only works on battery).
2. Hold **Menu + Volume Up** ~5 s to enter pairing mode.
3. Pair it in System Settings → Bluetooth.
4. The remote sleeps aggressively — **press any button to wake it** before
   launching `controller.py`. If you see `Remote not found`, wake it and retry.

---

## Button mappings

Tap = quick press. **HOLD** = press longer than `HOLD_THRESHOLD` (0.5 s).
Switch modes by **holding Menu**.

### MEDIA mode (default)
| Button | Tap | Hold |
|--------|-----|------|
| Vol +  | Volume Up | Brightness Up |
| Vol −  | Volume Down | Brightness Down |
| Play   | Play/Pause | Next Track |
| Touchpad click | Left Click | Right Click |
| TV     | Mission Control | Launchpad |
| Siri   | **Siri** (listening) | Spotlight |
| Menu   | Escape | → switch to NAV mode |

### NAV mode (keyboard navigation)
| Button | Tap | Hold |
|--------|-----|------|
| Vol +  | Up arrow | Page Up |
| Vol −  | Down arrow | Page Down |
| TV     | Left arrow | — |
| Play   | Right arrow | — |
| Touchpad click | Enter / Select | Left Click |
| Siri   | **Siri** | Spotlight |
| Menu   | Escape | → switch to MEDIA mode |

---

## How it works

- The remote exposes several HID interfaces over Bluetooth. Buttons arrive on
  the **Consumer Control** interface (`usage_page 0x0c`, `usage 0x01`) as a
  2-byte report: `fa <bitmask>`.
- `controller.py` opens that interface with **hidapi**, decodes the bitmask, and
  posts macOS events via **Quartz CGEvent** (`mac_actions.py`).
- The remote **autorepeats** held buttons as rapid press/release cycles. The
  controller **debounces** these (`DEBOUNCE = 0.18 s`): a release is only "real"
  if no new press of the same bit arrives within the window. Hold duration is
  measured from first press to final real release. This is what makes tap vs
  hold reliable.

### Button bitmask (`byte[1]`)
| Bit | Button |
|-----|--------|
| 0x01 | TV / AirPlay |
| 0x02 | Volume Up |
| 0x04 | Volume Down |
| 0x08 | Play/Pause |
| 0x10 | Siri (mic) |
| 0x20 | Menu |
| 0x80 | Touchpad click |

See [`PROTOCOL.md`](PROTOCOL.md) for the full reverse-engineered BLE/HID protocol.

---

## Files

| File | Purpose |
|------|---------|
| `controller.py` | **Main app.** Reads buttons, debounces, dispatches actions. |
| `mac_actions.py` | macOS event primitives (keys, clicks, media keys, Siri, Mission Control, Spotlight, Launchpad). |
| `PROTOCOL.md` | Reverse-engineered BLE/HID protocol notes. |
| `PROGRESS.md` | Session history + how to resume. |
| `requirements.txt` | Python dependencies. |
| `research/` | Exploratory/diagnostic scripts used during reverse engineering (not needed to run the controller). |

### `research/` scripts (for reference / debugging)
- `capture_bt.py` — dump raw HID reports from every interface (best diagnostic).
- `dump_descriptors.py` — print HID report descriptors.
- `seize_touch.py` — IOKit seize + raw input-report callback (proves the
  digitizer is exclusively held by macOS; see Limitations).
- `iohid_touch.py`, `touch_tap.py`, `enable_touch*.py`, `enable_input.py` —
  various (unsuccessful) attempts to enable/read the touchpad slide.
- `remote_ble.py`, `ble_scan.py` — CoreBluetooth experiments (HID service is
  blocked by macOS).
- `test_actions.py` — fire each macOS action with a countdown to verify injection.

---

## Limitations

### Touchpad slide (cursor) is not achievable from userspace — confirmed
We exhausted every userspace path:

- **CoreBluetooth**: macOS blocks the HID service (`0x1812`) from all apps. Only
  Device Info / Battery are visible. The `0xAF` enable write can't be sent.
- **IOKit SET_REPORT (`0xAF`)**: accepted locally but never transmitted to the
  device; touch never starts.
- **Seizing the digitizer** (`kIOHIDOptionsTypeSeizeDevice`): fails with
  `kIOReturnExclusiveAccess` (`0xE00002C5`) — macOS's own driver holds it.
- **Shared open + raw input-report callback**: opens, but macOS delivers **zero**
  digitizer reports (it consumes them).
- macOS parses the touch report as an **opaque vendor blob** (no X/Y usages), so
  it neither uses it (cursor doesn't move) nor forwards it.

Tools like **BetterTouchTool** / **Remote Buddy** get the touchpad only via a
privileged driver-level component. Replicating that requires a signed
**DriverKit HID system extension** (Apple Developer account + entitlements +
notarized installer) — a separate, much larger project.

### Other notes
- macOS handles **Volume / Play** natively too, so in NAV mode pressing Vol±
  also nudges system volume. A future enhancement could suppress native media
  keys via a `CGEventTap` while in NAV mode.
- The remote sleeps quickly; wake it before launching.

---

## Possible next steps
- Suppress native media keys in NAV mode (CGEventTap).
- Auto-start at login (launchd plist / `launchctl`).
- Config file for custom mappings.
- (Ambitious) DriverKit dext to unlock the touchpad slide.
