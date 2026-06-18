#!/usr/bin/env python3
"""Watch and print Linux joystick state from /dev/input/js*."""

from __future__ import annotations

import argparse
from glob import glob
import os
import struct
import sys


JS_EVENT_FORMAT = "IhBB"
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FORMAT)
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80


DEFAULT_AXIS_NAMES = {
    0: "left_x",
    1: "left_y",
    2: "l2",
    3: "right_x",
    4: "right_y",
    5: "r2",
    6: "dpad_x",
    7: "dpad_y",
}

DEFAULT_BUTTON_NAMES = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "L1",
    5: "R1",
    6: "Select",
    7: "Start",
    8: "Mode",
    9: "L3",
    10: "R3",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Watch Linux joystick events and maintain a live state table.",
    )
    parser.add_argument(
        "device",
        nargs="?",
        help="Joystick device path, for example /dev/input/js0. Defaults to the first detected device.",
    )
    parser.add_argument(
        "--show-init",
        action="store_true",
        help="Show synthetic initialization events as they arrive.",
    )
    return parser


def select_device(device: str | None) -> str:
    if device:
        return device

    devices = sorted(glob("/dev/input/js*"))
    if not devices:
        raise FileNotFoundError("No joystick devices found under /dev/input/js*")
    return devices[0]


def axis_name(number: int) -> str:
    return DEFAULT_AXIS_NAMES.get(number, f"axis_{number}")


def button_name(number: int) -> str:
    return DEFAULT_BUTTON_NAMES.get(number, f"button_{number}")


def print_snapshot(axes: dict[int, int], buttons: dict[int, int]) -> None:
    axis_parts = [f"{axis_name(index)}={value:6d}" for index, value in sorted(axes.items())]
    button_parts = [f"{button_name(index)}={'1' if value else '0'}" for index, value in sorted(buttons.items())]
    axis_text = " ".join(axis_parts) if axis_parts else "no axes yet"
    button_text = " ".join(button_parts) if button_parts else "no buttons yet"
    print(f"state axes[{axis_text}] buttons[{button_text}]", flush=True)


def watch_device(device_path: str, show_init: bool) -> int:
    axes: dict[int, int] = {}
    buttons: dict[int, int] = {}

    print(f"Watching joystick events from {device_path}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    with open(device_path, "rb", buffering=0) as handle:
        while True:
            payload = handle.read(JS_EVENT_SIZE)
            if len(payload) != JS_EVENT_SIZE:
                raise RuntimeError("Short read from joystick device")

            timestamp_ms, value, event_type, number = struct.unpack(JS_EVENT_FORMAT, payload)
            is_init = bool(event_type & JS_EVENT_INIT)
            base_type = event_type & ~JS_EVENT_INIT

            if is_init and not show_init:
                if base_type == JS_EVENT_AXIS:
                    axes[number] = value
                elif base_type == JS_EVENT_BUTTON:
                    buttons[number] = value
                continue

            if base_type == JS_EVENT_AXIS:
                axes[number] = value
                print(f"axis   t={timestamp_ms:8d} {axis_name(number):<10} value={value:6d}", flush=True)
                print_snapshot(axes, buttons)
                continue

            if base_type == JS_EVENT_BUTTON:
                buttons[number] = value
                print(f"button t={timestamp_ms:8d} {button_name(number):<10} value={value}", flush=True)
                print_snapshot(axes, buttons)
                continue

            print(
                f"other  t={timestamp_ms:8d} type=0x{event_type:02x} number={number} value={value}",
                flush=True,
            )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        device_path = select_device(args.device)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not os.path.exists(device_path):
        print(f"error: device does not exist: {device_path}", file=sys.stderr)
        return 1

    try:
        return watch_device(device_path, show_init=args.show_init)
    except PermissionError:
        print(f"error: cannot read {device_path}; try sudo or adjust input-device permissions", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped watcher.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())