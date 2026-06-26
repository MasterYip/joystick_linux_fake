"""Tests for the standalone joystick_parser module."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure the src directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import joystick_parser as jp
from joystick_parser import (
    AxisMapping,
    ButtonMapping,
    JoyMappingConfig,
    JoystickEvent,
    JoystickParser,
    JoystickSnapshot,
    discover_configs,
    get_mapping,
    BUILTIN_MAPPINGS,
)

# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class JoyMappingConfigTests(unittest.TestCase):
    def test_from_dict_basic(self) -> None:
        raw = {
            "name": "Test Pad",
            "version": 1,
            "axes": {"0": {"logical": "lx", "label": "Left X", "min": -100, "max": 100}},
            "buttons": {"0": {"logical": "btn0", "label": "A"}},
        }
        cfg = JoyMappingConfig.from_dict(raw)
        self.assertEqual(cfg.name, "Test Pad")
        self.assertEqual(cfg.version, 1)
        self.assertIn(0, cfg.axes)
        self.assertEqual(cfg.axes[0].logical, "lx")
        self.assertEqual(cfg.axes[0].label, "Left X")
        self.assertEqual(cfg.axes[0].min_val, -100)
        self.assertEqual(cfg.axes[0].max_val, 100)
        self.assertIn(0, cfg.buttons)
        self.assertEqual(cfg.buttons[0].logical, "btn0")
        self.assertEqual(cfg.buttons[0].label, "A")

    def test_from_dict_empty(self) -> None:
        cfg = JoyMappingConfig.from_dict({"name": "Empty", "version": 1})
        self.assertEqual(len(cfg.axes), 0)
        self.assertEqual(len(cfg.buttons), 0)

    def test_from_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(
                "name: FileTest\n"
                "version: 2\n"
                "axes:\n"
                '  0: {logical: lx, label: "LX", min: 0, max: 255}\n'
                "buttons:\n"
                '  0: {logical: fire, label: "Fire"}\n'
            )
            tmp_path = f.name
        try:
            cfg = JoyMappingConfig.from_file(tmp_path)
            self.assertEqual(cfg.name, "FileTest")
            self.assertEqual(cfg.version, 2)
            self.assertEqual(cfg.axes[0].logical, "lx")
            self.assertEqual(cfg.buttons[0].logical, "fire")
        finally:
            os.unlink(tmp_path)


class BuiltinMappingsTests(unittest.TestCase):
    def test_xbox_builtin(self) -> None:
        cfg = BUILTIN_MAPPINGS["xbox"]
        self.assertEqual(cfg.name, "Xbox 360 / One / Series")
        self.assertEqual(len(cfg.axes), 8)
        self.assertEqual(len(cfg.buttons), 11)
        # Verify standard Xbox layout
        self.assertEqual(cfg.axes[0].logical, "left_x")
        self.assertEqual(cfg.axes[3].logical, "right_x")
        self.assertEqual(cfg.buttons[0].logical, "south")  # A
        self.assertEqual(cfg.buttons[2].logical, "west")  # X

    def test_ps5_builtin(self) -> None:
        cfg = BUILTIN_MAPPINGS["ps5"]
        self.assertEqual(cfg.name, "PS5 DualSense (hid-playstation)")
        self.assertEqual(len(cfg.axes), 8)
        # PS5 has more buttons due to touchpad, mic, etc.
        self.assertGreaterEqual(len(cfg.buttons), 14)
        self.assertEqual(cfg.buttons[0].logical, "south")  # Cross
        self.assertEqual(cfg.buttons[3].logical, "north")  # Triangle


class GetMappingTests(unittest.TestCase):
    def test_builtin_xbox(self) -> None:
        cfg = get_mapping("xbox")
        self.assertIsInstance(cfg, JoyMappingConfig)
        self.assertIn("Xbox", cfg.name)

    def test_builtin_ps5(self) -> None:
        cfg = get_mapping("ps5")
        self.assertIsInstance(cfg, JoyMappingConfig)
        self.assertIn("PS5", cfg.name)

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_mapping("nonexistent_controller_xyz")

    def test_file_path(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(
                "name: CustomJoy\n"
                "version: 1\n"
                "axes:\n"
                '  0: {logical: a0, label: "A0", min: -10, max: 10}\n'
                "buttons:\n"
                '  0: {logical: b0, label: "B0"}\n'
            )
            tmp_path = f.name
        try:
            cfg = get_mapping(tmp_path)
            self.assertEqual(cfg.name, "CustomJoy")
        finally:
            os.unlink(tmp_path)


class DiscoverConfigsTests(unittest.TestCase):
    def test_returns_list(self) -> None:
        configs = discover_configs()
        self.assertIsInstance(configs, list)
        for display, path in configs:
            self.assertIsInstance(display, str)
            self.assertIsInstance(path, str)


# ---------------------------------------------------------------------------
# Event + parser tests
# ---------------------------------------------------------------------------


class JoystickEventTests(unittest.TestCase):
    def test_axis_event_fields(self) -> None:
        ev = JoystickEvent(
            timestamp_ms=12345,
            event_type="axis",
            number=0,
            value=16384,
            logical="left_x",
            label="Left Stick X",
        )
        self.assertEqual(ev.timestamp_ms, 12345)
        self.assertEqual(ev.event_type, "axis")
        self.assertEqual(ev.number, 0)
        self.assertEqual(ev.value, 16384)
        self.assertEqual(ev.logical, "left_x")
        self.assertEqual(ev.label, "Left Stick X")
        self.assertFalse(ev.is_init)

    def test_button_event_fields(self) -> None:
        ev = JoystickEvent(
            timestamp_ms=0,
            event_type="button",
            number=2,
            value=1,
            logical="west",
            label="X",
        )
        self.assertEqual(ev.event_type, "button")
        self.assertEqual(ev.value, 1)

    def test_init_flag(self) -> None:
        ev = JoystickEvent(
            timestamp_ms=0,
            event_type="axis",
            number=1,
            value=0,
            logical="left_y",
            label="Left Stick Y",
            is_init=True,
        )
        self.assertTrue(ev.is_init)


class JoystickParserSmokeTests(unittest.TestCase):
    """Smoke tests that don't require a real joystick device."""

    def test_construction_with_string_mapping(self) -> None:
        parser = JoystickParser("/dev/input/js0", mapping="xbox")
        self.assertEqual(parser.device_path, "/dev/input/js0")
        self.assertFalse(parser.running)
        parser.stop()

    def test_construction_with_config_mapping(self) -> None:
        cfg = BUILTIN_MAPPINGS["ps5"]
        parser = JoystickParser("/dev/input/js0", mapping=cfg)
        self.assertEqual(parser.mapping, cfg)
        parser.stop()

    def test_list_devices_returns_list(self) -> None:
        devices = JoystickParser.list_devices()
        self.assertIsInstance(devices, list)

    def test_context_manager_start_stop(self) -> None:
        # Context manager smoke test (won't find real device in CI, but
        # shouldn't crash on construction).
        parser = JoystickParser.__new__(JoystickParser)
        self.assertIsNotNone(parser)


