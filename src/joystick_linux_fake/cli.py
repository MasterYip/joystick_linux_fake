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
    parser.add_argument(
        "--scaling",
        type=float,
        default=None,
        help="Tkinter UI scaling factor for HiDPI displays (e.g. 2.0 for 200%%). Auto-detected when omitted.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Joystick mapping: 'xbox', 'ps5', or path to a YAML file.  Default: xbox (built-in).",
    )
    return parser


def _resolve_config(identifier: str | None):
    """Resolve a --config CLI value to a JoyMappingConfig, or None for default."""
    if identifier is None:
        return None
    try:
        from joystick_parser import get_mapping
        return get_mapping(identifier)
    except ImportError:
        print("Warning: joystick_parser not available — using built-in Xbox mapping.", flush=True)
        return None


def _make_controller(args: argparse.Namespace):
    return JoystickController(
        device_name=args.device_name,
        update_rate_hz=args.update_rate,
        config=_resolve_config(args.config),
    )


def run_check() -> int:
    report = get_environment_report()
    print(format_environment_report(report))
    return 0 if all(item.ok for item in report) else 1


def run_idle(args: argparse.Namespace) -> int:
    controller = _make_controller(args)
    controller.start()
    cfg_name = controller.config.name if controller.config else "xbox"
    print(f"Virtual joystick ready: {args.device_name}")
    print(f"Mode: idle  |  Mapping: {cfg_name}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0
    finally:
        controller.close()


def run_simulate(args: argparse.Namespace) -> int:
    controller = _make_controller(args)
    session = SimulationSession(controller)
    controller.start()
    session.start(args.pattern)
    cfg_name = controller.config.name if controller.config else "xbox"
    print(f"Virtual joystick ready: {args.device_name}")
    print(f"Mode: simulate ({args.pattern})  |  Mapping: {cfg_name}")
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

    return launch_gui(
        device_name=args.device_name,
        update_rate_hz=args.update_rate,
        scaling=args.scaling,
        config=_resolve_config(args.config),
    )


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
