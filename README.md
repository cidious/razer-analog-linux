# Razer Analog Linux — Huntsman V2 Analog

Userspace daemon that switches the keyboard into **driver mode**, converts
analog travel into normal keypresses, and lets you tune actuation thresholds.

Based on ideas from [meeuw/razer-analog](https://github.com/meeuw/razer-analog).
Target device: **Razer Huntsman V2 Analog** (`1532:0266`).

## Features (v0.1)

- Enter / leave Razer driver mode (`device_mode` 0x03 / 0x00)
- Map analog depth → `uinput` key events with hysteresis
- Configurable press / release thresholds
- Calibration (`dump` / `calibrate`) to discover Razer key IDs
- Coexist with OpenRazer for RGB (this daemon owns input in driver mode)
- Forward lock LEDs (incl. Scroll Lock) for layout indicators (e.g. KDE)

## Requirements

- Linux with `uinput` and hidraw support
- Python **3.10+**
- Access to the keyboard’s `/dev/hidraw*` nodes and `/dev/uinput` (typically **root**, or membership in `plugdev` / `input` after installing the udev rules below)
- Optional but recommended: [OpenRazer](https://openrazer.github.io/) for RGB (input is handled by this daemon)

## Installation

### 1. Clone and install into a virtualenv

```bash
git clone https://github.com/cidious/razer-analog-linux.git
cd razer-analog-linux

python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .

# optional: run tests
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

The CLI entry point is `.venv/bin/razer-analog-linux`.

**Do not use `sudo poetry run …`** unless this project `.venv` exists and Poetry
is using it — otherwise root’s environment misses packages (`ModuleNotFoundError: evdev`).
Prefer:

```bash
sudo .venv/bin/razer-analog-linux …
# or
sudo ./scripts/run.sh …
```

### 2. (Optional) udev rules for non-root hidraw / uinput

```bash
sudo cp dist/udev/99-razer-analog-linux.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

# ensure your user is in the groups used by the rules
sudo usermod -aG plugdev,input "$USER"
# log out and back in (or reboot) for groups to apply
```

Until udev/groups are set up, run the daemon with `sudo`.

### 3. (Optional) systemd template

A sample unit is in `dist/systemd/razer-analog-linux@.service`. It expects an
installed binary at `/usr/local/bin/razer-analog-linux` and config under
`/etc/razer-analog-linux/`. Adjust paths before enabling; for day-to-day use,
running from the venv (step 1) is enough.

### 4. Find the device (optional)

Auto-detect usually works for `1532:0266`:

```bash
.venv/bin/razer-analog-linux find-device
# → /sys/devices/…/usbX/Y-Z
```

Or locate the USB parent manually:

```bash
udevadm info -t | less   # search Razer_Huntsman_V2_Analog, note T: usb_device / P:
```

Pass it explicitly with `--device /sys/devices/…/usbX/Y-Z` if needed.

## Usage

```bash
# Dump raw key_id / depth (no key injection). Quit with ESC — not Ctrl+C on this KB.
sudo .venv/bin/razer-analog-linux dump

# Map missing keys into the layout JSON (SPACE=skip, ESC=abort)
sudo .venv/bin/razer-analog-linux calibrate

# Run virtual keyboard (Ctrl+C works again here — keys are injected via uinput)
sudo .venv/bin/razer-analog-linux run --actuate 128 --release 96

# Same with config file
sudo .venv/bin/razer-analog-linux run --config config/default.toml
```

Helper wrapper (uses the project `.venv`):

```bash
sudo ./scripts/run.sh run --actuate 128 --release 96
```

## Safety

Driver mode **disables normal HID key reports**. Always stop the daemon cleanly
(Ctrl-C on `run`, or ESC on `dump` / `calibrate`).

If the keyboard is stuck with no input:

```bash
printf '\x00\x00' | sudo tee \
  /sys/bus/hid/drivers/razerkbd/0003:1532:0266.*/device_mode
# or unplug / replug the keyboard
```

## OpenRazer

OpenRazer may keep managing RGB. This tool sets driver mode via hidraw and
mirrors OpenRazer `device_mode` sysfs when present. Stop `openrazer-daemon`
only if mode fighting appears.

## Config

- Thresholds / device options: `config/default.toml`
- Key map: `config/layouts/huntsman_v2_analog.json`  
  (re-run `calibrate` to adjust; dedicated media keys/dial are not analog — skip with SPACE)

## License

GPL-3.0-or-later.
