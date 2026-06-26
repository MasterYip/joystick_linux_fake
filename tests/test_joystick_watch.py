"""Tests for the joystick_watch GUI app (CLI layer only)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from joystick_watch.app import build_parser


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
