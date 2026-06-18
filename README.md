# Joystick Linux Fake

Joystick Linux Fake is a small Python package for creating a virtual Linux gamepad backed by `python-evdev`.

It is designed for local testing when a real controller is not available. The package exposes a Tkinter GUI for manual control, built-in simulation patterns for repeatable input, and a CLI for headless use.

## Features

- `python-evdev` backend only. No `python-uinput` dependency and no mixed device backends.
- Desktop GUI with left and right sticks, `L1`, `R1`, `L2`, `R2`, face buttons, and multi-button combinations.
- Built-in simulation patterns: `circle`, `figure8`, `trigger-pulse`, `combo-demo`, and `idle`.
- CLI modes for GUI, headless simulation, idle keep-alive, and environment checks.
- Minimal package layout with `pyproject.toml`, `requirements.txt`, and a compatibility `dummy_joystick.py` launcher.

## Requirements

- Linux
- Python 3.10+
- `python-evdev`
- Tkinter for the GUI

Tkinter ships with many Linux Python builds. If your distribution splits it into a separate package, install `python3-tk` from your system package manager.

The package does not use the `python-uinput` package. It creates the virtual controller through `evdev.UInput`, which still relies on the Linux `/dev/uinput` interface when the kernel exposes it.

## Installation

### 1. Make sure the Linux virtual input interface is available

```bash
sudo modprobe uinput
```

To load it automatically at boot:

```bash
echo "uinput" | sudo tee /etc/modules-load.d/uinput.conf
```

### 2. Install the package

From the repository root:

```bash
python -m pip install -e .
```

If you only want the runtime dependency:

```bash
python -m pip install -r requirements.txt
```

### 3. Grant access to `/dev/uinput` if you do not want to use `sudo`

```bash
sudo usermod -a -G input "$USER"
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Log out and back in after changing group membership.

## Quick Start

Run a setup check first:

```bash
joystick-linux-fake --mode check
```

Start the GUI:

```bash
joystick-linux-fake --mode gui
```

Or use the repository compatibility launcher:

```bash
sudo python3 dummy_joystick.py --mode gui
```

## GUI Usage

The GUI exposes:

- Left and right stick sliders
- `L2` and `R2` analog trigger sliders
- Face buttons `A`, `B`, `X`, `Y`
- Shoulder buttons `L1`, `R1`
- `Start`, `Select`, `Mode`, `L3`, `R3`
- Preset combo buttons and manual multi-button holds

Manual combinations work by checking multiple buttons at once. The `Tap Combo` action sends a short simultaneous press for a preset combination.

## CLI Usage

### Idle mode

Creates the device and keeps it available without moving controls:

```bash
sudo joystick-linux-fake --mode idle
```

### Simulation mode

Runs one of the built-in patterns:

```bash
sudo joystick-linux-fake --mode simulate --pattern circle
sudo joystick-linux-fake --mode simulate --pattern figure8
sudo joystick-linux-fake --mode simulate --pattern trigger-pulse
sudo joystick-linux-fake --mode simulate --pattern combo-demo
```

### Custom device name

```bash
sudo joystick-linux-fake --mode simulate --device-name "CI Test Gamepad"
```

## Verification

Check the created joystick node:

```bash
ls -l /dev/input/js*
```

Inspect events with common Linux tools:

```bash
sudo apt-get install joystick evtest
jstest /dev/input/js0
sudo evtest /dev/input/eventX
```

## Troubleshooting

### `virtual input interface not ready`

Load the module used by `evdev.UInput`:

```bash
sudo modprobe uinput
```

### `/dev/uinput writable: FAIL`

Run with `sudo` or grant your user access through the `input` group and udev rule described above.

### GUI does not open on a remote or headless system

Use one of the CLI modes instead:

```bash
joystick-linux-fake --mode simulate --pattern combo-demo
```

### `python-evdev installed: FAIL`

Install the dependency:

```bash
python -m pip install evdev
```

## Project Layout

```text
.
├── dummy_joystick.py
├── JOYSTICK_SETUP.md
├── pyproject.toml
├── requirements.txt
├── setup.py
├── src/
│   └── joystick_linux_fake/
│       ├── cli.py
│       ├── controller.py
│       ├── device.py
│       ├── gui.py
│       ├── simulations.py
│       └── state.py
└── tests/
```

## Development

Run the lightweight test suite:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Notes

- The package creates a standard dual-stick virtual gamepad through `evdev.UInput`.
- There is no `python-uinput` backend in this project.
- The active `/dev/input/js*` index depends on what is already connected on the host.
- `dummy_joystick.py` is kept as a compatibility launcher for direct repository use.
