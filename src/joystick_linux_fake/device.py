"""evdev-backed virtual joystick device."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import grp
import importlib.util
import os
import stat

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


def _has_uinput_interface() -> bool:
    return os.path.exists("/dev/uinput") or _is_uinput_loaded()


def _uinput_write_detail() -> tuple[bool, str]:
    device_path = "/dev/uinput"
    if not os.path.exists(device_path):
        return False, "Create or load the kernel module before starting the device."

    if os.access(device_path, os.W_OK):
        return True, "Write access available."

    try:
        stat_result = os.stat(device_path)
        group_name = grp.getgrgid(stat_result.st_gid).gr_name
        mode = stat.S_IMODE(stat_result.st_mode)
    except (KeyError, OSError):
        return False, "Run with sudo or grant your user access to /dev/uinput."

    active_group_ids = set(os.getgroups())
    if stat_result.st_gid not in active_group_ids:
        return (
            False,
            f"/dev/uinput is owned by group '{group_name}' with mode {mode:o}, but your current session is not in that group yet. Start a new login session or use sudo.",
        )

    return False, f"/dev/uinput is present but not writable for the current session (group '{group_name}', mode {mode:o})."


def get_environment_report() -> list[CheckResult]:
    js_devices = sorted(glob.glob("/dev/input/js*"))
    interface_available = _has_uinput_interface()
    interface_detail = (
        "Detected via /dev/uinput."
        if os.path.exists("/dev/uinput")
        else "Load with: sudo modprobe uinput"
    )
    uinput_writable, uinput_write_detail = _uinput_write_detail()
    return [
        CheckResult(
            label="python-evdev installed",
            ok=importlib.util.find_spec("evdev") is not None,
            detail="Install with: python -m pip install evdev",
        ),
        CheckResult(
            label="virtual input kernel interface available",
            ok=interface_available,
            detail=interface_detail,
        ),
        CheckResult(
            label="/dev/uinput device present",
            ok=os.path.exists("/dev/uinput"),
            detail="Create or load the kernel module before starting the device.",
        ),
        CheckResult(
            label="/dev/uinput writable",
            ok=uinput_writable,
            detail=uinput_write_detail,
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


def _resolve_ecode(ecodes_module, *names: str) -> int:
    for name in names:
        value = getattr(ecodes_module, name, None)
        if value is not None:
            return value
    raise AttributeError(f"None of the evdev ecodes are available: {', '.join(names)}")


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
            "dpad_x": e.ABS_HAT0X,
            "dpad_y": e.ABS_HAT0Y,
        }
        self._button_codes = {
            "south": _resolve_ecode(e, "BTN_SOUTH", "BTN_A"),
            "east": _resolve_ecode(e, "BTN_EAST", "BTN_B"),
            # Buttons X and Y are at the west / north cardinal positions, but joydev
            # enumerates BTN codes in numeric order.  BTN_NORTH (0x133) < BTN_WEST
            # (0x134), so if we mapped west→BTN_WEST and north→BTN_NORTH, the Y
            # button would land on js button 2 and X on js button 3 — inverted from
            # what real Xbox controllers report.  Swap the evdev codes so the
            # cardinal *names* still match physical positions but the joystick API
            # sees X on button 2 and Y on button 3.
            "west": _resolve_ecode(e, "BTN_NORTH", "BTN_Y"),
            "north": _resolve_ecode(e, "BTN_WEST", "BTN_X"),
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
                (e.ABS_HAT0X, AbsInfo(0, -1, 1, 0, 0, 0)),
                (e.ABS_HAT0Y, AbsInfo(0, -1, 1, 0, 0, 0)),
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