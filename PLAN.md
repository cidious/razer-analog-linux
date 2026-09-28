# Plan: Razer Huntsman V2 Analog — Linux sensitivity daemon

## Goal

Linux userspace daemon that:

1. Switches the **Razer Huntsman V2 Analog** (`USB 1532:0266`) into **driver mode**.
2. Reads per-key analog travel (`0x00`–`0xFF`).
3. Converts that into normal `EV_KEY` events on a virtual keyboard (`uinput`).
4. Lets the user tune **key sensitivity** (actuation / release travel thresholds).

**Repo:** https://github.com/cidious/razer-analog-linux  
**Status:** v0.1 usable daily driver for typing; Approach A (software thresholds in driver mode) shipped.

---

## Current status (as of initial commit)

| Area | Status | Notes |
|---|---|---|
| Project scaffold + git | Done | `src/razer_analog_linux`, config, tests, udev/systemd stubs |
| Port from `meeuw/razer-analog` | Done | hidraw / CRC / mode `0x03` / report `0x07` |
| HID descriptors vs Mini Analog | Done | Control + analog interfaces **byte-identical** to Mini |
| Driver mode enter/restore | Done | hidraw + OpenRazer `device_mode` sysfs sync |
| CLI `run` / `dump` / `calibrate` / `find-device` | Done | |
| Global actuate/release | Done | `config/default.toml` + `--actuate` / `--release` |
| V2 plain key map | Done | F-row, nav, arrows, system, numpad calibrated (~104 keys) |
| Dedicated media keys / dial | Skipped | Not on analog report `0x07` — see below |
| OpenRazer RGB coexistence | Done | Soft coexistence; daemon may stay running |
| Scroll Lock LED (KDE layout indicator) | Done | `EV_LED` on uinput → physical sysfs LEDs |
| ESC / SPACE exit in dump/calibrate | Done | Ctrl+C from this KB impossible in those modes |
| Per-key threshold overrides / live reload | Not done | |
| Fn-layer (backlight, sleep, macros) | Minimal | Only `FN` stub |
| On-device actuation (Approach B) | Not done | |
| Distro packaging | Stubs only | udev + systemd unit templates |

### What works today

```bash
sudo .venv/bin/razer-analog-linux run --actuate 128 --release 96
sudo .venv/bin/razer-analog-linux dump          # quit: ESC
sudo .venv/bin/razer-analog-linux calibrate     # SPACE=skip, ESC=abort
```

- Typing on the full main/numpad/F/nav clusters via uinput.
- Threshold tuning verified (including near-max actuate for “bottom of travel”).
- KDE layout hotkeys (Caps / Shift+Caps) with Scroll Lock LED on 2nd layout.

### Known limitations

- **Dedicated media row + digital dial** do not emit analog `0x07` events (Consumer Control / non-optical hardware). Marked `_skipped` / `_non_analog_controls` in the layout JSON.
- **`dump` / `calibrate`:** this keyboard cannot send Ctrl+C; use ESC (or SIGTERM from elsewhere).
- **Per-key thresholds, live IPC `set`, profiles:** not implemented yet (global only).
- **Fn combos** (brightness, sleep, OTF macro, etc.): not calibrated as a layer.

---

## Research summary (background)

### OpenRazer

