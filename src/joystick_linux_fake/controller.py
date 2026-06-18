"""High-level controller that streams state into the evdev device."""

from __future__ import annotations

import threading
import time

from .device import VirtualJoystickDevice
from .simulations import PATTERNS
from .state import AXIS_RANGES, JoystickState


def clamp_axis(axis_name: str, value: int) -> int:
    low, high = AXIS_RANGES[axis_name]
    return max(low, min(high, int(value)))


class JoystickController:
    """Owns the virtual joystick device and a steady state write loop."""

    def __init__(self, device_name: str = "Joystick Linux Fake", update_rate_hz: int = 125) -> None:
        self.device_name = device_name
        self.update_rate_hz = update_rate_hz
        self._device: VirtualJoystickDevice | None = None
        self._state = JoystickState.neutral()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._device = VirtualJoystickDevice(name=self.device_name)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._write_loop, name="joystick-writer", daemon=True)
        self._thread.start()

    def _write_loop(self) -> None:
        assert self._device is not None
        interval = 1 / max(1, self.update_rate_hz)
        while not self._stop_event.is_set():
            with self._lock:
                snapshot = self._state.copy()
            self._device.write_state(snapshot)
            self._stop_event.wait(interval)

    def snapshot(self) -> JoystickState:
        with self._lock:
            return self._state.copy()

    def apply_state(self, state: JoystickState) -> None:
        with self._lock:
            self._state = state.copy()

    def reset(self) -> None:
        self.apply_state(JoystickState.neutral())

    def set_axis(self, axis_name: str, value: int) -> None:
        with self._lock:
            self._state.axes[axis_name] = clamp_axis(axis_name, value)

    def set_button(self, button_name: str, pressed: bool) -> None:
        with self._lock:
            self._state.buttons[button_name] = bool(pressed)

    def tap_buttons(self, button_names: tuple[str, ...], duration: float = 0.18) -> None:
        with self._lock:
            previous = {name: self._state.buttons[name] for name in button_names}
            for name in button_names:
                self._state.buttons[name] = True

        def restore() -> None:
            time.sleep(duration)
            with self._lock:
                for name in button_names:
                    self._state.buttons[name] = previous[name]

        threading.Thread(target=restore, name="joystick-tap", daemon=True).start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._device is not None:
            self._device.close()
            self._device = None
        self._thread = None


class SimulationSession:
    """Runs one simulation pattern at a time and feeds it into the controller."""

    def __init__(self, controller: JoystickController, update_rate_hz: int = 60) -> None:
        self.controller = controller
        self.update_rate_hz = update_rate_hz
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, pattern_name: str) -> None:
        if pattern_name not in PATTERNS:
            raise ValueError(f"Unknown pattern: {pattern_name}")
        self.stop(reset=False)
        self._stop_event.clear()

        def run() -> None:
            started = time.monotonic()
            interval = 1 / max(1, self.update_rate_hz)
            pattern = PATTERNS[pattern_name]
            while not self._stop_event.is_set():
                elapsed = time.monotonic() - started
                self.controller.apply_state(pattern(elapsed))
                self._stop_event.wait(interval)

        self._thread = threading.Thread(target=run, name="joystick-sim", daemon=True)
        self._thread.start()

    def stop(self, reset: bool = True) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if reset:
            self.controller.reset()