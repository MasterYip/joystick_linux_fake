"""Command-line entry point for joystick_linux_fake."""

from __future__ import annotations

import argparse
import time

from .controller import JoystickController, SimulationSession
from .device import format_environment_report, get_environment_report
from .simulations import PATTERNS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="joystick-linux-fake",
        description="Create and drive a virtual Linux joystick backed by python-evdev.",
    )
    parser.add_argument(
        "--mode",
        choices=["gui", "idle", "simulate", "check"],
        default="gui",
        help="How to run the virtual joystick session.",
    )
    parser.add_argument(
        "--pattern",
        choices=sorted(PATTERNS),
        default="circle",
        help="Simulation pattern used when --mode simulate is selected.",
    )
    parser.add_argument(
        "--device-name",
        default="Joystick Linux Fake",
        help="Visible name for the virtual joystick device.",
    )
    parser.add_argument(
        "--update-rate",
        type=int,
        default=125,
        help="State refresh rate in Hz for the virtual device.",
    )
    return parser


def run_check() -> int:
    report = get_environment_report()
    print(format_environment_report(report))
    return 0 if all(item.ok for item in report) else 1


def run_idle(args: argparse.Namespace) -> int:
    controller = JoystickController(
        device_name=args.device_name,
        update_rate_hz=args.update_rate,
    )
    controller.start()
    print(f"Virtual joystick ready: {args.device_name}")
    print("Mode: idle")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0
    finally:
        controller.close()


def run_simulate(args: argparse.Namespace) -> int:
    controller = JoystickController(
        device_name=args.device_name,
        update_rate_hz=args.update_rate,
    )
    session = SimulationSession(controller)
    controller.start()
    session.start(args.pattern)
    print(f"Virtual joystick ready: {args.device_name}")
    print(f"Mode: simulate ({args.pattern})")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0
    finally:
        session.stop(reset=True)
        controller.close()


def run_gui(args: argparse.Namespace) -> int:
    from .gui import launch_gui

    return launch_gui(device_name=args.device_name, update_rate_hz=args.update_rate)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "check":
        return run_check()
    if args.mode == "idle":
        return run_idle(args)
    if args.mode == "simulate":
        return run_simulate(args)
    return run_gui(args)
