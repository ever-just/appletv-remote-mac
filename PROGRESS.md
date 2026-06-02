# Progress / Handoff Notes

Running log so this project can be resumed later. Newest at top.

## Current state (working)
- `controller.py` is functional. All buttons map to Mac actions with tap/hold +
  MEDIA/NAV modes. Debounce handles the remote's autorepeat.
- **Verified live:** Menu (Escape), TV tap (Mission Control), TV hold
  (Launchpad), Siri (launches Siri), Touchpad click (left click), mode switch
  (Menu hold), tap/hold detection all dispatch correctly in the logs.
- **Reliable triggers:** Siri / Mission Control / Launchpad use `open -a <App>`
  instead of keyboard shortcuts (shortcuts can be disabled by the user and were
  unreliable). Spotlight uses Cmd+Space (confirmed working).

## Key technical decisions / learnings
- Buttons come on Consumer Control interface `0xc:0x1` as `fa <bitmask>`.
- The remote **autorepeats** held buttons (rapid press/release). Solved with a
  debounced release in `controller.py` (`DEBOUNCE = 0.18`, `poll_releases()`).
- macOS already enables the input stream (we get buttons without sending 0xAF).
- **Touchpad slide is a dead end from userspace** (see README Limitations):
  digitizer is exclusively held by macOS (`kIOReturnExclusiveAccess` on seize;
  zero reports on shared open). Would need a DriverKit dext.

## How to resume
1. `cd appletv-remote-mac && source .venv/bin/activate`
   (or recreate: `python3 -m venv .venv && pip install -r requirements.txt`)
2. Wake the remote (press a button). Confirm it's seen:
   `python -c "import hid; print(len(hid.enumerate(0x004C,0x026D)))"` → should be 8.
3. `python controller.py`
4. Diagnostics live in `research/` — `capture_bt.py` is the most useful (dumps
   raw reports from all interfaces).

## Open items / TODO
- [ ] Confirm Mission Control / Launchpad open *visibly* (logs fire correctly;
      last pending visual confirmation from user).
- [ ] Optional: suppress native Volume/Play media keys in NAV mode (CGEventTap)
      so Vol± act purely as arrows.
- [ ] Optional: auto-start at login (launchd plist).
- [ ] Optional: external config file for custom mappings.
- [ ] Ambitious: DriverKit HID dext to unlock the touchpad slide-as-mouse.

## Device facts
- Siri Remote A1962, VID `0x004C`, PID `0x026D`, name `DL3VTK4YJ90M`.
- 8 HID interfaces; buttons on `0xc:0x1`, digitizer on `0xd:0x1` (blocked).
