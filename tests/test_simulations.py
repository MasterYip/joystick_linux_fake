from __future__ import annotations

import unittest

from joystick_linux_fake.simulations import PATTERNS


class SimulationPatternTests(unittest.TestCase):
    def test_patterns_return_expected_ranges(self) -> None:
        for name, pattern in PATTERNS.items():
            state = pattern(1.25)
            with self.subTest(pattern=name):
                self.assertTrue(-32768 <= state.axes["left_x"] <= 32767)
                self.assertTrue(-32768 <= state.axes["left_y"] <= 32767)
                self.assertTrue(-32768 <= state.axes["right_x"] <= 32767)
                self.assertTrue(-32768 <= state.axes["right_y"] <= 32767)
                self.assertTrue(0 <= state.axes["l2"] <= 255)
                self.assertTrue(0 <= state.axes["r2"] <= 255)
                self.assertIn(state.axes["dpad_x"], (-1, 0, 1))
                self.assertIn(state.axes["dpad_y"], (-1, 0, 1))


if __name__ == "__main__":
    unittest.main()