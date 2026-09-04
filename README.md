# Siri Remote → Mac

Turn a Bluetooth-paired Apple Siri Remote into a macOS input device, with tap-vs-hold and two modes.

**Status:** Working · first commit 2026-09-04 · public

|  |  |
|---|---|
| **What it is** | A userspace macOS controller for the Apple Siri Remote (A1962) |
| **Who it's for** | Mac users who want a couch remote — and anyone reverse-engineering Apple HID |
| **Live at** | — (a local script, not a hosted service) |
| **Stack** | Python 3 · hidapi · PyObjC / Quartz `CGEvent` · macOS |
| **Status** | Working · 7 buttons, tap and hold, 2 modes · ~500 lines · one commit, 2026-09-04 |

Siri Remote → Mac reads the remote's Bluetooth HID button reports and posts native macOS
events for them. The usual answer to "can I use this remote with my Mac?" is a commercial
utility with a privileged driver component. This is about 500 lines of Python you can read,
plus the reverse-engineered protocol written down next to it.

## The problem

The Siri Remote is a good piece of hardware that macOS ignores. Pair it over Bluetooth and
the system will register it, take the volume and play keys for itself, and do nothing with
the other five buttons. There is no Apple-supplied way to bind them.

The buttons are not actually hidden — they arrive on a standard HID interface as a two-byte
bitmask. What makes a naive script unusable is that the remote **autorepeats**: hold a button
and it emits rapid press/release cycles, so every hold reads as a burst of taps and tap-vs-hold
detection collapses. Solving that debounce is most of the value here; the rest is a mapping table.

The touchpad **slide** is a different story, and it is a dead end from userspace. That is
documented rather than worked around — see [Known limitations](#known-limitations).

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python controller.py
```

**Two things to do first, or nothing will happen:**

1. **Pair the remote.** Unplug it from power (BLE only works on battery), hold **Menu + Volume Up**
   for ~5 s, then pair in System Settings → Bluetooth. It sleeps aggressively — press any button to
   wake it before launching, or you will get `Remote not found`.
2. **Grant two permissions** to whatever runs Python (Terminal, iTerm, your IDE): **Input Monitoring**
   and **Accessibility**, both under System Settings → Privacy & Security. Without them the remote is
   never read and synthetic events are never posted.

## What it does

- **Maps every physical button** — Volume ±, Play, TV/AirPlay, Siri, Menu and the touchpad click.
- **Distinguishes tap from hold** at a 0.5 s threshold, so each button carries two actions.
- **Switches modes** — hold Menu to toggle MEDIA (playback, volume, brightness, Mission Control,
  Siri, Spotlight) and NAV (arrows, Page Up/Down, Enter, click).
- **Debounces the remote's autorepeat**, which is what makes hold detection reliable at all.
- **Documents the protocol it decodes** — GATT layout, the enable handshake, report formats — in
  [`PROTOCOL.md`](PROTOCOL.md), so the mapping table is extensible rather than magic.

### Mappings

| Button | MEDIA tap | MEDIA hold | NAV tap | NAV hold |
|---|---|---|---|---|
| Vol + | Volume Up | Brightness Up | Up arrow | Page Up |
| Vol − | Volume Down | Brightness Down | Down arrow | Page Down |
| Play | Play/Pause | Next Track | Right arrow | — |
| TV | Mission Control | Launchpad | Left arrow | — |
| Touchpad click | Left Click | Right Click | Enter / Select | Left Click |
| Siri | Siri | Spotlight | Siri | Spotlight |
| Menu | Escape | → NAV mode | Escape | → MEDIA mode |

## How it works

The remote exposes eight HID interfaces over Bluetooth. Buttons arrive on the Consumer Control
interface (`usage_page 0x0c`, `usage 0x01`) as a two-byte report, `fa <bitmask>`. `controller.py`
opens that interface with [hidapi](https://github.com/libusb/hidapi), decodes the bitmask, and posts
macOS events through Quartz `CGEvent` in `mac_actions.py`. macOS enables the input stream itself, so
the `0xAF` write the Linux drivers send is not needed on this platform.

Hold detection is the non-obvious part. A release only counts as real when no new press of the same
bit arrives within `DEBOUNCE` (0.18 s) — shorter than a deliberate re-press, longer than the autorepeat
gap. Hold duration is then measured from the first press to that final real release, and compared
against `HOLD_THRESHOLD` (0.5 s).

### Repository layout

```text
.
├── controller.py     # main app — opens the HID interface, debounces, dispatches actions
├── mac_actions.py    # macOS event primitives: keys, clicks, media keys, Siri, Spotlight, Launchpad
├── requirements.txt  # hidapi + PyObjC (Quartz, Cocoa, CoreBluetooth)
├── PROTOCOL.md       # reverse-engineered BLE/HID protocol for the A1962
├── PROGRESS.md       # session log, verified behaviour, and how to resume
└── research/         # diagnostic scripts from the reverse engineering — not needed to run the app
```

Entry point: `controller.py`. The read loop is `poll_releases()`; the two mapping tables are
`_do_media()` and `_do_nav()`. Protocol groundwork is owed to
[SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux).

## Known limitations

- **Touchpad slide-as-cursor is not achievable from userspace — confirmed, not assumed.** CoreBluetooth
  cannot see the HID service (`0x1812`); IOKit `SET_REPORT` accepts the `0xAF` enable but never transmits
  it; seizing the digitizer returns `kIOReturnExclusiveAccess`; a shared open delivers zero reports because
  macOS consumes them. Doing it properly needs a signed DriverKit HID system extension. The touchpad
  **click** works.
- **macOS keeps its native handling of Volume and Play**, so in NAV mode Vol± also nudges system volume.
  Suppressing that needs a `CGEventTap`.
- **Mappings are constants in `controller.py`.** No config file, and no launch agent — it does not start
  at login.
- **One device, one revision.** Written and tested against the A1962 (2nd-gen Siri Remote), VID `0x004C`
  / PID `0x026D`.

## License

MIT is the intent for this repository. **No `LICENSE` file is committed yet** — add one before making
the repository public.
