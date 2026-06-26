#!/usr/bin/env python3
"""Tkinter GUI for real-time joystick visualization.

Uses ``joystick_parser`` for all device I/O and mapping.  The GUI polls the
parser at ~60 fps via ``root.after()`` — zero cross-thread widget access.
"""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

# ---------------------------------------------------------------------------
# Resolve the standalone parser module regardless of install layout.
# When running from source (PYTHONPATH=src), the `joystick_parser` module
# is importable directly.  When installed, it lives alongside this package.
# ---------------------------------------------------------------------------
try:
    import joystick_parser as _jp
except ImportError:
    # Fall back to a same-directory import when the module is vendored.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import joystick_parser as _jp  # type: ignore[no-redef]

from joystick_parser import (
    JoyMappingConfig,
    JoystickEvent,
    JoystickParser,
    JoystickSnapshot,
    discover_configs,
    get_mapping,
    load_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _axis_percent(value: int, min_val: int, max_val: int) -> float:
    """Map a raw axis value to 0.0–100.0 for a progress bar."""
    span = max_val - min_val
    if span == 0:
        return 0.0
    return max(0.0, min(100.0, (value - min_val) / span * 100.0))


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------


class JoystickWatchApp:
    """Tkinter application for real-time joystick visualization."""

    def __init__(self, root: tk.Tk, device_path: str | None = None) -> None:
        self.root = root
        self.root.title("Joystick Watch")
        self.root.minsize(900, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Parser state
        self._parser: JoystickParser | None = None
        self._config: JoyMappingConfig | None = None
        self._device_path = device_path

        # Poll loop
        self._poll_after_id: str | None = None
        self._poll_interval_ms = 16  # ~60 fps

        # Mapping resolution — maps combobox display label → (identifier, source)
        # source is "builtin" or a file path
        self._mapping_options: list[tuple[str, str, str]] = []  # (label, id, source)

        # Per-axis widgets: logical_name → {"var": IntVar, "bar": Progressbar, "label": Label}
        self._axis_widgets: dict[str, dict] = {}
        # Per-button widgets: logical_name → {"var": BooleanVar, "frame": Frame, "label": Label}
        self._button_widgets: dict[str, dict] = {}

        # UI containers (populated by _build_*)
        self._toolbar: ttk.Frame | None = None
        self._axis_container: ttk.Frame | None = None
        self._button_container: ttk.Frame | None = None
        self._log_widget: tk.Text | None = None

        self._build_ui()
        self._refresh_devices()
        self._refresh_mappings()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)  # toolbar
        self.root.rowconfigure(1, weight=1)  # main content
        self.root.rowconfigure(2, weight=0)  # log

        self._build_toolbar()
        self._build_main_content()
        self._build_event_log()

    # -- toolbar -------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(12, 8, 12, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        self._toolbar = toolbar

        # Device label + combobox
        ttk.Label(toolbar, text="Device:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            toolbar, textvariable=self._device_var, state="readonly", width=22
        )
        self._device_combo.grid(row=0, column=1, sticky="w", padx=(0, 12))

        # Mapping label + combobox
        ttk.Label(toolbar, text="Mapping:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._mapping_var = tk.StringVar()
        self._mapping_combo = ttk.Combobox(
            toolbar, textvariable=self._mapping_var, state="readonly", width=22
        )
        self._mapping_combo.grid(row=0, column=3, sticky="w", padx=(0, 12))
        self._mapping_combo.bind("<<ComboboxSelected>>", self._on_select_mapping)

        # Buttons
        self._start_btn = ttk.Button(toolbar, text="Start", command=self._start_watching)
        self._start_btn.grid(row=0, column=4, padx=(0, 6))

        self._stop_btn = ttk.Button(toolbar, text="Stop", command=self._stop_watching, state="disabled")
        self._stop_btn.grid(row=0, column=5, padx=(0, 12))

        # Refresh buttons
        ttk.Button(toolbar, text="↻ Devices", command=self._refresh_devices).grid(
            row=0, column=6, padx=(0, 4)
        )
        ttk.Button(toolbar, text="↻ Mappings", command=self._refresh_mappings).grid(
            row=0, column=7
        )

        # Status
        self._status_var = tk.StringVar(value="Ready.  Select a device and mapping, then Start.")
        ttk.Label(toolbar, textvariable=self._status_var).grid(
            row=1, column=0, columnspan=8, sticky="w", pady=(6, 0)
        )

    # -- main content --------------------------------------------------

    def _build_main_content(self) -> None:
        main = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=3)  # axes
        main.columnconfigure(1, weight=2)  # buttons
        main.rowconfigure(0, weight=1)

        # ---- axes panel ----------------------------------------------
        axis_panel_frame = ttk.LabelFrame(main, text="Axes", padding=8)
        axis_panel_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        axis_panel_frame.rowconfigure(0, weight=1)
        axis_panel_frame.columnconfigure(0, weight=1)

        # Scrollable canvas for axes
        axis_canvas = tk.Canvas(axis_panel_frame, highlightthickness=0)
        axis_scrollbar = ttk.Scrollbar(axis_panel_frame, orient="vertical", command=axis_canvas.yview)
        self._axis_container = ttk.Frame(axis_canvas)
        self._axis_container.columnconfigure(0, weight=1)

        self._axis_container.bind(
            "<Configure>",
            lambda e: axis_canvas.configure(scrollregion=axis_canvas.bbox("all")),
        )
        axis_canvas.create_window((0, 0), window=self._axis_container, anchor="nw")
        axis_canvas.configure(yscrollcommand=axis_scrollbar.set)

        axis_canvas.grid(row=0, column=0, sticky="nsew")
        axis_scrollbar.grid(row=0, column=1, sticky="ns")
        axis_panel_frame.rowconfigure(0, weight=1)
        axis_panel_frame.columnconfigure(0, weight=1)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            axis_canvas.yview_scroll(-1 * int(event.delta / 120), "units")

        axis_canvas.bind("<Enter>", lambda e: axis_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        axis_canvas.bind("<Leave>", lambda e: axis_canvas.unbind_all("<MouseWheel>"))

        # ---- buttons panel -------------------------------------------
        btn_panel_frame = ttk.LabelFrame(main, text="Buttons", padding=8)
        btn_panel_frame.grid(row=0, column=1, sticky="nsew")
        btn_panel_frame.rowconfigure(0, weight=1)
        btn_panel_frame.columnconfigure(0, weight=1)

        btn_canvas = tk.Canvas(btn_panel_frame, highlightthickness=0)
        btn_scrollbar = ttk.Scrollbar(btn_panel_frame, orient="vertical", command=btn_canvas.yview)
        self._button_container = ttk.Frame(btn_canvas)
        self._button_container.columnconfigure(0, weight=1)

        self._button_container.bind(
            "<Configure>",
            lambda e: btn_canvas.configure(scrollregion=btn_canvas.bbox("all")),
        )
        btn_canvas.create_window((0, 0), window=self._button_container, anchor="nw")
        btn_canvas.configure(yscrollcommand=btn_scrollbar.set)

        btn_canvas.grid(row=0, column=0, sticky="nsew")
        btn_scrollbar.grid(row=0, column=1, sticky="ns")
        btn_panel_frame.rowconfigure(0, weight=1)
        btn_panel_frame.columnconfigure(0, weight=1)

        def _on_mousewheel_btns(event):
            btn_canvas.yview_scroll(-1 * int(event.delta / 120), "units")

        btn_canvas.bind("<Enter>", lambda e: btn_canvas.bind_all("<MouseWheel>", _on_mousewheel_btns))
        btn_canvas.bind("<Leave>", lambda e: btn_canvas.unbind_all("<MouseWheel>"))

    # -- event log -----------------------------------------------------

    def _build_event_log(self) -> None:
        log_frame = ttk.LabelFrame(self.root, text="Event Log", padding=(12, 8, 12, 12))
        log_frame.grid(row=2, column=0, sticky="ew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._log_widget = tk.Text(
            log_frame,
            height=8,
            wrap="none",
            state="disabled",
            font=("TkFixedFont", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
        )
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_widget.yview)
        self._log_widget.configure(yscrollcommand=log_scrollbar.set)

        self._log_widget.grid(row=0, column=0, sticky="nsew")
        log_scrollbar.grid(row=0, column=1, sticky="ns")

        # Tags for colour
        self._log_widget.tag_configure("axis", foreground="#569cd6")
        self._log_widget.tag_configure("button", foreground="#dcdcaa")
        self._log_widget.tag_configure("init", foreground="#6a9955")

        # Hide init events by default
        self._show_init = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            log_frame,
            text="Show init events",
            variable=self._show_init,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self._log_lines = 0
        self._max_log_lines = 5000

    # ==================================================================
    # Panels build-out
    # ==================================================================

    def _rebuild_panels(self) -> None:
        """Destroy and recreate axis / button panels from the current config."""
        if self._config is None:
            return
        # Clear existing
        for w in self._axis_widgets.values():
            w["frame"].destroy()
        self._axis_widgets.clear()
        for w in self._button_widgets.values():
            w["frame"].destroy()
        self._button_widgets.clear()

        self._build_axis_rows()
        self._build_button_grid()

    def _build_axis_rows(self) -> None:
        if self._config is None or self._axis_container is None:
            return
        for number, am in sorted(self._config.axes.items()):
            frame = ttk.Frame(self._axis_container)
            frame.grid(row=len(self._axis_widgets), column=0, sticky="ew", pady=2)
            frame.columnconfigure(1, weight=1)

            # Label (e.g. "Left Stick X")
            ttk.Label(frame, text=am.label, width=18, anchor="w").grid(
                row=0, column=0, sticky="w", padx=(0, 8)
            )

            # Progress bar
            bar_var = tk.IntVar(value=0)
            bar = ttk.Progressbar(
                frame, variable=bar_var, mode="determinate", maximum=100
            )
            bar.grid(row=0, column=1, sticky="ew", padx=(0, 8))

            # Numeric value label
            val_label = ttk.Label(frame, text="0", width=8, anchor="e")
            val_label.grid(row=0, column=2, sticky="e")

            self._axis_widgets[am.logical] = {
                "frame": frame,
                "var": bar_var,
                "bar": bar,
                "label": val_label,
                "mapping": am,
            }

        # Placeholder when there are no axes
        if not self._config.axes:
            ttk.Label(self._axis_container, text="(no axes in mapping)").grid(
                row=0, column=0, sticky="w"
            )

    def _build_button_grid(self) -> None:
        if self._config is None or self._button_container is None:
            return
        sorted_btns = sorted(self._config.buttons.items())
        cols = 2
        for idx, (number, bm) in enumerate(sorted_btns):
            row = idx // cols
            col = idx % cols

            frame = ttk.Frame(self._button_container, relief="solid", borderwidth=1)
            frame.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
            frame.columnconfigure(0, weight=1)

            indicator = tk.Label(
                frame,
                text=" ● ",
                font=("TkDefaultFont", 10, "bold"),
                fg="#555555",  # off state
                bg=self.root.cget("bg"),
            )
            indicator.grid(row=0, column=0, padx=(8, 6), pady=6)

            label = ttk.Label(frame, text=bm.label, width=12, anchor="w")
            label.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=6)

            self._button_widgets[bm.logical] = {
                "frame": frame,
                "indicator": indicator,
                "label": label,
                "mapping": bm,
                "var": tk.BooleanVar(value=False),
            }

        # Placeholder when there are no buttons
        if not self._config.buttons:
            ttk.Label(self._button_container, text="(no buttons in mapping)").grid(
                row=0, column=0, sticky="w"
            )

    # ==================================================================
    # Toolbar actions
    # ==================================================================

    def _refresh_devices(self) -> None:
        devices = JoystickParser.list_devices()
        self._device_combo["values"] = devices
        if devices:
            if self._device_path and self._device_path in devices:
                self._device_var.set(self._device_path)
            else:
                self._device_var.set(devices[0])
            self._start_btn.configure(state="normal")
        else:
            self._device_var.set("")
            self._start_btn.configure(state="disabled")
            self._status_var.set("No joystick devices found in /dev/input/js*")

    def _refresh_mappings(self) -> None:
        self._mapping_options = []

        # Builtins first
        self._mapping_options.append(("Xbox (built-in)", "xbox", "builtin"))
        self._mapping_options.append(("PS5 (built-in)", "ps5", "builtin"))

        # Filesystem YAML configs
        for display_name, path in discover_configs():
            # Avoid duplicates with builtins
            ident = os.path.splitext(os.path.basename(path))[0]
            if ident in ("xbox", "ps5"):
                display_name = f"{display_name} (YAML)"
            self._mapping_options.append((display_name, path, "file"))

        labels = [label for label, _, _ in self._mapping_options]
        self._mapping_combo["values"] = labels
        if labels:
            self._mapping_combo.current(0)  # default to first

    def _on_select_mapping(self, event: tk.Event | None = None) -> None:
        idx = self._mapping_combo.current()
        if idx < 0 or idx >= len(self._mapping_options):
            return
        _label, identifier, _source = self._mapping_options[idx]

        try:
            self._config = get_mapping(identifier)
        except Exception as exc:
            messagebox.showerror("Mapping Error", f"Failed to load mapping: {exc}")
            return

        self._rebuild_panels()
        self._status_var.set(f"Mapping loaded: {self._config.name}")

    # ==================================================================
    # Start / Stop
    # ==================================================================

    def _start_watching(self) -> None:
        device = self._device_var.get()
        if not device or not os.path.exists(device):
            messagebox.showerror("Device Error", f"Device not found: {device}")
            return

        # Ensure a mapping is selected
        if self._config is None:
            self._on_select_mapping()

        if self._config is None:
            messagebox.showerror("Mapping Error", "No mapping selected.")
            return

        try:
            self._parser = JoystickParser(device, mapping=self._config)
            self._parser.start()
        except (OSError, PermissionError) as exc:
            messagebox.showerror("Device Error", str(exc))
            return

        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._device_combo.configure(state="disabled")
        self._mapping_combo.configure(state="disabled")
        self._status_var.set(f"Watching {device}  |  {self._config.name}")
        self._start_poll_loop()

    def _stop_watching(self) -> None:
        self._cancel_poll_loop()

        if self._parser is not None:
            self._parser.stop()
            self._parser = None

        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._device_combo.configure(state="readonly")
        self._mapping_combo.configure(state="readonly")
        self._status_var.set("Stopped.")

        # Reset visual indicators
        for w in self._axis_widgets.values():
            w["var"].set(0)
            w["label"].configure(text="0")
        for w in self._button_widgets.values():
            w["var"].set(False)
            w["indicator"].configure(fg="#555555")

    # ==================================================================
    # Poll loop
    # ==================================================================

    def _start_poll_loop(self) -> None:
        self._poll_events()

    def _cancel_poll_loop(self) -> None:
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None

    def _poll_events(self) -> None:
        parser = self._parser
        if parser is None or not parser.running:
            self._cancel_poll_loop()
            self._stop_watching()
            return

        try:
            events = parser.drain_events()
            for ev in events:
                self._append_event_log(ev)

            snap = parser.get_snapshot()
            self._update_from_snapshot(snap)
        except Exception:
            pass  # Don't crash the poll loop on transient errors.

        self._poll_after_id = self.root.after(self._poll_interval_ms, self._poll_events)

    # ==================================================================
    # UI updates
    # ==================================================================

    def _update_from_snapshot(self, snap: JoystickSnapshot) -> None:
        # Axes
        for logical, value in snap.axes.items():
            w = self._axis_widgets.get(logical)
            if w is None:
                continue
            am = w["mapping"]
            pct = _axis_percent(value, am.min_val, am.max_val)
            w["var"].set(int(pct))
            w["label"].configure(text=str(value))

        # Buttons
        for logical, pressed in snap.buttons.items():
            w = self._button_widgets.get(logical)
            if w is None:
                continue
            w["var"].set(pressed)
            w["indicator"].configure(
                fg="#4ec94e" if pressed else "#555555"  # green when pressed
            )

    def _append_event_log(self, ev: JoystickEvent) -> None:
        if self._log_widget is None:
            return
        if ev.is_init and not self._show_init.get():
            return

        tag = "axis" if ev.event_type == "axis" else "button"
        if ev.is_init:
            tag = "init"

        line = (
            f"[{ev.timestamp_ms:8d}] {ev.event_type:6s} "
            f"#{ev.number:2d}  {ev.label:<16s}  {ev.value:>6d}"
        )

        self._log_widget.configure(state="normal")
        self._log_widget.insert("end", line + "\n", tag)
        self._log_widget.see("end")
        self._log_widget.configure(state="disabled")

        self._log_lines += 1
        if self._log_lines > self._max_log_lines:
            # Trim old lines
            self._log_widget.configure(state="normal")
            self._log_widget.delete("1.0", "200.0")
            self._log_widget.configure(state="disabled")
            self._log_lines = 0  # approximate reset

    # ==================================================================
    # Shutdown
    # ==================================================================

    def _on_close(self) -> None:
        self._stop_watching()
        self.root.destroy()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Real-time joystick visualization GUI.",
    )
    parser.add_argument(
        "--device",
        help="Joystick device path, e.g. /dev/input/js0.  Auto-detected when omitted.",
    )
    parser.add_argument(
        "--config",
        help="Mapping to use: 'xbox', 'ps5', or a path to a YAML file.  Default: xbox.",
        default="xbox",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print detected /dev/input/js* devices and exit.",
    )
    parser.add_argument(
        "--list-mappings",
        action="store_true",
        help="Print available built-in and filesystem mappings and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # -- Info-only modes --
    if args.list_devices:
        devices = JoystickParser.list_devices()
        if devices:
            print("\n".join(devices))
        else:
            print("No joystick devices found under /dev/input/js*")
        return 0

    if args.list_mappings:
        print("Built-in mappings:")
        for name in ("xbox", "ps5"):
            cfg = get_mapping(name)
            print(f"  {name:8s}  {cfg.name}")
        print()
        print("Filesystem mappings:")
        discovered = discover_configs()
        if discovered:
            for display, path in discovered:
                print(f"  {display:<30s}  {path}")
        else:
            print("  (none found — place .yaml files in ~/.config/joystick_watch/mappings/)")
        return 0

    # -- GUI mode --
    if not os.environ.get("DISPLAY"):
        print("No DISPLAY environment variable found. Use --list-devices or --list-mappings, or run from a desktop session.")
        return 1

    root = tk.Tk()
    ttk.Style(root).theme_use("clam")
    JoystickWatchApp(root, device_path=args.device)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
