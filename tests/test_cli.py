from __future__ import annotations

import unittest

from joystick_linux_fake.cli import build_parser


class CliParserTests(unittest.TestCase):
    def test_defaults(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.mode, "gui")
        self.assertEqual(args.pattern, "circle")
        self.assertEqual(args.update_rate, 125)

    def test_updated_xbox_config_flag(self) -> None:
        args = build_parser().parse_args(["--config", "xbox_new"])
        self.assertEqual(args.config, "xbox_new")


if __name__ == "__main__":
    unittest.main()
