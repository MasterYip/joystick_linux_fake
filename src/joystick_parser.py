#!/usr/bin/env python3
"""Standalone joystick event parser for Linux /dev/input/js* devices.

Drop this single file into any project that needs joystick input.  Zero
dependencies beyond the standard library -- PyYAML is optional (only needed
when loading external mapping files).

Usage::

    from joystick_parser import JoystickParser

    parser = JoystickParser("/dev/input/js0", mapping="xbox")
    parser.on_event(lambda e: print(f"{e.label} = {e.value}"))
    parser.start()

    # … later …
    snap = parser.get_snapshot()
    print(snap.axes["left_x"], snap.buttons["south"])

    parser.stop()

    # Or as a context manager:
    with JoystickParser("/dev/input/js0", mapping="ps5") as p:
        events = p.drain_events()
        ...
"""

from __future__ import annotations

import glob
import os
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Constants (js_event struct -- identical to Linux's <linux/joystick.h>)
# ---------------------------------------------------------------------------

_JS_EVENT_FORMAT = "IhBB"
_JS_EVENT_SIZE = struct.calcsize(_JS_EVENT_FORMAT)
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AxisMapping:
    """Maps a physical axis number to a logical name and display label."""

    logical: str
    label: str
    min_val: int
    max_val: int


@dataclass
class ButtonMapping:
    """Maps a physical button number to a logical name and display label."""

    logical: str
    label: str


@dataclass
class JoyMappingConfig:
    """Complete joystick mapping: axis + button number → logical name + label."""

    name: str
    version: int
    axes: dict[int, AxisMapping] = field(default_factory=dict)
    buttons: dict[int, ButtonMapping] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "JoyMappingConfig":
        """Build a JoyMappingConfig from an already-parsed dict."""
        axes: dict[int, AxisMapping] = {}
        for num_str, obj in raw.get("axes", {}).items():
            n = int(num_str)
            axes[n] = AxisMapping(
                logical=obj["logical"],
                label=obj["label"],
                min_val=int(obj["min"]),
                max_val=int(obj["max"]),
            )
        buttons: dict[int, ButtonMapping] = {}
        for num_str, obj in raw.get("buttons", {}).items():
            n = int(num_str)
            buttons[n] = ButtonMapping(logical=obj["logical"], label=obj["label"])
        return JoyMappingConfig(
            name=raw.get("name", "Unknown"),
            version=int(raw.get("version", 1)),
            axes=axes,
            buttons=buttons,
        )

    @staticmethod
    def from_file(path: str | Path) -> "JoyMappingConfig":
        """Parse a YAML mapping file and return a JoyMappingConfig.

        Requires PyYAML.  Raises ImportError with a clear message if it is
        not installed.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required to load joystick mapping files.  "
                "Install it with:  pip install pyyaml"
            ) from None

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid mapping file: {path} (expected a YAML dict)")
        return JoyMappingConfig.from_dict(raw)


# ---------------------------------------------------------------------------
# Built-in mappings -- no filesystem required
# ---------------------------------------------------------------------------


def _xbox_mapping() -> JoyMappingConfig:
    return JoyMappingConfig(
        name="Xbox 360 / One / Series",
        version=1,
        axes={
            0: AxisMapping("left_x", "Left Stick X", -32768, 32767),
            1: AxisMapping("left_y", "Left Stick Y", -32768, 32767),
            2: AxisMapping("l2", "L2 Trigger", 0, 255),
            3: AxisMapping("right_x", "Right Stick X", -32768, 32767),
            4: AxisMapping("right_y", "Right Stick Y", -32768, 32767),
            5: AxisMapping("r2", "R2 Trigger", 0, 255),
            6: AxisMapping("dpad_x", "D-Pad X", -1, 1),
            7: AxisMapping("dpad_y", "D-Pad Y", -1, 1),
        },
        buttons={
            0: ButtonMapping("south", "A"),
            1: ButtonMapping("east", "B"),
            2: ButtonMapping("west", "X"),
            3: ButtonMapping("north", "Y"),
            4: ButtonMapping("l1", "LB"),
            5: ButtonMapping("r1", "RB"),
            6: ButtonMapping("select", "Back"),
            7: ButtonMapping("start", "Start"),
            8: ButtonMapping("mode", "Guide"),
            9: ButtonMapping("l3", "L-Thumb"),
            10: ButtonMapping("r3", "R-Thumb"),
        },
    )


def _ps5_mapping() -> JoyMappingConfig:
    return JoyMappingConfig(
        name="PS5 DualSense (hid-playstation)",
        version=1,
        axes={
            0: AxisMapping("left_x", "Left Stick X", -32768, 32767),
            1: AxisMapping("left_y", "Left Stick Y", -32768, 32767),
            2: AxisMapping("right_x", "Right Stick X", -32768, 32767),
            3: AxisMapping("l2", "L2 Trigger", 0, 255),
            4: AxisMapping("right_y", "Right Stick Y", -32768, 32767),
            5: AxisMapping("r2", "R2 Trigger", 0, 255),
            6: AxisMapping("dpad_x", "D-Pad X", -1, 1),
            7: AxisMapping("dpad_y", "D-Pad Y", -1, 1),
        },
        buttons={
            0: ButtonMapping("south", "Cross"),
            1: ButtonMapping("east", "Circle"),
            2: ButtonMapping("west", "Square"),
            3: ButtonMapping("north", "Triangle"),
            4: ButtonMapping("l1", "L1"),
            5: ButtonMapping("r1", "R1"),
            6: ButtonMapping("l2_btn", "L2 Button"),
            7: ButtonMapping("r2_btn", "R2 Button"),
            8: ButtonMapping("select", "Share"),
            9: ButtonMapping("start", "Options"),
            10: ButtonMapping("mode", "PS"),
            11: ButtonMapping("l3", "L3"),
            12: ButtonMapping("r3", "R3"),
            13: ButtonMapping("touchpad", "Touchpad"),
            14: ButtonMapping("mic", "Mic"),
        },
    )


BUILTIN_MAPPINGS: dict[str, JoyMappingConfig] = {
    "xbox": _xbox_mapping(),
    "ps5": _ps5_mapping(),
}
"""Hardcoded mappings for common controllers.  Use `get_mapping("xbox")` etc."""

# ---------------------------------------------------------------------------
# Config discovery & loading
# ---------------------------------------------------------------------------


def _shipped_config_dir() -> Path | None:
    """Path to the shipped ``configs/joystick_mappings/`` directory.

    Returns ``None`` when running from a zip / the directory doesn't exist.
    """
    candidate = Path(__file__).resolve().parent / "configs" / "joystick_mappings"
    if candidate.is_dir():
        return candidate
    # Fallback for when joystick_parser.py is used standalone (not in the
    # joystick_watch package tree): search relative to CWD.
    cwd_candidate = Path("configs/joystick_mappings")
    if cwd_candidate.is_dir():
        return cwd_candidate.resolve()
    return None


def _user_config_dir() -> Path:
    """XDG-style user config directory for custom mappings."""
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "joystick_watch" / "mappings"


def discover_configs(search_paths: list[str] | None = None) -> list[tuple[str, str]]:
    """Scan config directories for YAML mapping files.

    Returns a list of ``(display_name, file_path)`` pairs.  The display name
    is read from the YAML ``name`` field when possible; otherwise the stem of
    the filename is used.

    Directories scanned (in order):
    * *search_paths* (when provided)
    * The shipped ``configs/joystick_mappings/`` directory (if it exists)
    * ``~/.config/joystick_watch/mappings/``
    """
    dirs: list[Path] = [Path(p) for p in (search_paths or [])]
    shipped = _shipped_config_dir()
    if shipped is not None:
        dirs.append(shipped)
    dirs.append(_user_config_dir())

    seen: set[str] = set()
    results: list[tuple[str, str]] = []

    for directory in dirs:
        if not directory.is_dir():
            continue
        for yaml_path in sorted(directory.glob("*.yaml")):
            yaml_path_str = str(yaml_path)
            if yaml_path_str in seen:
                continue
            seen.add(yaml_path_str)
            # Try to extract the display name from the YAML without heavy parsing.
            display = _read_yaml_name(yaml_path) or yaml_path.stem
            results.append((display, yaml_path_str))

    return results


def _read_yaml_name(path: Path) -> str | None:
    """Read the ``name`` field from a YAML file with minimal parsing."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            # Handle quoted and unquoted values.
            value = stripped.removeprefix("name:").strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value or None
    return None


def load_config(path: str | Path) -> JoyMappingConfig:
    """Convenience: load one mapping from a YAML file path."""
    return JoyMappingConfig.from_file(path)


def get_mapping(identifier: str) -> JoyMappingConfig:
    """Resolve a mapping identifier to a :class:`JoyMappingConfig`.

    Resolution order:
    1. Built-in names: ``"xbox"``, ``"ps5"``
    2. Filesystem path to a ``.yaml`` or ``.yml`` file
    3. Raise :class:`ValueError`
    """
    if identifier in BUILTIN_MAPPINGS:
        return BUILTIN_MAPPINGS[identifier]

    # Try as a filesystem path.
    path = Path(identifier)
    if not path.exists():
        path = Path(identifier + ".yaml")
    if path.is_file():
        return JoyMappingConfig.from_file(path)

    builtins = ", ".join(BUILTIN_MAPPINGS)
    raise ValueError(
        f"Unknown mapping '{identifier}'.  "
        f"Built-in mappings: {builtins}.  "
        f"Or provide a path to a YAML mapping file."
    )


# ---------------------------------------------------------------------------
# Event & snapshot types
# ---------------------------------------------------------------------------


@dataclass
class JoystickEvent:
    """A single parsed joystick event with mapped logical names."""

    timestamp_ms: int
    event_type: str  # "axis" | "button"
    number: int  # raw physical number
    value: int  # raw value
    logical: str  # mapped logical name ("left_x", "south", …)
    label: str  # mapped display label ("Left Stick X", "A", …)
    is_init: bool = False


@dataclass
class JoystickSnapshot:
    """Thread-safe point-in-time copy of joystick axis and button state."""

    axes: dict[str, int]  # logical_name → raw value
    buttons: dict[str, bool]  # logical_name → pressed
    timestamp: float  # time.monotonic() when the snapshot was taken


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class JoystickParser:
    """Reads raw ``/dev/input/js*`` events from a Linux joystick device.

    Parses events in a background daemon thread and exposes them via a
    thread-safe queue (polled with ``drain_events()``) and callbacks.

    Parameters
    ----------
    device_path:
        Path to the joystick device, e.g. ``"/dev/input/js0"``.
    mapping:
        Either a :class:`JoyMappingConfig` instance, or a string identifier.
        Strings are resolved by :func:`get_mapping` (builtin ``"xbox"`` /
        ``"ps5"``, or path to a YAML file).
    max_event_queue:
        Maximum number of events to buffer.  Older events are dropped when
        the buffer is full (protects against memory growth when the consumer
        falls behind).
    """

    def __init__(
        self,
        device_path: str,
        mapping: JoyMappingConfig | str = "xbox",
        *,
        max_event_queue: int = 4096,
    ) -> None:
        self.device_path = device_path
        if isinstance(mapping, JoyMappingConfig):
            self.mapping = mapping
        else:
            self.mapping = get_mapping(mapping)

        self._max_queue = max_event_queue

        # Private state (protected by _lock)
        self._running = False
        self._thread: threading.Thread | None = None
        self._fd = None  # raw binary file handle
        self._lock = threading.Lock()
        self._axes: dict[int, int] = {}
        self._buttons: dict[int, int] = {}
        self._queue: deque[JoystickEvent] = deque(maxlen=max_event_queue)
        self._callbacks: list[Callable[[JoystickEvent], None]] = []

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Open the device and start the background reader thread."""
        if self._running:
            return
        self._fd = open(self.device_path, "rb", buffering=0)
        # Absorb synthetic INIT events into the state dicts first.
        self._absorb_init_events()
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, name="joystick-parser", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the reader thread to exit, join it, and close the device."""
        self._running = False
        # Close the fd to unblock the background thread's read() call.
        with self._lock:
            fd = self._fd
            self._fd = None
        if fd is not None:
            try:
                fd.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ---- context manager --------------------------------------------------

    def __enter__(self) -> "JoystickParser":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ---- callbacks --------------------------------------------------------

    def on_event(self, callback: Callable[[JoystickEvent], None]) -> None:
        """Register a callback invoked from the **reader thread** for every event.

        If the callback needs to touch GUI widgets, it **must** schedule the
        work on the main thread (e.g. via ``root.after(0, ...)`` in tkinter).
        """
        self._callbacks.append(callback)

    # ---- snapshot (thread-safe) -------------------------------------------

    def get_snapshot(self) -> JoystickSnapshot:
        """Return a consistent point-in-time copy of axis and button state."""
        with self._lock:
            axes = {
                self._mapped_axis_name(num): val
                for num, val in self._axes.items()
            }
            buttons = {
                self._mapped_button_name(num): bool(val)
                for num, val in self._buttons.items()
            }
        return JoystickSnapshot(axes=axes, buttons=buttons, timestamp=time.monotonic())

    # ---- event drain (for polling consumers) ------------------------------

    def drain_events(self) -> list[JoystickEvent]:
        """Atomically drain and return all queued events.

        Designed for consumers that poll from a main/GUI thread.  After
        draining events, call :meth:`get_snapshot` to update the UI.
        """
        with self._lock:
            if not self._queue:
                return []
            events = list(self._queue)
            self._queue.clear()
            return events

    # ---- static helpers ---------------------------------------------------

    @staticmethod
    def list_devices() -> list[str]:
        """Return sorted list of ``/dev/input/js*`` device paths."""
        return sorted(glob.glob("/dev/input/js*"))

    @staticmethod
    def default_device() -> str:
        """Return the first available js device.

        Raises :class:`FileNotFoundError` if none is found.
        """
        devices = JoystickParser.list_devices()
        if not devices:
            raise FileNotFoundError(
                "No joystick devices found under /dev/input/js*"
            )
        return devices[0]

    # ---- internal ---------------------------------------------------------

    def _mapped_axis_name(self, number: int) -> str:
        """Resolve an axis number to its logical name, falling back to a numeric key."""
        mapping = self.mapping.axes.get(number)
        return mapping.logical if mapping else f"axis_{number}"

    def _mapped_button_name(self, number: int) -> str:
        """Resolve a button number to its logical name, falling back to a numeric key."""
        mapping = self.mapping.buttons.get(number)
        return mapping.logical if mapping else f"button_{number}"

    def _event_meta(self, number: int, is_axis: bool) -> tuple[str, str]:
        """Return ``(logical, label)`` for a raw axis or button number."""
        if is_axis:
            m = self.mapping.axes.get(number)
            if m is not None:
                return m.logical, m.label
            return f"axis_{number}", f"Axis {number}"
        else:
            m = self.mapping.buttons.get(number)
            if m is not None:
                return m.logical, m.label
            return f"button_{number}", f"Button {number}"

    def _absorb_init_events(self) -> None:
        """Drain any pending synthetic INIT events from the kernel buffer.

        The kernel emits an INIT event for every supported axis and button
        when the device is first opened.  We read them into our state dicts
        so the initial snapshot reflects the real neutral state instead of
        all-zero defaults.
        """
        assert self._fd is not None
        # We can't call select/poll on a raw fd easily from Python without
        # the select module.  Instead we'll do a short heuristic read: most
        # kernels flush INIT events immediately and then go quiet.
        # We read whatever is immediately available by setting O_NONBLOCK.
        import fcntl

        flags = fcntl.fcntl(self._fd, fcntl.F_GETFL)
        fcntl.fcntl(self._fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        try:
            init_events = []
            while True:
                try:
                    payload = self._fd.read(_JS_EVENT_SIZE)
                except BlockingIOError:
                    break
                if payload is None or len(payload) != _JS_EVENT_SIZE:
                    break
                timestamp_ms, value, event_type, number = struct.unpack(
                    _JS_EVENT_FORMAT, payload
                )
                if not (event_type & JS_EVENT_INIT):
                    # Not an init event — put it back? We can't un-read.
                    # Just queue it as a normal event.
                    logical, label = self._event_meta(
                        number, bool(event_type & JS_EVENT_AXIS)
                    )
                    init_events.append(
                        JoystickEvent(
                            timestamp_ms=timestamp_ms,
                            event_type=(
                                "axis"
                                if (event_type & ~JS_EVENT_INIT) == JS_EVENT_AXIS
                                else "button"
                            ),
                            number=number,
                            value=value,
                            logical=logical,
                            label=label,
                            is_init=False,
                        )
                    )
                    continue
                base_type = event_type & ~JS_EVENT_INIT
                if base_type == JS_EVENT_AXIS:
                    self._axes[number] = value
                elif base_type == JS_EVENT_BUTTON:
                    self._buttons[number] = value
            # Re-queue non-init events we captured.
            for ev in init_events:
                self._queue.append(ev)
        finally:
            fcntl.fcntl(self._fd, fcntl.F_SETFL, flags)

    def _read_loop(self) -> None:
        """Background thread: block-read 8-byte events, parse, update state, enqueue."""
        while self._running:
            # Get a local reference to the fd in case stop() sets it to None.
            with self._lock:
                fd = self._fd
            if fd is None:
                return

            try:
                payload = fd.read(_JS_EVENT_SIZE)
            except (ValueError, OSError):
                # fd closed by stop() or device disconnected.
                self._running = False
                break

            if payload is None or len(payload) != _JS_EVENT_SIZE:
                self._running = False
                break

            try:
                timestamp_ms, value, event_type, number = struct.unpack(
                    _JS_EVENT_FORMAT, payload
                )
            except struct.error:
                self._running = False
                break
            is_init = bool(event_type & JS_EVENT_INIT)
            base_type = event_type & ~JS_EVENT_INIT
            is_axis = base_type == JS_EVENT_AXIS

            logical, label = self._event_meta(number, is_axis)

            event = JoystickEvent(
                timestamp_ms=timestamp_ms,
                event_type="axis" if is_axis else "button",
                number=number,
                value=value,
                logical=logical,
                label=label,
                is_init=is_init,
            )

            # Update persistent state.
            with self._lock:
                if is_axis:
                    self._axes[number] = value
                else:
                    self._buttons[number] = value
                self._queue.append(event)

            # Fire callbacks (outside the lock to prevent deadlocks).
            for cb in self._callbacks:
                try:
                    cb(event)
                except Exception:
                    pass
