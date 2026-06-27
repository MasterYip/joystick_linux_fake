"""evdev-backed virtual joystick device — configurable via ``JoyMappingConfig``."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import grp
import importlib.util
import os
import stat

from .state import JoystickState


# ---------------------------------------------------------------------------
# Lazy import of joystick_parser (avoids hard dependency when unused)
# ---------------------------------------------------------------------------

def _get_default_config():
    """Return the hardcoded Xbox mapping used when no config is provided."""
    try:
        from joystick_parser import BUILTIN_MAPPINGS

        return BUILTIN_MAPPINGS["xbox"]
    except ImportError:
        # Fallback: build a minimal Xbox-like config inline so the package
        # does not strictly require joystick_parser at import time.
        return _fallback_xbox_config()


def _fallback_xbox_config():
    """Inline Xbox mapping — only used when joystick_parser is unavailable."""
    from dataclasses import dataclass as _dc

    @_dc(slots=True)
    class _AxisMapping:
        logical: str
        label: str
        min_val: int
        max_val: int

    @_dc(slots=True)
    class _ButtonMapping:
        logical: str
        label: str

    @_dc(slots=True)
    class _FallbackConfig:
        name: str
        version: int
        axes: dict
        buttons: dict

    return _FallbackConfig(
        name="Xbox (fallback)",
        version=1,
        axes={
            0: _AxisMapping("left_x", "Left Stick X", -32768, 32767),
            1: _AxisMapping("left_y", "Left Stick Y", -32768, 32767),
            2: _AxisMapping("l2", "L2 Trigger", 0, 255),
            3: _AxisMapping("right_x", "Right Stick X", -32768, 32767),
            4: _AxisMapping("right_y", "Right Stick Y", -32768, 32767),
            5: _AxisMapping("r2", "R2 Trigger", 0, 255),
            6: _AxisMapping("dpad_x", "D-Pad X", -1, 1),
            7: _AxisMapping("dpad_y", "D-Pad Y", -1, 1),
        },
        buttons={
            0: _ButtonMapping("south", "A"),
            1: _ButtonMapping("east", "B"),
            2: _ButtonMapping("west", "X"),
            3: _ButtonMapping("north", "Y"),
            4: _ButtonMapping("l1", "LB"),
            5: _ButtonMapping("r1", "RB"),
            6: _ButtonMapping("select", "Back"),
            7: _ButtonMapping("start", "Start"),
            8: _ButtonMapping("mode", "Guide"),
            9: _ButtonMapping("l3", "L-Thumb"),
            10: _ButtonMapping("r3", "R-Thumb"),
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DeviceError(RuntimeError):
    """Raised when the virtual device cannot be created."""


@dataclass
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
            f"/dev/uinput is owned by group '{group_name}' with mode {mode:o}, "
            "but your current session is not in that group yet. "
            "Start a new login session or use sudo.",
        )
    return False, (
        f"/dev/uinput is present but not writable for the current session "
        f"(group '{group_name}', mode {mode:o})."
    )


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


# ---------------------------------------------------------------------------
# evdev code tables — map common logical names to standard evdev codes.
# Unknown names fall back to pools.
# ---------------------------------------------------------------------------

# Known axis logical names → evdev codes
_KNOWN_AXIS_CODES: dict[str, int] = {
    "left_x": 0x00,  # ABS_X
    "left_y": 0x01,  # ABS_Y
    "right_x": 0x03,  # ABS_RX
    "right_y": 0x04,  # ABS_RY
    "l2": 0x02,  # ABS_Z
    "r2": 0x05,  # ABS_RZ
    "dpad_x": 0x10,  # ABS_HAT0X
    "dpad_y": 0x11,  # ABS_HAT0Y
}

# Spare axis codes (assigned in order to unknown config axes)
_AXIS_CODE_POOL: list[int] = [
    0x00,  # ABS_X
    0x01,  # ABS_Y
    0x02,  # ABS_Z
    0x03,  # ABS_RX
    0x04,  # ABS_RY
    0x05,  # ABS_RZ
    0x06,  # ABS_THROTTLE
    0x07,  # ABS_RUDDER
    0x08,  # ABS_WHEEL
    0x09,  # ABS_GAS
    0x0A,  # ABS_BRAKE
    0x10,  # ABS_HAT0X
    0x11,  # ABS_HAT0Y
    0x12,  # ABS_HAT1X
    0x13,  # ABS_HAT1Y
    0x14,  # ABS_HAT2X
    0x15,  # ABS_HAT2Y
    0x16,  # ABS_HAT3X
    0x17,  # ABS_HAT3Y
]

# Known button logical names → (evdev_code, comment)
# "west" / "north" codes are swapped so that joydev exposes X→btn2, Y→btn3
# (BTN_NORTH 0x133 sorts before BTN_WEST 0x134 in the kernel).
_KNOWN_BTN_CODES: dict[str, int] = {
    "south": 0x130,  # BTN_SOUTH / BTN_A
    "east": 0x131,  # BTN_EAST / BTN_B
    "west": 0x133,  # → BTN_NORTH / BTN_Y  (swapped for joydev order)
    "north": 0x134,  # → BTN_WEST / BTN_X   (swapped for joydev order)
    "l1": 0x136,  # BTN_TL
    "r1": 0x137,  # BTN_TR
    "select": 0x13A,  # BTN_SELECT
    "start": 0x13B,  # BTN_START
    "mode": 0x13C,  # BTN_MODE
    "l3": 0x13D,  # BTN_THUMBL
    "r3": 0x13E,  # BTN_THUMBR
}

# Spare button codes for unknown config buttons
_BTN_CODE_POOL: list[int] = [
    0x130,  # BTN_SOUTH / A
    0x131,  # BTN_EAST / B
    0x132,  # BTN_C
    0x133,  # BTN_NORTH / Y
    0x134,  # BTN_WEST / X
    0x135,  # BTN_Z
    0x136,  # BTN_TL
    0x137,  # BTN_TR
    0x138,  # BTN_TL2
    0x139,  # BTN_TR2
    0x13A,  # BTN_SELECT
    0x13B,  # BTN_START
    0x13C,  # BTN_MODE
    0x13D,  # BTN_THUMBL
    0x13E,  # BTN_THUMBR
    0x220,  # BTN_DPAD_UP
    0x221,  # BTN_DPAD_DOWN
    0x222,  # BTN_DPAD_LEFT
    0x223,  # BTN_DPAD_RIGHT
    0x2C0,  # BTN_TRIGGER_HAPPY1
    0x2C1,  # BTN_TRIGGER_HAPPY2
    0x2C2,  # BTN_TRIGGER_HAPPY3
    0x2C3,  # BTN_TRIGGER_HAPPY4
]


def _assign_axis_codes(config) -> dict[str, int]:
    """Return ``{logical_name: evdev_code}`` for every axis in *config*."""
    mapping: dict[str, int] = {}
    pool_iter = iter(_AXIS_CODE_POOL)
    for number in sorted(config.axes):
        am = config.axes[number]
        if am.logical in _KNOWN_AXIS_CODES:
            code = _KNOWN_AXIS_CODES[am.logical]
        else:
            try:
                code = next(pool_iter)
            except StopIteration:
                raise DeviceError(
                    f"Too many axes in config — maximum is {len(_AXIS_CODE_POOL)}.  "
                    f"Cannot assign evdev code for axis '{am.logical}'."
                )
            # Mark this code as taken so a subsequent known name doesn't
            # double-assign it (unlikely but defensive).
            _KNOWN_AXIS_CODES.setdefault(am.logical, code)
        if code in mapping.values():
            raise DeviceError(
                f"Duplicate evdev axis code 0x{code:02X} for logical axis "
                f"'{am.logical}'.  Check the mapping config."
            )
        mapping[am.logical] = code
    return mapping


def _assign_button_codes(config) -> dict[str, int]:
    """Return ``{logical_name: evdev_code}`` for every button in *config*."""
    mapping: dict[str, int] = {}
    pool_iter = iter(_BTN_CODE_POOL)
    for number in sorted(config.buttons):
        bm = config.buttons[number]
        if bm.logical in _KNOWN_BTN_CODES:
            code = _KNOWN_BTN_CODES[bm.logical]
        else:
            try:
                code = next(pool_iter)
            except StopIteration:
                raise DeviceError(
                    f"Too many buttons in config — maximum is {len(_BTN_CODE_POOL)}.  "
                    f"Cannot assign evdev code for button '{bm.logical}'."
                )
            _KNOWN_BTN_CODES.setdefault(bm.logical, code)
        if code in mapping.values():
            raise DeviceError(
                f"Duplicate evdev button code 0x{code:03X} for logical button "
                f"'{bm.logical}'.  Check the mapping config."
            )
        mapping[bm.logical] = code
    return mapping


def _absinfo_for_range(min_val: int, max_val: int):
    """Build an ``evdev.AbsInfo`` appropriate for the given value range.

    Stick axes (-32768..32767) get fuzz=16, flat=128.
    Trigger axes (0..255) get fuzz=0, flat=0.
    Hat axes (-1..1) get fuzz=0, flat=0.
    Everything else uses sensible defaults.
    """
    from evdev import AbsInfo

    span = max_val - min_val
    if span >= 65535:
        # 16-bit stick
        return AbsInfo(min_val, min_val, max_val, 16, 128, 0)
    if span <= 10:
        # hat or small-range axis
        return AbsInfo(min_val, min_val, max_val, 0, 0, 0)
    # trigger / medium range
    return AbsInfo(max(min_val, 0), min_val, max_val, 0, 0, 0)


# ---------------------------------------------------------------------------
# VirtualJoystickDevice
# ---------------------------------------------------------------------------


class VirtualJoystickDevice:
    """evdev ``UInput`` wrapper whose layout is driven by a mapping config.

    Parameters
    ----------
    name:
        Visible device name (``"Joystick Linux Fake"`` by default).
    config:
        A ``JoyMappingConfig`` (from ``joystick_parser``) that defines which
        axes and buttons the device exposes.  When ``None`` the built-in Xbox
        mapping is used.
    """

    def __init__(self, name: str = "Joystick Linux Fake", config=None) -> None:
        if config is None:
            config = _get_default_config()

        from evdev import UInput, ecodes as e

        self._ecodes = e
        self._config = config

        # Build logical-name → evdev-code maps
        self._axis_codes: dict[str, int] = _assign_axis_codes(config)
        self._button_codes: dict[str, int] = _assign_button_codes(config)

        # Build AbsInfo for each axis
        abs_infos: list[tuple[int, object]] = []
        for number in sorted(config.axes):
            am = config.axes[number]
            code = self._axis_codes[am.logical]
            abs_infos.append((code, _absinfo_for_range(am.min_val, am.max_val)))

        capabilities = {
            e.EV_KEY: list(self._button_codes.values()),
            e.EV_ABS: abs_infos,
        }

        try:
            self._device = UInput(capabilities, name=name, version=0x0003)
        except OSError as exc:
            raise DeviceError(
                "Unable to create the virtual joystick. "
                "Check /dev/uinput access for the evdev backend and "
                "load the kernel interface if needed."
            ) from exc

    def write_state(self, state: JoystickState) -> None:
        for logical, code in self._axis_codes.items():
            if logical in state.axes:
                self._device.write(self._ecodes.EV_ABS, code, int(state.axes[logical]))
        for logical, code in self._button_codes.items():
            if logical in state.buttons:
                self._device.write(
                    self._ecodes.EV_KEY, code, int(state.buttons[logical])
                )
        self._device.syn()

    def close(self) -> None:
        self._device.close()
