"""Built-in joystick motion and button demo patterns."""

from __future__ import annotations

import math

from .state import JoystickState


def _stick(value: float) -> int:
    return max(-32768, min(32767, int(round(value * 32767))))


def _trigger(value: float) -> int:
    return max(0, min(255, int(round(value * 255))))


def idle_pattern(_: float) -> JoystickState:
    return JoystickState.neutral()


def circle_pattern(elapsed: float) -> JoystickState:
    state = JoystickState.neutral()
    state.axes["left_x"] = _stick(math.cos(elapsed * 1.3) * 0.75)
    state.axes["left_y"] = _stick(math.sin(elapsed * 1.3) * 0.75)
    state.axes["right_x"] = _stick(math.sin(elapsed * 0.6) * 0.45)
    state.axes["right_y"] = _stick(math.cos(elapsed * 0.6) * 0.45)
    state.axes["l2"] = _trigger((math.sin(elapsed) + 1) / 2)
    state.axes["r2"] = _trigger((math.cos(elapsed) + 1) / 2)
    return state


def figure8_pattern(elapsed: float) -> JoystickState:
    state = JoystickState.neutral()
    state.axes["left_x"] = _stick(math.sin(elapsed * 1.4) * 0.85)
    state.axes["left_y"] = _stick(math.sin(elapsed * 2.8) * 0.55)
    state.axes["right_x"] = _stick(math.cos(elapsed * 1.2) * 0.35)
    state.axes["right_y"] = _stick(math.sin(elapsed * 0.7) * 0.35)
    state.axes["l2"] = _trigger((math.sin(elapsed * 0.8) + 1) / 2)
    return state


def trigger_pulse_pattern(elapsed: float) -> JoystickState:
    state = JoystickState.neutral()
    state.axes["right_x"] = _stick(math.sin(elapsed * 0.9) * 0.6)
    state.axes["right_y"] = _stick(math.cos(elapsed * 0.9) * 0.6)
    state.axes["l2"] = _trigger((math.sin(elapsed * 2.0) + 1) / 2)
    state.axes["r2"] = _trigger((math.sin(elapsed * 2.0 + math.pi / 2) + 1) / 2)
    state.buttons["l1"] = int(elapsed * 3) % 2 == 0
    state.buttons["r1"] = int(elapsed * 4) % 2 == 0
    return state


def combo_demo_pattern(elapsed: float) -> JoystickState:
    state = JoystickState.neutral()
    stage = int(elapsed / 0.6) % 5
    if stage == 0:
        state.buttons["south"] = True
        state.buttons["east"] = True
    elif stage == 1:
        state.buttons["west"] = True
        state.buttons["north"] = True
    elif stage == 2:
        state.buttons["l1"] = True
        state.buttons["r1"] = True
        state.axes["l2"] = 255
        state.axes["r2"] = 255
    elif stage == 3:
        state.buttons["start"] = True
        state.buttons["select"] = True
    else:
        state.buttons["mode"] = True
        state.buttons["l3"] = True
        state.buttons["r3"] = True
    return state


PATTERNS = {
    "circle": circle_pattern,
    "combo-demo": combo_demo_pattern,
    "figure8": figure8_pattern,
    "idle": idle_pattern,
    "trigger-pulse": trigger_pulse_pattern,
}