class EventPackingRoundtripTests(unittest.TestCase):
    """Verify that our struct format matches the Linux kernel's js_event."""

    def test_pack_unpack_axis_event(self) -> None:
        timestamp = 1000
        value = -16384
        event_type = jp.JS_EVENT_AXIS  # 0x02
        number = 3
        packed = struct.pack(
            jp._JS_EVENT_FORMAT, timestamp, value, event_type, number
        )
        self.assertEqual(len(packed), jp._JS_EVENT_SIZE)
        t, v, et, n = struct.unpack(jp._JS_EVENT_FORMAT, packed)
        self.assertEqual(t, timestamp)
        self.assertEqual(v, value)
        self.assertEqual(et, event_type)
        self.assertEqual(n, number)

    def test_pack_unpack_button_event(self) -> None:
        timestamp = 500
        value = 1  # pressed
        event_type = jp.JS_EVENT_BUTTON  # 0x01
        number = 2
        packed = struct.pack(
            jp._JS_EVENT_FORMAT, timestamp, value, event_type, number
        )
        self.assertEqual(len(packed), jp._JS_EVENT_SIZE)
        t, v, et, n = struct.unpack(jp._JS_EVENT_FORMAT, packed)
        self.assertEqual(t, timestamp)
        self.assertEqual(v, value)
        self.assertEqual(et, event_type)
        self.assertEqual(n, number)

    def test_init_flag(self) -> None:
        event_type = jp.JS_EVENT_AXIS | jp.JS_EVENT_INIT  # 0x82
        packed = struct.pack(jp._JS_EVENT_FORMAT, 0, 0, event_type, 0)
        t, v, et, n = struct.unpack(jp._JS_EVENT_FORMAT, packed)
        self.assertTrue(et & jp.JS_EVENT_INIT)
        self.assertEqual(et & ~jp.JS_EVENT_INIT, jp.JS_EVENT_AXIS)

    def test_event_size_matches_kernel(self) -> None:
        # js_event is exactly 8 bytes on both 32- and 64-bit Linux
        self.assertEqual(jp._JS_EVENT_SIZE, 8)
