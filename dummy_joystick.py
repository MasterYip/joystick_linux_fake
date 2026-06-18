#!/usr/bin/env python3
"""Compatibility launcher for the packaged joystick_linux_fake CLI."""

from __future__ import annotations

from pathlib import Path
import sys


def _bootstrap_src_path() -> None:
    repo_root = Path(__file__).resolve().parent
    src_path = repo_root / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))


def main() -> int:
    _bootstrap_src_path()
    from joystick_linux_fake.cli import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
