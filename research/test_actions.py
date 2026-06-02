#!/usr/bin/env python3
"""Fire each macOS action with a countdown so you can watch which ones work."""
import time
import mac_actions as M

def step(name, fn, wait=4):
    for s in (3, 2, 1):
        print(f"  {name} in {s}...", flush=True)
        time.sleep(1)
    print(f">>> FIRING: {name}", flush=True)
    fn()
    time.sleep(wait)

print("Watch your screen. Each action fires after a countdown.\n", flush=True)
step("Spotlight (Cmd+Space)", M.spotlight)
step("Escape (close Spotlight)", lambda: M._tap_key(M.KEY_ESC))
step("Mission Control (Ctrl+Up)", M.mission_control)
step("Mission Control again (toggle off)", M.mission_control)
step("App Switcher (Cmd+Tab)", M.app_switcher_next)
print("\nDone.", flush=True)
