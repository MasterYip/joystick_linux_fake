# Dummy Joystick Setup Guide

This document focuses on system setup for Joystick Linux Fake. The project now uses `python-evdev` as the only runtime backend.

## Quick Start

```bash
sudo modprobe uinput
python -m pip install -e .
joystick-linux-fake --mode check
sudo joystick-linux-fake --mode gui
```

## System Prerequisites

### Load the `uinput` module

```bash
sudo modprobe uinput
```

To load it automatically on boot:

```bash
echo "uinput" | sudo tee /etc/modules-load.d/uinput.conf
```

### Install Python dependencies

From the repository root:

```bash
python -m pip install -e .
```

Or install only the runtime dependency:

```bash
python -m pip install -r requirements.txt
```

### Install Tkinter if your distro separates it

Ubuntu or Debian example:

```bash
sudo apt-get install python3-tk
```

## Optional Non-Root Access

If you do not want to run the device with `sudo`, grant access to `/dev/uinput`:

```bash
sudo usermod -a -G input "$USER"
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Log out and back in after the group change.

## Command Reference

### Check the environment

```bash
joystick-linux-fake --mode check
```

### Start the GUI

```bash
sudo joystick-linux-fake --mode gui
```

### Start an idle virtual joystick

```bash
sudo joystick-linux-fake --mode idle
```

### Run a simulation pattern

```bash
sudo joystick-linux-fake --mode simulate --pattern circle
sudo joystick-linux-fake --mode simulate --pattern figure8
sudo joystick-linux-fake --mode simulate --pattern trigger-pulse
sudo joystick-linux-fake --mode simulate --pattern combo-demo
```

### Use the compatibility launcher

```bash
python dummy_joystick.py --mode gui
```

## Verification

Check joystick nodes:

```bash
ls -l /dev/input/js*
```

Inspect with standard Linux tools:

```bash
sudo apt-get install joystick evtest
jstest /dev/input/js0
sudo evtest /dev/input/eventX
```

## Troubleshooting

### `uinput kernel module loaded: FAIL`

```bash
sudo modprobe uinput
```

### `/dev/uinput writable: FAIL`

Run with `sudo` or configure the `input` group and udev rule shown above.

### No `/dev/input/js*` node appears

- Check whether another joystick already occupies `js0`
- Check `evtest` output for a new event device
- Stop other virtual joystick processes before retrying

### GUI cannot start

- Confirm you are in a desktop session with `DISPLAY` set
- Install `python3-tk` if Tkinter is missing
- Use `--mode simulate` or `--mode idle` on headless systems

## Integration Notes

Keep the virtual joystick process alive while your application is running. In GUI mode, closing the window removes the virtual device. In CLI modes, stop the process with `Ctrl+C`.
