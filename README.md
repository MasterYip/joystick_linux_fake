# Joystick Linux Fake

Joystick Linux Fake is a small Python package for creating a virtual Linux gamepad backed by `python-evdev`.

It is designed for local testing when a real controller is not available. The package exposes a Tkinter GUI for manual control, built-in simulation patterns for repeatable input, and a CLI for headless use.

## Features

- `python-evdev` backend only. No `python-uinput` dependency and no mixed device backends.
- Desktop GUI with left and right sticks, `L1`, `R1`, `L2`, `R2`, face buttons, and multi-button combinations.
- Built-in simulation patterns: `circle`, `figure8`, `trigger-pulse`, `combo-demo`, and `idle`.
- CLI modes for GUI, headless simulation, idle keep-alive, and environment checks.
- Standalone [`joystick_parser`](#joystick_parser) module — drop-in joystick event reader with built-in Xbox / PS5 mappings and YAML config support.
- [`joystick-watch`](#joystick_watch) — real-time joystick visualization GUI with live event log.
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

**Install System-wide**:

```bash
sudo apt install python3-evdev python3-tk
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

## joystick_parser

`src/joystick_parser.py` is a **standalone single-file module** — drop it into any Python project that needs to read joystick input on Linux. It reads raw `/dev/input/js*` events and maps them to logical names through built-in or YAML config files.

**Zero dependencies beyond the standard library.** PyYAML is optional (only needed when loading custom `.yaml` mapping files).

### Quick start

```python
from joystick_parser import JoystickParser

# Use a built-in mapping — no config file needed
with JoystickParser("/dev/input/js0", mapping="xbox") as parser:
    events = parser.drain_events()
    snap = parser.get_snapshot()
    print(snap.axes["left_x"], snap.buttons["south"])  # 0, False
```

### Built-in mappings

| Key | Controller | Buttons | Axes |
|-----|-----------|---------|------|
| `xbox` | Xbox 360 / One / Series | 11 | 8 |
| `ps5` | PS5 DualSense (hid-playstation) | 15 | 8 |

```python
from joystick_parser import get_mapping

cfg = get_mapping("xbox")   # built-in, no filesystem hit
cfg = get_mapping("ps5")    # built-in
cfg = get_mapping("/path/to/my_controller.yaml")  # custom YAML
```

### Custom YAML mappings

```yaml
# my_controller.yaml
name: "Custom Gamepad"
version: 1

axes:
  0: {logical: left_x,  label: "Left Stick X",  min: -32768, max: 32767}
  1: {logical: left_y,  label: "Left Stick Y",  min: -32768, max: 32767}
  # ...

buttons:
  0: {logical: south, label: "A"}
  1: {logical: east,  label: "B"}
  # ...
```

Place YAML files in `~/.config/joystick_watch/mappings/` or pass an absolute path to `get_mapping()`.

### API overview

| Method | Description |
|--------|-------------|
| `JoystickParser(device_path, mapping)` | Create a parser. `mapping` is `"xbox"`, `"ps5"`, a `JoyMappingConfig`, or a YAML file path. |
| `parser.start()` / `parser.stop()` | Start/stop the background reader thread. |
| `parser.get_snapshot() -> JoystickSnapshot` | Thread-safe copy of current axes and button state. |
| `parser.drain_events() -> list[JoystickEvent]` | Atomically drain the event queue (for polling consumers like GUI loops). |
| `parser.on_event(callback)` | Register a callback invoked from the reader thread for every event. |
| `JoystickParser.list_devices()` | Return sorted list of `/dev/input/js*` paths. |

The parser is also a context manager: `with JoystickParser(...) as p: ...`

## joystick_watch

`joystick-watch` is a Tkinter GUI for real-time joystick visualization, built on top of `joystick_parser`.

### Quick start

```bash
# Launch the GUI (auto-detects device and uses Xbox mapping)
joystick-watch

# Specify device and mapping
joystick-watch --device /dev/input/js1 --config ps5

# List available devices and mappings without opening the GUI
joystick-watch --list-devices
joystick-watch --list-mappings

# Run from source
PYTHONPATH=src python -m joystick_watch
```

### GUI layout

- **Toolbar**: device selector, mapping selector (built-ins + discovered YAML files), Start/Stop buttons, status bar
- **Axes panel**: progress bars with live numeric value labels for every axis in the mapping
- **Buttons panel**: color-coded indicators — green when pressed, grey when released
- **Event log**: dark-themed scrollable text widget showing every event (axis/button) with timestamp, number, label, and value. Init events can be shown/hidden with a checkbox.

### Mapping selection

The mapping dropdown shows:
1. **Built-in** `xbox` and `ps5` mappings (no filesystem required)
2. **YAML files** discovered from the shipped `configs/joystick_mappings/` directory and `~/.config/joystick_watch/mappings/`

Select a different mapping at any time before starting — the panels rebuild automatically.

## Verification

Check the created joystick node:

```bash
ls -l /dev/input/js*
```

### joystick-watch GUI (recommended)

The easiest way to verify joystick output:

```bash
joystick-watch
joystick-watch --device /dev/input/js1 --config ps5
```

Run from source without installing:

```bash
PYTHONPATH=src python -m joystick_watch
PYTHONPATH=src python -m joystick_watch --list-devices
PYTHONPATH=src python -m joystick_watch --list-mappings
```

### watch_js.py (CLI)

A lightweight CLI watcher is also provided:

```bash
python watch_js.py
python watch_js.py /dev/input/js0
```

If reading the joystick node fails, run it with `sudo` or adjust your input-device permissions.

### External tools

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
├── watch_js.py
├── pyproject.toml
├── requirements.txt
├── setup.py
├── src/
│   ├── joystick_parser.py              # Standalone joystick event reader
│   ├── joystick_linux_fake/            # Virtual gamepad package
│   │   ├── cli.py
│   │   ├── controller.py
│   │   ├── device.py
│   │   ├── gui.py
│   │   ├── simulations.py
│   │   └── state.py
│   └── joystick_watch/                 # Joystick visualization GUI
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       └── configs/
│           └── joystick_mappings/
│               ├── xbox.yaml
│               └── ps5.yaml
└── tests/
    ├── test_cli.py
    ├── test_simulations.py
    ├── test_joystick_parser.py
    └── test_joystick_watch.py
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
- `joystick_parser.py` is a **standalone module** — copy it into any project that needs Linux joystick input. It has no dependencies beyond the standard library (PyYAML is optional for custom YAML mappings).
- `joystick-watch` is the recommended tool for visually verifying joystick state. It works with both real and virtual joysticks.
