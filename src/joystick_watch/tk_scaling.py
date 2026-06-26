"""Shared tkinter scaling helper for HiDPI displays.

Tkinter does not automatically scale on high-DPI monitors.  This module
detects the system DPI (from X resources) and applies an appropriate
scaling factor — both widget geometry (via ``tk scaling``) and fonts
(via named Tk font resizing).
"""

from __future__ import annotations

import subprocess
import tkinter.font as _tkfont

# Named fonts that should be resized for HiDPI.
_SCALED_FONT_NAMES = (
    "TkDefaultFont",
    "TkFixedFont",
    "TkTextFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkTooltipFont",
    "TkMenuFont",
    "TkSmallCaptionFont",
    "TkIconFont",
)


def detect_scaling_factor() -> float:
    """Auto-detect a sensible tkinter scaling factor from the X server.

    Returns a multiplier (e.g. 1.0 for 96 DPI, 2.0 for 192 DPI).
    The value is always clamped to **[1.0, 4.0]**.
    """
    factor = _read_xft_dpi()
    # Some desktops report 96 even on HiDPI (they do their own scaling),
    # so we only raise the factor when DPI is clearly above 120.
    if factor < 1.25:
        # One more heuristic: try xdpyinfo to get physical screen dimensions.
        factor = max(factor, _read_xdpyinfo_dpi())
    return max(1.0, min(4.0, factor))


def apply_scaling(root, factor: float | None = None) -> float:
    """Apply DPI scaling to *root* — geometry **and** fonts.

    - Widget sizes are scaled via ``root.tk.call('tk', 'scaling', …)``.
    - Named fonts (``TkDefaultFont``, ``TkFixedFont``, etc.) are resized
      by the same factor so text remains readable.

    When *factor* is ``None`` (the default), auto-detection is used.
    Returns the factor that was applied.
    """
    if factor is None:
        factor = detect_scaling_factor()
    root.tk.call("tk", "scaling", factor)
    _scale_fonts(factor)
    return factor


def _scale_fonts(factor: float) -> None:
    """Resize each named Tk font by *factor*, rounding to the nearest int."""
    for name in _SCALED_FONT_NAMES:
        try:
            font = _tkfont.nametofont(name)
            # Some named fonts may not exist on all platforms — skip silently.
        except Exception:
            continue
        try:
            base_size = font.cget("size")
            if base_size <= 0:
                base_size = font.actual("size")
        except Exception:
            base_size = 12  # sensible default
        if base_size <= 0:
            base_size = 12
        new_size = max(1, int(round(base_size * factor)))
        try:
            font.configure(size=new_size)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_xft_dpi() -> float:
    """Return ``Xft.dpi / 96.0`` from ``xrdb -query``, or 1.0 on failure."""
    try:
        out = subprocess.check_output(
            ["xrdb", "-query"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return 1.0
    for line in out.splitlines():
        if line.strip().startswith("Xft.dpi:"):
            parts = line.split(":")
            if len(parts) >= 2:
                try:
                    dpi = float(parts[1].strip())
                    return dpi / 96.0
                except ValueError:
                    pass
    return 1.0


def _read_xdpyinfo_dpi() -> float:
    """Estimate DPI from ``xdpyinfo`` physical screen dimensions.

    Returns ``estimated_dpi / 96.0`` or 1.0 on failure.
    """
    try:
        out = subprocess.check_output(
            ["xdpyinfo"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return 1.0
    # Look for "dimensions: 3840x2160 pixels" and "resolution: 96x96 dots per inch"
    import re

    dims_match = re.search(r"dimensions:\s+(\d+)x(\d+)\s+pixels", out)
    res_match = re.search(r"resolution:\s+(\d+)x(\d+)\s+dots per inch", out)
    # We need the physical screen size from the X server.
    # Without RandR info, xdpyinfo doesn't report mm dimensions reliably.
    # Fall back: if resolution is reported, use it directly.
    if res_match:
        try:
            dpi = float(res_match.group(1))
            return dpi / 96.0
        except ValueError:
            pass
    return 1.0
