# Razer Analog Linux — Huntsman V2 Analog

Userspace daemon that switches the keyboard into **driver mode**, converts
analog travel into normal keypresses, and lets you tune actuation thresholds.

Based on ideas from [meeuw/razer-analog](https://github.com/meeuw/razer-analog)
(Huntsman Mini Analog). Target device: **Razer Huntsman V2 Analog** (`1532:0266`).

## Features (v0.1)

- Enter / leave Razer driver mode (`device_mode` 0x03 / 0x00)
- Map analog depth → `uinput` key events with hysteresis
- Configurable press / release thresholds
- Calibration (`dump` / `calibrate`) to discover Razer key IDs
- Coexist with OpenRazer for RGB (this daemon owns input in driver mode)

## Quick start

```bash
cd /path/to/razer-analog-linux
python3 -m venv .venv
.venv/bin/pip install -e .

# Discover USB sysfs parent (T: usb_device for the keyboard)
udevadm info -t | less   # search Razer_Huntsman_V2_Analog

# Dump raw key IDs (no typing injection). Quit with ESC (not Ctrl+C on this KB).
sudo .venv/bin/razer-analog-linux dump

# Interactive calibration for missing keys (ESC aborts)
sudo .venv/bin/razer-analog-linux calibrate

# Run virtual keyboard
sudo .venv/bin/razer-analog-linux run \
  --device /sys/devices/.../usb3/3-1 \
  --config config/default.toml
```

Or use the helper: `sudo ./scripts/run.sh run --device …`

**Do not use `sudo poetry run`** unless a project `.venv` exists — root Poetry
will miss packages (`ModuleNotFoundError: evdev`).

## Safety

Driver mode disables normal HID key reports. Always stop the daemon cleanly
(Ctrl-C). Recovery if stuck:

```bash
printf '\x00\x00' | sudo tee \
  /sys/bus/hid/drivers/razerkbd/0003:1532:0266.*/device_mode
# or unplug / replug the keyboard
```

## OpenRazer

OpenRazer may keep managing RGB. This tool sets driver mode via hidraw (and
mirrors to OpenRazer `device_mode` sysfs when present). Stop `openrazer-daemon`
only if mode fighting appears.

## Config

See `config/default.toml` for thresholds and `config/layouts/huntsman_v2_analog.json`
for the key map (fill unknowns with `calibrate`).

## License

GPL-3.0-or-later (aligned with upstream razer-analog / OpenRazer ecosystem).
