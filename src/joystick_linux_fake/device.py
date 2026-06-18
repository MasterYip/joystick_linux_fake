"""evdev-backed virtual joystick device."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import importlib.util
import os

from .state import JoystickState


class DeviceError(RuntimeError):
    """Raised when the virtual device cannot be created."""


@dataclass(slots=True)
class CheckResult:
    label: str
    ok: bool
    detail: str


def _is_uinput_loaded() -> bool:
    try:
        with open("/proc/modules", "r", encoding="utf-8") as handle:
            return any(line.startswith("uinput ") for line in handle)
    except OSError:
        return False


def get_environment_report() -> list[CheckResult]:
    js_devices = sorted(glob.glob("/dev/input/js*"))
    return [
        CheckResult(
            label="python-evdev installed",
            ok=importlib.util.find_spec("evdev") is not None,
            detail="Install with: python -m pip install evdev",
        ),
        CheckResult(
            label="virtual input kernel interface available",
            ok=_is_uinput_loaded(),
            detail="Load with: sudo modprobe uinput",
        ),
        CheckResult(
            label="/dev/uinput device present",
            ok=os.path.exists("/dev/uinput"),
            detail="Create or load the kernel module before starting the device.",
        ),
        CheckResult(
            label="/dev/uinput writable",
            ok=os.access("/dev/uinput", os.W_OK),
            detail="Run with sudo or grant your user access to /dev/uinput.",
        ),
        CheckResult(
            label="Existing joystick nodes",
            ok=True,
            detail=", ".join(js_devices) if js_devices else "none detected",
        ),
    ]


def format_environment_report(report: list[CheckResult]) -> str:
    lines = ["Environment check", "================="]
    for item in report:
        status = "OK" if item.ok else "FAIL"
        lines.append(f"[{status}] {item.label}: {item.detail}")
    return "\n".join(lines)


class VirtualJoystickDevice:
    """Thin wrapper around evdev.UInput for a standard dual-stick gamepad."""

    def __init__(self, name: str = "Joystick Linux Fake") -> None:
        from evdev import AbsInfo, UInput, ecodes as e

        self._ecodes = e
        self._axis_codes = {
            "left_x": e.ABS_X,
            "left_y": e.ABS_Y,
            "right_x": e.ABS_RX,
            "right_y": e.ABS_RY,
            "l2": e.ABS_Z,
            "r2": e.ABS_RZ,
        }
        self._button_codes = {
            "south": e.BTN_SOUTH,
            "east": e.BTN_EAST,
            "west": e.BTN_WEST,
            "north": e.BTN_NORTH,
            "l1": e.BTN_TL,
            "r1": e.BTN_TR,
            "select": e.BTN_SELECT,
            "start": e.BTN_START,
            "mode": e.BTN_MODE,
            "l3": e.BTN_THUMBL,
            "r3": e.BTN_THUMBR,
        }
        capabilities = {
            e.EV_KEY: list(self._button_codes.values()),
            e.EV_ABS: [
                (e.ABS_X, AbsInfo(0, -32768, 32767, 16, 128, 0)),
                (e.ABS_Y, AbsInfo(0, -32768, 32767, 16, 128, 0)),
                (e.ABS_RX, AbsInfo(0, -32768, 32767, 16, 128, 0)),
                (e.ABS_RY, AbsInfo(0, -32768, 32767, 16, 128, 0)),
                (e.ABS_Z, AbsInfo(0, 0, 255, 0, 0, 0)),
                (e.ABS_RZ, AbsInfo(0, 0, 255, 0, 0, 0)),
            ],
        }

        try:
            self._device = UInput(capabilities, name=name, version=0x0003)
        except OSError as exc:
            raise DeviceError(
                "Unable to create the virtual joystick. Check /dev/uinput access for the evdev backend and load the kernel interface if needed."
            ) from exc

    def write_state(self, state: JoystickState) -> None:
        for axis_name, code in self._axis_codes.items():
            self._device.write(self._ecodes.EV_ABS, code, int(state.axes[axis_name]))
        for button_name, code in self._button_codes.items():
            self._device.write(self._ecodes.EV_KEY, code, int(state.buttons[button_name]))
        self._device.syn()

    def close(self) -> None:
        self._device.close()