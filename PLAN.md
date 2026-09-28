# Plan: Razer Huntsman V2 Analog — Linux sensitivity daemon

## Goal

Build a Linux userspace project that:

1. Switches the **Razer Huntsman V2 Analog** (`USB 1532:0266`) into **driver mode**.
2. Reads per-key analog travel values (`0x00`–`0xFF`).
3. Converts those into normal `EV_KEY` presses on a virtual keyboard (`uinput`).
4. Lets the user tune **key sensitivity** by setting the travel distance (actuation / release thresholds) required for a keypress.

This machine already has the keyboard connected and bound to OpenRazer (`razerkbd`, `openrazer-daemon`). Current `device_mode` is `00 00` (normal/device mode).

---

## Research summary

### OpenRazer (`openrazer/openrazer`)

| Finding | Detail |
|---|---|
| Device support | Huntsman V2 Analog is supported for lighting / basic control. |
| Analog / sensitivity | **Not implemented.** Tracked as [#1579](https://github.com/openrazer/openrazer/issues/1579); maintainers treat full analog input as out of scope for OpenRazer. |
| Driver-mode PR | [#1868](https://github.com/openrazer/openrazer/pull/1868) (Huntsman Mini Analog) was closed; author moved to a standalone userspace project. |
| Device mode | `echo -ne '\x03\x00' > …/device_mode` enters driver mode; `\x00\x00` returns to device mode. OpenRazer exposes this on the mouse/control HID interface (here: `…/0003:1532:0266.0016/device_mode`). |
| Critical constraint | In **device mode**, firmware emits normal HID key reports and sensitivity is **not** software-tunable. In **driver mode**, normal key reports stop; firmware emits custom analog depth reports that software must translate. |

OpenRazer remains useful for RGB and as one way to flip `device_mode`, but **it will not** solve actuation tuning by itself.

### evmapy (`kempniu/evmapy`)

| Finding | Detail |
|---|---|
| Role | Maps existing `evdev` events → uinput keypresses or command execution. |
| Absolute axes | Only fires on axis **min/max** extremes (`:min` / `:max`), not continuous thresholds. |
| Gaps for this project | No Razer protocol / driver-mode support; no key-repeat model suitable for typing; no per-key travel hysteresis; assumes an input device already exposing usable events. |

Useful as a **reference for uinput injection and config-driven mapping**, not as the core stack. A dedicated daemon that owns the HID stream is required.

### Closest prior art: `meeuw/razer-analog`

Standalone userspace driver for **Huntsman Mini Analog** (`1532:0282`):

- Opens all `hidraw` children of the USB parent via `pyudev`.
- Sends Razer feature report `0x00 / 0x04` with mode `0x03` to enter driver mode; restores `0x00` on exit.
- Parses analog input reports (report ID `0x07`: up to 11 `(key_id, depth)` pairs).
- Maps Razer key IDs → Linux `KEY_*` via a JSON layout.
- Applies hysteresis: press when depth `> 128`, release when `< 96`.
- Injects `EV_KEY` (with software repeat) and optional `EV_ABS` via `uinput`.
- Ships udev rules + systemd template units.

**Not a drop-in for V2 Analog:** different product ID, full-size layout, likely different HID descriptors / report IDs. A V2 adaptation attempt was reported as incomplete ([#1579 comment](https://github.com/openrazer/openrazer/issues/1579#issuecomment-2395573878)). Treat it as the architecture template, not a fork-and-run.

### Hardware notes (this host)

```
USB: 1532:0266  Razer Huntsman V2 Analog
USB parent: /sys/devices/pci0000:00/0000:00:08.1/0000:0d:00.3/usb3/3-1
Interfaces: 5 HID interfaces under razerkbd (0014…0018)
hidraw: hidraw1–hidraw5
OpenRazer control attrs: …/0003:1532:0266.0016/ (device_mode, matrix_*, etc.)
device_mode now: 00 00
```

### Two sensitivity approaches (choose primary)

| Approach | How it works | Pros | Cons |
|---|---|---|---|
| **A. Software threshold (driver mode)** — **primary target** | Enter driver mode; daemon thresholds analog stream → uinput keys | Live tuning on Linux; global + per-key; no Windows/Synapse | Daemon must stay running; must replace stock keyboard input; OpenRazer coexistence needs care |
| **B. On-device actuation** | Write actuation/release via Razer cmd class `0x02` / id `0x12` into onboard profile (persists without Synapse, per community tests) | Works in normal device mode; no continuous daemon for typing | Opcode / payload not fully documented in open source; harder to reverse; less flexible for live “sensitivity feel” tools |

This project should ship **Approach A** as MVP. Optionally research Approach B later as a complementary feature.

---

## Recommended architecture

```
┌─────────────────────────────┐
│  Huntsman V2 Analog (USB)   │
│  device_mode = 0x03         │
└──────────────┬──────────────┘
               │ hidraw analog reports (key_id, depth 0–255)
               ▼
┌─────────────────────────────┐
│  razer-analog-linux daemon  │
│  - protocol / mode control  │
│  - report parser            │
│  - threshold engine         │
│  - layout map (V2)          │
│  - uinput injector          │
│  - config / IPC             │
└──────────────┬──────────────┘
               │ EV_KEY (+ optional EV_ABS)
               ▼
┌─────────────────────────────┐
│  Virtual keyboard (uinput)  │
│  → X11 / Wayland / games    │
└─────────────────────────────┘
```

**Language:** Python 3 (match prior art / OpenRazer ecosystem) for MVP; optionally Rust later if latency profiling demands it.

**Runtime deps:** `python-evdev`, `pyudev`, access to `/dev/hidraw*` and `/dev/uinput`.

---

## Core design decisions

### 1. How to enter driver mode

Prefer talking to the device via **hidraw feature reports** (same as `razer-analog`), so the project works even if OpenRazer is stopped:

- Command class `0x00`, command id `0x04`, args `[0x03, 0x00]` → driver mode.
- Args `[0x00, 0x00]` → restore device mode on clean shutdown, SIGTERM, and crash-safe `atexit` / systemd `ExecStop`.

Also support reading/writing OpenRazer’s `device_mode` sysfs when present (convenience / debugging).

**Safety rule:** never leave the keyboard in driver mode without the daemon running — otherwise the OS gets **no keystrokes**.

### 2. Coexistence with OpenRazer

OpenRazer currently owns the HID interfaces for RGB. Options:

1. **Soft coexistence (MVP):** leave `razerkbd` loaded; grab/ignore stock `event*` nodes once in driver mode (they should go quiet for keys); keep OpenRazer for lighting only. Verify that OpenRazer daemon does not fight mode changes.
2. **Hard isolation:** temporarily unbind keyboard input interfaces from `razerkbd` / `hid-generic` while the daemon runs; rebind on stop. More reliable, more brittle.
3. Document: stop `openrazer-daemon` during early bring-up if mode fighting appears.

Plan: start with (1), fall back to (2) if needed.

### 3. Threshold / sensitivity model

Per key (and global default):

| Parameter | Meaning | Default (from prior art) |
|---|---|---|
| `actuate` | Depth ≥ this → key down | `128` (~50% travel) |
| `release` | Depth ≤ this → key up | `96` (~37.5% travel) |
| Optional `deadzone` | Ignore noise below this | `8` |

Require `release < actuate` (hysteresis) to avoid chatter / stuck keys.

Expose travel as both raw `0–255` and approximate millimetres if firmware full-press range is known (document as approximate until calibrated).

Support:

- Global default sensitivity.
- Per-key overrides.
- Live reload (SIGHUP or Unix socket / D-Bus) without exiting driver mode.
- Profiles (e.g. `typing.json`, `gaming.json`).

### 4. Key mapping

Build a **Huntsman V2 Analog** layout table: Razer report key ID → Linux `KEY_*`.

Bootstrap process:

1. Dump analog reports while pressing keys one-by-one (`debug-dump` mode).
2. Compare against Mini Analog map in `razer-analog` for overlapping keys.
3. Fill numpad / F-row / extras unique to full-size V2.
4. Handle Fn-layer separately if firmware reports the same physical ID with Fn held (or if Fn is a software modifier like in Mini Analog).

### 5. Output device behaviour

- Create one `uinput` keyboard named e.g. `Razer Huntsman V2 Analog (linux-analog)`.
- Emit press=`1`, release=`0`, and software auto-repeat=`2` for typing comfort (evmapy’s lack of good hold/repeat is why we don’t reuse it wholesale).
- Optional second mode later: also emit `EV_ABS` per key for games that want progressive input (out of MVP scope).
- Grab or otherwise suppress residual events from the physical HID keyboard interfaces while active.

### 6. Stuck-key mitigation

Prior art notes keys can stick if release never crosses the release threshold. Mitigations:

- Hysteresis + timeout: if a key disappears from the pressed set, force depth `0`.
- Periodic “all clear” if no analog report for N ms.
- Watchdog that restores device mode if the daemon dies.

---

## Project layout (proposed)

```
razer-analog-linux/
├── PLAN.md                 # this file
├── README.md
├── pyproject.toml
├── config/
│   ├── default.toml        # global actuate/release
│   └── layouts/
│       └── huntsman_v2_analog.json
├── src/razer_analog_linux/
│   ├── __init__.py
│   ├── cli.py              # start / stop / set-threshold / dump
│   ├── device.py           # USB/hidraw discovery, mode switch
│   ├── protocol.py         # Razer report build/CRC/send
│   ├── parser.py           # analog report → {key_id: depth}
│   ├── threshold.py        # hysteresis state machine
│   ├── layout.py           # key id → KEY_*
│   ├── uinput_kb.py        # virtual keyboard + repeat
│   ├── config.py           # load/reload profiles
│   └── daemon.py           # asyncio main loop
├── dist/
│   ├── udev/99-razer-analog-linux.rules
│   └── systemd/razer-analog-linux@.service
└── tests/
    ├── test_threshold.py
    ├── test_parser.py
    └── fixtures/analog_reports.bin
```

---

## Implementation phases

### Phase 0 — Protocol bring-up (1–2 days)

- [ ] Inventory hidraw nodes + HID report descriptors (`usbhid-dump -m 1532:0266`).
- [ ] Identify control interface vs analog-input interface (compare descriptors to Mini Analog).
- [ ] Implement CRC + feature-report send/receive.
- [ ] Toggle driver mode via hidraw; confirm stock keyboard goes silent.
- [ ] Dump raw analog packets while pressing keys; document report ID and packing.
- [ ] Always restore device mode on exit.

**Exit criteria:** prints live `(key_id, depth)` for several keys; keyboard returns to normal HID after quit.

### Phase 1 — Virtual keyboard MVP (2–4 days)

- [ ] Parser for active-key list reports.
- [ ] Minimal V2 layout for alphanumeric + modifiers.
- [ ] Threshold engine with global `actuate` / `release`.
- [ ] `uinput` injection + software repeat.
- [ ] CLI: `razer-analog-linux run --actuate 100 --release 70`.
- [ ] Suppress / ignore dead stock input nodes while running.

**Exit criteria:** can type in a terminal with adjustable sensitivity; Ctrl-C restores device mode.

### Phase 2 — Productization (3–5 days)

- [ ] Complete layout (Fn layer, media, numpad).
- [ ] Config file + per-key overrides + named profiles.
- [ ] Live threshold update without restart.
- [ ] udev rule + systemd user/system unit.
- [ ] Permissions story (`plugdev` / `input` / uaccess tags).
- [ ] OpenRazer coexistence notes / optional RGB-only mode.
- [ ] Logging, stuck-key watchdog, crash recovery.

**Exit criteria:** enable service, reboot, keyboard usable with saved sensitivity profile.

### Phase 3 — Polish / optional

- [ ] TUI or simple GUI to visualize per-key depth bars and drag thresholds.
- [ ] Research onboard actuation command `0x02/0x12` (Approach B) for persistent firmware thresholds without driver mode.
- [ ] Optional progressive `EV_ABS` / virtual gamepad mappings.
- [ ] Latency measurement vs stock HID; optimize hot path if needed.
- [ ] Package for distros (AUR, `.deb`).

---

## CLI sketch

```bash
# Discover device and dump analog stream (driver mode, no key injection)
razer-analog-linux dump

# Run virtual keyboard with global sensitivity
razer-analog-linux run --config ~/.config/razer-analog-linux/default.toml

# Live adjust (IPC to running daemon)
razer-analog-linux set --actuate 90 --release 60
razer-analog-linux set --key KEY_SPACE --actuate 40 --release 25

# Leave driver mode / stop service
razer-analog-linux stop
```

Example config:

```toml
[threshold]
actuate = 128
release = 96
repeat_delay_ms = 200
repeat_rate_ms = 30

[keys.KEY_SPACE]
actuate = 64
release = 48
```

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Leave keyboard in driver mode → no input | systemd `ExecStop=`; `atexit`; udev revert script; hardware USB re-plug documented as recovery |
| V2 report format differs from Mini | Phase 0 dump-first; do not hardcode Mini report ID until verified |
| Fight with OpenRazer over `device_mode` | Detect daemon; prefer exclusive mode or document “RGB via OpenRazer, input via this tool” |
| Stuck keys | Force zero on key disappearance; hysteresis; watchdog |
| Wrong key map → dangerous bindings | Start with dump/calibration tool; dry-run mode that only logs |
| Secure Boot / module issues | Project is userspace-hidraw; does not require new kernel modules (OpenRazer optional) |
| Typing latency | Keep hot path allocation-free; measure; consider Rust rewrite only if needed |

---

## Explicit non-goals (MVP)

- Replacing OpenRazer lighting / Chroma effects.
- Full Synapse feature parity (macros, Snap Tap, Hypershift cloud profiles).
- Kernel patch for `razerkbd` analog ABS events (rejected path / limited ABS codes).
- Relying on `evmapy` as the runtime (inspiration only).

---

## Success criteria

1. With the daemon running, every alphanumeric key produces correct Linux key events.
2. Lowering `actuate` makes keys fire with less travel; raising it requires deeper presses.
3. Stopping the daemon (or reboot with service off) returns the keyboard to normal OpenRazer/HID behaviour.
4. A documented config file is enough to persist a preferred sensitivity profile across sessions.

---

## Progress (this machine)

| Item | Status |
|---|---|
| Project scaffold (`src/razer_analog_linux`, config, dist, tests) | Done |
| Port from `razer-analog` (hidraw / protocol / driver mode) | Done |
| HID descriptors match Mini Analog | Done |
| CLI `run` / `dump` / `calibrate` / `find-device` | Done |
| Configurable actuate/release (`config/default.toml`) | Done |
| OpenRazer coexistence (`sync_sysfs`, leave daemon for RGB) | Done |
| Alphanumeric + main modifiers (seeded Mini map) | Working |
| Full V2 key coverage via calibrate | **Next — run calibrate** |

---

### Exit while in driver mode (`dump` / `calibrate`)

Ctrl+C from **this** keyboard does not reach the terminal (no HID key reports).
Those commands:

1. Warn explicitly after entering driver mode
2. Confirm mode via OpenRazer `device_mode` sysfs when available
3. Quit on **ESC** (Razer key_id `110`) past the actuate threshold, or on SIGINT/SIGTERM from another keyboard/terminal
4. Always restore device mode (`0x00`) and re-check sysfs on exit

`run` injects keys via uinput, so Ctrl+C from this keyboard works again there.

---

## Next step: Complete Huntsman V2 Analog key map

### Why keys are missing

The daemon still loads `razer_huntsman_mini_analog.json` (60% Mini). That file only maps **~61 plain keys**. The V2 Analog is full-size, so these physical keys have **no plain-layer mapping** today:

| Group | Missing examples |
|---|---|
| Function row | `F1`–`F12`, dedicated `GRAVE` |
| Navigation cluster | `INSERT`, `DELETE`, `HOME`, `END`, `PAGEUP`, `PAGEDOWN` |
| Arrow keys | `UP`, `DOWN`, `LEFT`, `RIGHT` |
| System cluster | `SYSRQ` (PrtSc), `SCROLLLOCK`, `PAUSE` |
| Numpad | `NUMLOCK`, `KP0`–`KP9`, `KPPLUS`, `KPMINUS`, `KPASTERISK`, `KPSLASH`, `KPDOT`, `KPENTER` |
| Media (if reported as analog IDs) | `MUTE`, `VOLUMEUP`/`DOWN`, play/skip; digital dial may be separate |

On Mini, many of those only exist on the **Fn layer** (e.g. Fn+number → F-keys). On V2 they are **dedicated keys** with their own Razer key IDs — different IDs from the Mini Fn overlays.

Also review Mini-specific quirks before copying them to V2:

- Super/`LEFTMETA` currently doubles as Fn (software Fn). V2 should treat Super as Super unless we deliberately keep that hack.
- Fn-layer media / arrows on Mini must not collide with V2’s dedicated arrow/media IDs.

### Goal

Every physical key on the V2 produces the correct Linux `KEY_*` in driver mode (plain layer first; Fn layer second).

### Approach: calibrate, don’t guess

Razer key IDs are not published as a clean V2 table. Discover them from the live analog stream.

```
 physical key press
        │
        ▼
  report 0x07: (razer_key_id, depth)
        │
        ▼
  dump / calibrate UI  ──record──►  huntsman_v2_analog.json
        │
        ▼
  layout.py loads V2 JSON by product ID
        │
        ▼
  virtual_keyboard → uinput
```

### Implementation checklist

1. **Add `dump` / calibrate mode** (no key injection, or injection only for already-mapped keys)
   - Enter driver mode, print `key_id=NN depth=DD` on press/release.
   - Optional: prompt `Press the key for F1:` and write the ID into a draft JSON.
   - Log **unmapped** IDs that cross threshold so unknown keys are obvious during normal use.

2. **Add `razer_huntsman_v2_analog.json`**
   - Start from Mini `plain` map (alphas/mods already verified).
   - Fill missing groups in this order (user presses each key once during calibration):
     1. `GRAVE`, `F1`–`F12`
     2. Arrows
     3. Ins/Del/Home/End/PgUp/PgDn
     4. PrtSc / Scroll Lock / Pause
     5. Full numpad
     6. Media row / dial (only if they appear as analog key IDs)
   - Define a V2-appropriate `fn` layer (backlight, sleep, macros, etc.) after plain works.

3. **Select layout by product ID** in `layout.py`
   - `0x0282` → Mini JSON; `0x0266` → V2 JSON.
   - Expand `uinput` capability list to include every `KEY_*` in the active layout (numpad, F-keys, etc.), or the kernel will drop events.

4. **Normalize modifier behaviour for V2**
   - Default: `LEFTMETA` → `KEY_LEFTMETA`, `FN` → Fn layer only.
   - Keep Mini “meta-as-Fn” behind a flag if still wanted.

5. **Verification matrix**
   - In driver mode with high actuate threshold: press each missing key fully and confirm the expected glyph/action in a terminal / `evtest` on the virtual device.
   - Confirm no stuck keys; release hysteresis still sane.
   - Restore device mode on exit.

### Deliverables

- `razer_analog/razer_huntsman_v2_analog.json` (complete plain map)
- `dump` or `calibrate` CLI entry point
- Product-ID layout selection + full `uinput` keybit set
- Short note in `DEVELOP.md`: how to re-run calibration if a key ID is wrong

### Exit criteria

- F-row, arrows, nav cluster, and numpad all work in driver mode.
- Unmapped-key logger stays quiet for a full pass over the board (except intentional non-keys like wrist-rest / unused).

### Estimate

~half day with interactive calibration; longer if media dial uses a different report path.

---

## First concrete next steps

1. ~~Capture HID descriptors and live analog dumps on this host (`1532:0266`).~~
2. ~~Port Mini Analog mode-switch + report loop, parameterized by product ID `0x0266`.~~
3. ~~Build the threshold → uinput path with a global sensitivity flag.~~
4. **Complete V2 key map** (dump/calibrate → `razer_huntsman_v2_analog.json` → product-ID layout load) — see section above.
5. Then: packaging, live threshold config, OpenRazer coexistence polish.

---

## References

- [OpenRazer](https://github.com/openrazer/openrazer) — lighting / `device_mode` sysfs; no analog sensitivity.
- [OpenRazer #1579](https://github.com/openrazer/openrazer/issues/1579) — analog support discussion; driver mode semantics.
- [OpenRazer #1868](https://github.com/openrazer/openrazer/pull/1868) — kernel-side Mini Analog attempt (closed).
- [OpenRazer #2031](https://github.com/openrazer/openrazer/issues/2031) — onboard remap / actuation opcode hints (`0x02/0x12`).
- [evmapy](https://github.com/kempniu/evmapy) — evdev→uinput mapper (axis min/max only).
- [meeuw/razer-analog](https://github.com/meeuw/razer-analog) — userspace hidraw reference implementation (Mini Analog).
- Local device: `1532:0266`, USB parent `…/usb3/3-1`, OpenRazer `device_mode` at interface `.0016`.
