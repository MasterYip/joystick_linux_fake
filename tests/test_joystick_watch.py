"""Tests for the joystick_watch GUI app (CLI layer only)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from joystick_parser import AxisMapping, ButtonMapping, JoyMappingConfig
from joystick_watch.app import build_parser, mapping_to_dict, reorder_mapping_slots


class CliParserTests(unittest.TestCase):
    def test_defaults(self) -> None:
        args = build_parser().parse_args([])
        self.assertIsNone(args.device)
        self.assertEqual(args.config, "xbox")
        self.assertFalse(args.list_devices)
        self.assertFalse(args.list_mappings)

    def test_device_flag(self) -> None:
        args = build_parser().parse_args(["--device", "/dev/input/js2"])
        self.assertEqual(args.device, "/dev/input/js2")

    def test_config_flag(self) -> None:
        args = build_parser().parse_args(["--config", "ps5"])
        self.assertEqual(args.config, "ps5")

    def test_updated_xbox_config_flag(self) -> None:
        args = build_parser().parse_args(["--config", "xbox_new"])
        self.assertEqual(args.config, "xbox_new")

    def test_list_devices_flag(self) -> None:
        args = build_parser().parse_args(["--list-devices"])
        self.assertTrue(args.list_devices)

    def test_list_mappings_flag(self) -> None:
        args = build_parser().parse_args(["--list-mappings"])
        self.assertTrue(args.list_mappings)

    def test_combined_flags(self) -> None:
        args = build_parser().parse_args(
            ["--device", "/dev/input/js0", "--config", "xbox"]
        )
        self.assertEqual(args.device, "/dev/input/js0")
        self.assertEqual(args.config, "xbox")


class CalibrationMappingTests(unittest.TestCase):
    def test_reorder_preserves_physical_slots(self) -> None:
        mappings = {
            2: ButtonMapping("south", "A"),
            5: ButtonMapping("east", "B"),
            9: ButtonMapping("west", "X"),
        }

        reordered = reorder_mapping_slots(mappings, 0, 2)

        self.assertEqual(list(reordered), [2, 5, 9])
        self.assertEqual(
            [mapping.logical for mapping in reordered.values()],
            ["east", "west", "south"],
        )

    def test_reorder_invalid_index_leaves_mapping_unchanged(self) -> None:
        mappings = {0: ButtonMapping("south", "A")}
        self.assertEqual(reorder_mapping_slots(mappings, -1, 0), mappings)
        self.assertEqual(reorder_mapping_slots(mappings, 0, 4), mappings)

    def test_mapping_to_dict_is_yaml_ready_and_ordered(self) -> None:
        config = JoyMappingConfig(
            name="Calibrated Pad",
            version=1,
            axes={3: AxisMapping("right_x", "Right X", -10, 10)},
            buttons={2: ButtonMapping("west", "X"), 0: ButtonMapping("south", "A")},
        )

        raw = mapping_to_dict(config)

        self.assertEqual(raw["name"], "Calibrated Pad")
        self.assertEqual(list(raw["buttons"]), [0, 2])
        self.assertEqual(raw["axes"][3]["min"], -10)
