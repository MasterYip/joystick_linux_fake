"""State and metadata for the virtual joystick."""

from __future__ import annotations

from dataclasses import dataclass, field


AXIS_NAMES = (
    "left_x",
    "left_y",
    "right_x",
    "right_y",
    "l2",
    "r2",
    "dpad_x",
    "dpad_y",
)

BUTTON_NAMES = (
    "south",
    "east",
    "west",
    "north",
    "l1",
    "r1",
    "select",
    "start",
    "mode",
    "l3",
    "r3",
)

BUTTON_LABELS = {
    "south": "A",
    "east": "B",
    "west": "X",
    "north": "Y",
    "l1": "L1",
    "r1": "R1",
    "select": "Select",
    "start": "Start",
    "mode": "Mode",
    "l3": "L3",
    "r3": "R3",
}

AXIS_LABELS = {
    "left_x": "Left Stick X",
    "left_y": "Left Stick Y",
    "right_x": "Right Stick X",
    "right_y": "Right Stick Y",
    "l2": "L2 Trigger",
    "r2": "R2 Trigger",
    "dpad_x": "D-pad X",
    "dpad_y": "D-pad Y",
}

COMBO_PRESETS = {
    "A + B": ("south", "east"),
    "X + Y": ("west", "north"),
    "L1 + R1": ("l1", "r1"),
    "START + SELECT": ("start", "select"),
    "A + L1 + R1": ("south", "l1", "r1"),
}

AXIS_RANGES = {
    "left_x": (-32768, 32767),
    "left_y": (-32768, 32767),
    "right_x": (-32768, 32767),
    "right_y": (-32768, 32767),
    "l2": (0, 255),
    "r2": (0, 255),
    "dpad_x": (-1, 1),
    "dpad_y": (-1, 1),
}


def neutral_axes() -> dict[str, int]:
    return {name: 0 for name in AXIS_NAMES}


def neutral_buttons() -> dict[str, bool]:
    return {name: False for name in BUTTON_NAMES}


def axis_ranges_from_config(cfg) -> dict[str, tuple[int, int]]:
    """Build an ``AXIS_RANGES``-style dict from a ``JoyMappingConfig``."""
    return {am.logical: (am.min_val, am.max_val) for am in cfg.axes.values()}


def button_labels_from_config(cfg) -> dict[str, str]:
    """Build a ``BUTTON_LABELS``-style dict from a ``JoyMappingConfig``."""
    return {bm.logical: bm.label for bm in cfg.buttons.values()}


def axis_labels_from_config(cfg) -> dict[str, str]:
    """Build display labels for axes from a config."""
    return {am.logical: am.label for am in cfg.axes.values()}


def neutral_axes_from_config(cfg) -> dict[str, int]:
    """Return zero-valued axes for every axis in *cfg*."""
    return {am.logical: 0 for am in cfg.axes.values()}


def neutral_buttons_from_config(cfg) -> dict[str, bool]:
    """Return released buttons for every button in *cfg*."""
    return {bm.logical: False for bm in cfg.buttons.values()}


@dataclass
class JoystickState:
    axes: dict[str, int] = field(default_factory=neutral_axes)
    buttons: dict[str, bool] = field(default_factory=neutral_buttons)

    @classmethod
    def neutral(cls) -> "JoystickState":
        return cls()

    @classmethod
    def from_config(cls, cfg) -> "JoystickState":
        """Create a neutral state matching the axes and buttons in *cfg*."""
        return cls(
            axes=neutral_axes_from_config(cfg),
            buttons=neutral_buttons_from_config(cfg),
        )

    def copy(self) -> "JoystickState":
        return JoystickState(axes=dict(self.axes), buttons=dict(self.buttons))