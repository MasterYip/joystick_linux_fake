"""High-level controller that streams state into the evdev device."""

from __future__ import annotations

import threading
import time

from .device import VirtualJoystickDevice
from .simulations import PATTERNS
from .state import JoystickState, axis_ranges_from_config, neutral_axes_from_config, neutral_buttons_from_config


class JoystickController:
    """Owns the virtual joystick device and a steady-state write loop.

    Parameters
    ----------
    device_name:
        Visible name for the virtual device.
    update_rate_hz:
        State-refresh rate in Hz.
    config:
        A ``JoyMappingConfig`` (from ``joystick_parser``) that defines the
        axes and buttons exposed by the device.  When ``None`` the built-in
        Xbox mapping is used.
    """

    def __init__(
        self,
        device_name: str = "Joystick Linux Fake",
        update_rate_hz: int = 125,
        config=None,
    ) -> None:
        self.device_name = device_name
        self.update_rate_hz = update_rate_hz
        self.config = config
        self._axis_ranges: dict[str, tuple[int, int]] = (
            axis_ranges_from_config(config) if config is not None else {}
        )
        self._device: VirtualJoystickDevice | None = None
        self._state = self._make_neutral_state()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _make_neutral_state(self) -> JoystickState:
        if self.config is not None:
            return JoystickState(
                axes=neutral_axes_from_config(self.config),
                buttons=neutral_buttons_from_config(self.config),
            )
        return JoystickState.neutral()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._device = VirtualJoystickDevice(name=self.device_name, config=self.config)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._write_loop, name="joystick-writer", daemon=True
        )
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
        self.apply_state(self._make_neutral_state())

    def _clamp_axis(self, axis_name: str, value: int) -> int:
        """Clamp *value* to the configured range for *axis_name*."""
        if self.config is not None:
            low, high = self._axis_ranges.get(axis_name, (-32768, 32767))
        else:
            from .state import AXIS_RANGES
            low, high = AXIS_RANGES.get(axis_name, (-32768, 32767))
        return max(low, min(high, int(value)))

    def set_axis(self, axis_name: str, value: int) -> None:
        with self._lock:
            self._state.axes[axis_name] = self._clamp_axis(axis_name, value)

    def set_button(self, button_name: str, pressed: bool) -> None:
        with self._lock:
            self._state.buttons[button_name] = bool(pressed)

    def tap_buttons(
        self, button_names: tuple[str, ...], duration: float = 0.18
    ) -> None:
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
    """Runs one simulation pattern and feeds it into the controller."""

    def __init__(
        self, controller: JoystickController, update_rate_hz: int = 60
    ) -> None:
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