- Supports V2 Analog for lighting; **no** analog sensitivity ([#1579](https://github.com/openrazer/openrazer/issues/1579)).
- Driver-mode PR [#1868](https://github.com/openrazer/openrazer/pull/1868) closed; userspace preferred.
- Device mode via `device_mode`: `03 00` = driver, `00 00` = normal.

### evmapy

Inspiration for uinput mapping only — no Razer protocol; axes only at min/max.

### meeuw/razer-analog

Architecture template (Mini Analog `0x0282`). V2 reused the same descriptors/report IDs after product-ID change; layout and media controls differ.

### Hardware (this host)

```
USB: 1532:0266  Razer Huntsman V2 Analog
USB parent: /sys/devices/pci0000:00/0000:00:08.1/0000:0d:00.3/usb3/3-1
OpenRazer device_mode: …/0003:1532:0266.*/device_mode
```

### Sensitivity approaches

| Approach | Role in this project |
|---|---|
| **A. Software threshold (driver mode)** | **Shipped** — primary path |
| **B. On-device actuation (`0x02/0x12`)** | Future optional; opcode still poorly documented in FOSS |

---

## Architecture (implemented)

```
┌─────────────────────────────┐
│  Huntsman V2 Analog (USB)   │
│  device_mode = 0x03         │
└──────────────┬──────────────┘
               │ hidraw report 0x07 (key_id, depth)
               ▼
┌─────────────────────────────┐
│  razer-analog-linux         │
│  device / protocol / parser │
│  threshold (hysteresis)     │
│  layout (V2 JSON)           │
│  uinput_kb + LED forward    │
└───────┬─────────────┬───────┘
        │ EV_KEY      │ EV_LED → sysfs
        ▼             ▼
   virtual kb    physical scroll/caps/num LEDs
```

**Stack:** Python 3.10+, `evdev`, `pyudev`, `ioctl-opt`.

**Layout file:** `config/layouts/huntsman_v2_analog.json`  
**Config:** `config/default.toml`

---

## Design decisions (resolved)

1. **Driver mode:** hidraw feature report `0x00/0x04`; also write OpenRazer `device_mode` when present; restore `0x00` on exit / atexit / signals.
2. **OpenRazer:** soft coexistence (RGB stays); optional `require_daemon_stopped`.
3. **Thresholds:** global `actuate` / `release` with hysteresis (`release < actuate`); CLI overrides.
4. **Key map:** calibrated V2 plain map; Super is Super (`meta_as_fn = false`); Mini meta-as-Fn available via config flag.
5. **Media keys:** not mappable via analog path; calibrate supports **SPACE = skip**.
6. **LEDs:** uinput advertises `EV_LED`; compositor updates forwarded to physical LED sysfs (needed for KDE `grp_led:scroll`-style indicators).
7. **Stuck keys:** implicit depth `0` when a key disappears from the active set + hysteresis.

---

## Project layout (actual)

```
razer-analog-linux/
├── PLAN.md
├── README.md
├── LICENSE
├── pyproject.toml
├── config/
│   ├── default.toml
│   └── layouts/huntsman_v2_analog.json
├── src/razer_analog_linux/
│   ├── cli.py
│   ├── config.py
│   ├── daemon.py
│   ├── device.py
│   ├── protocol.py
│   ├── parser.py
│   ├── threshold.py
│   ├── layout.py
│   ├── uinput_kb.py
│   ├── leds.py
│   └── hidraw.py
├── scripts/run.sh
├── dist/
│   ├── udev/99-razer-analog-linux.rules
│   └── systemd/razer-analog-linux@.service
└── tests/
    ├── test_threshold.py
    └── test_parser.py
```

Upstream `meeuw/razer-analog` may exist locally as `/razer-analog/` for reference; it is **gitignored**.

---

## Implementation phases

### Phase 0 — Protocol bring-up — Done

- [x] HID descriptors / interfaces inventory
- [x] CRC + feature reports
- [x] Driver mode toggle + restore
- [x] Analog report `0x07` dump

### Phase 1 — Virtual keyboard MVP — Done

- [x] Parser + threshold engine
- [x] uinput injection + software repeat
- [x] CLI `run` with `--actuate` / `--release`
- [x] OpenRazer soft coexistence

### Phase 2 — V2 layout + usability — Mostly done

- [x] Interactive `calibrate` / `dump` (ESC quit, SPACE skip)
- [x] Full plain map (alphas, F-row, nav, arrows, system, numpad)
- [x] Document / skip non-analog media controls
- [x] Scroll Lock LED forwarding for layout indicators
- [x] udev + systemd **templates** (not installed/end-to-end tested as a service)
- [ ] Per-key threshold overrides
- [ ] Live threshold reload / IPC (`set` command)
- [ ] Named profiles
- [ ] Fn-layer mappings (brightness, sleep, etc.)
- [ ] Hardened crash recovery / watchdog beyond atexit

### Phase 3 — Polish / optional — Not started

- [ ] TUI/GUI for depth bars + threshold sliders
- [ ] Approach B: onboard actuation opcode
- [ ] Progressive `EV_ABS` / gamepad mappings
- [ ] Latency measurement / optimization
- [ ] Distro packages (AUR, `.deb`)
- [ ] Consumer-control path for dedicated media keys (if useful in driver mode)

---

## CLI (current vs planned)

**Shipped:**

```bash
razer-analog-linux find-device
razer-analog-linux dump [--device …] [--actuate N] [--release N]
razer-analog-linux calibrate [--device …] [--layout …] [--only KEY…]
razer-analog-linux run [--device …] [--config …] [--actuate N] [--release N]
```

**Still planned:**

```bash
razer-analog-linux set --actuate 90 --release 60
razer-analog-linux set --key KEY_SPACE --actuate 40 --release 25
razer-analog-linux stop
```

---

## Risks (updated)

| Risk | Mitigation (current) |
|---|---|
| Stuck in driver mode | Restore on exit / atexit / ESC in dump·calibrate; USB re-plug; write `device_mode` `00 00` |
| OpenRazer mode fights | sysfs sync; leave daemon for RGB; document stop if needed |
| Media keys missing | Expected; SPACE skip in calibrate; future Consumer Control work |
| LED indicator broken under uinput | Fixed via LED forward |
| Wrong key map | Calibrate + unmapped logger in `run` |

---

## Non-goals (unchanged)

- Replacing OpenRazer Chroma.
- Full Synapse parity.
- Kernel `razerkbd` analog ABS support.
- Using evmapy as the runtime.

---

## Success criteria

| Criterion | Met? |
|---|---|
| Alphanumeric (+ full board clusters) work in driver mode | Yes |
| Actuate/release change feel | Yes (global) |
| Clean exit restores normal HID | Yes |
| Documented config for sensitivity | Yes (global TOML; not per-key yet) |
| Layout LED (Scroll Lock) with KDE | Yes |

---

## Next steps (priority)

1. **Per-key thresholds + profiles** in config; optional live `set` over a Unix socket.
2. **Fn-layer calibration** for V2 Fn combos worth keeping.
3. **Service install path:** document installing udev rules + systemd unit; test reboot persistence.
4. **Optional:** decode dedicated media / dial via Consumer Control reports while in driver mode.
5. **Optional:** Approach B onboard actuation reverse-engineering.

---

## References

- [OpenRazer](https://github.com/openrazer/openrazer)
- [OpenRazer #1579](https://github.com/openrazer/openrazer/issues/1579) — analog / driver mode
- [OpenRazer #1868](https://github.com/openrazer/openrazer/pull/1868) — Mini Analog PR (closed)
- [OpenRazer #2031](https://github.com/openrazer/openrazer/issues/2031) — onboard remap / actuation hints
- [evmapy](https://github.com/kempniu/evmapy)
- [meeuw/razer-analog](https://github.com/meeuw/razer-analog)
- This project: https://github.com/cidious/razer-analog-linux
