#!/usr/bin/env python3
"""Tkinter GUI for real-time joystick visualization.

Uses ``joystick_parser`` for all device I/O and mapping.  The GUI polls the
parser at ~60 fps via ``root.after()`` — zero cross-thread widget access.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TypeVar

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
    AxisMapping,
    BUILTIN_MAPPINGS,
    ButtonMapping,
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


_MappingT = TypeVar("_MappingT")


def reorder_mapping_slots(
    mappings: dict[int, _MappingT], source_index: int, target_index: int
) -> dict[int, _MappingT]:
    """Move one assignment in physical-slot order, preserving slot numbers.

    Calibration changes which logical control belongs to each raw physical
    number.  The physical numbers themselves are device facts and therefore
    remain fixed while their assignments are reordered.
    """
    slots = sorted(mappings)
    if not (0 <= source_index < len(slots) and 0 <= target_index < len(slots)):
        return dict(mappings)
    assignments = [mappings[number] for number in slots]
    assignment = assignments.pop(source_index)
    assignments.insert(target_index, assignment)
    return dict(zip(slots, assignments))


def mapping_to_dict(config: JoyMappingConfig) -> dict:
    """Return a YAML-ready representation of a joystick mapping."""
    return {
        "name": config.name,
        "version": config.version,
        "axes": {
            number: {
                "logical": mapping.logical,
                "label": mapping.label,
                "min": mapping.min_val,
                "max": mapping.max_val,
            }
            for number, mapping in sorted(config.axes.items())
        },
        "buttons": {
            number: {"logical": mapping.logical, "label": mapping.label}
            for number, mapping in sorted(config.buttons.items())
        },
    }


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

        # Calibration keeps a separate draft until Apply is pressed.
        self._calibration_draft: JoyMappingConfig | None = None
        self._calibration_trees: dict[str, ttk.Treeview] = {}
        self._calibration_drag: tuple[str, str] | None = None

        # UI containers (populated by _build_*)
        self._toolbar: ttk.Frame | None = None
        self._axis_container: ttk.Frame | None = None
        self._button_container: ttk.Frame | None = None
        self._main_content: ttk.Frame | None = None
        self._calibration_panel: ttk.LabelFrame | None = None
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

        self._calibration_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar,
            text="Calibration mode",
            variable=self._calibration_mode,
            command=self._toggle_calibration,
        ).grid(row=0, column=8, padx=(12, 0))

        # Status
        self._status_var = tk.StringVar(value="Ready.  Select a device and mapping, then Start.")
        ttk.Label(toolbar, textvariable=self._status_var).grid(
            row=1, column=0, columnspan=9, sticky="w", pady=(6, 0)
        )

    # -- main content --------------------------------------------------

    def _build_main_content(self) -> None:
        main = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        main.grid(row=1, column=0, sticky="nsew")
        self._main_content = main
        main.columnconfigure(0, weight=3)  # axes
        main.columnconfigure(1, weight=2)  # buttons
        main.columnconfigure(2, weight=0)  # calibration (hidden initially)
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

        self._build_calibration_panel(main)

    def _build_calibration_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Calibration", padding=8)
        panel.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        panel.rowconfigure(4, weight=1)
        self._calibration_panel = panel

        ttk.Label(
            panel,
            text="Move a control, then drag its assignment to the\n"
            "highlighted raw slot. Physical # stays fixed.",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        ttk.Label(panel, text="Axes", anchor="w").grid(row=1, column=0, sticky="ew")
        self._calibration_trees["axis"] = self._make_calibration_tree(panel, 2, "axis")
        ttk.Label(panel, text="Buttons", anchor="w").grid(
            row=3, column=0, sticky="ew", pady=(8, 0)
        )
        self._calibration_trees["button"] = self._make_calibration_tree(panel, 4, "button")

        name_frame = ttk.Frame(panel)
        name_frame.grid(row=5, column=0, sticky="ew", pady=(8, 4))
        name_frame.columnconfigure(1, weight=1)
        ttk.Label(name_frame, text="Name:").grid(row=0, column=0, padx=(0, 4))
        self._calibration_name = tk.StringVar()
        ttk.Entry(name_frame, textvariable=self._calibration_name).grid(
            row=0, column=1, sticky="ew"
        )

        actions = ttk.Frame(panel)
        actions.grid(row=6, column=0, sticky="ew")
        ttk.Button(actions, text="Reset", command=self._reset_calibration).pack(
            side="left"
        )
        ttk.Button(actions, text="Apply", command=self._apply_calibration).pack(
            side="left", padx=4
        )
        ttk.Button(actions, text="Save YAML…", command=self._save_calibration).pack(
            side="right"
        )
        panel.grid_remove()

    def _make_calibration_tree(
        self, parent: ttk.Frame, row: int, event_type: str
    ) -> ttk.Treeview:
        tree = ttk.Treeview(
            parent,
            columns=("number", "assignment", "value"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        tree.heading("number", text="Raw #")
        tree.heading("assignment", text="Assignment (drag)")
        tree.heading("value", text="Value")
        tree.column("number", width=48, anchor="center", stretch=False)
        tree.column("assignment", width=150, anchor="w")
        tree.column("value", width=64, anchor="e", stretch=False)
        tree.tag_configure("changed", background="#ffe08a", foreground="#111111")
        tree.grid(row=row, column=0, sticky="nsew")
        tree.bind(
            "<ButtonPress-1>",
            lambda event, kind=event_type: self._calibration_drag_start(event, kind),
        )
        tree.bind(
            "<ButtonRelease-1>",
            lambda event, kind=event_type: self._calibration_drag_end(event, kind),
        )
        return tree

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
            font="TkFixedFont",
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
                font="TkDefaultFont",
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
        self._mapping_options.append(("Xbox wired / legacy", "xbox", "builtin"))
        self._mapping_options.append(("Xbox updated BLE firmware", "xbox_new", "builtin"))
        self._mapping_options.append(("PS5 (built-in)", "ps5", "builtin"))
        self._mapping_options.append(("Beitong KP20 (built-in)", "beitong_kp20", "builtin"))

        # Additional filesystem configs
        for display_name, path in discover_configs():
            ident = os.path.splitext(os.path.basename(path))[0]
            if ident in BUILTIN_MAPPINGS:
                continue
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
            # Built-ins are shared module-level objects.  Keep the GUI copy
            # private so calibration can never mutate a global preset.
            self._config = copy.deepcopy(get_mapping(identifier))
        except Exception as exc:
            messagebox.showerror("Mapping Error", f"Failed to load mapping: {exc}")
            return

        self._rebuild_panels()
        if self._calibration_mode.get():
            self._reset_calibration()
        self._status_var.set(f"Mapping loaded: {self._config.name}")

    # -- calibration ---------------------------------------------------

    def _toggle_calibration(self) -> None:
        panel = self._calibration_panel
        main = self._main_content
        if panel is None or main is None:
            return
        if self._calibration_mode.get():
            if self._config is None:
                self._on_select_mapping()
            if self._config is None:
                self._calibration_mode.set(False)
                return
            self.root.minsize(1180, 640)
            panel.grid()
            main.columnconfigure(2, weight=3)
            self._reset_calibration()
            self._status_var.set(
                "Calibration: operate one control, then drag its assignment to the highlighted raw slot."
            )
        else:
            panel.grid_remove()
            self.root.minsize(900, 640)
            main.columnconfigure(2, weight=0)
            self._calibration_drag = None
            self._status_var.set("Calibration closed; unapplied changes were discarded.")

    def _reset_calibration(self) -> None:
        if self._config is None:
            return
        self._calibration_draft = copy.deepcopy(self._config)
        self._calibration_name.set(f"{self._config.name} (calibrated)")
        self._populate_calibration_trees()

    def _populate_calibration_trees(self) -> None:
        draft = self._calibration_draft
        if draft is None:
            return
        for kind, mappings in (("axis", draft.axes), ("button", draft.buttons)):
            tree = self._calibration_trees[kind]
            tree.delete(*tree.get_children())
            for number, mapping in sorted(mappings.items()):
                tree.insert(
                    "",
                    "end",
                    iid=f"{kind}:{number}",
                    values=(number, f"{mapping.label}  [{mapping.logical}]", "—"),
                )

    def _calibration_drag_start(self, event: tk.Event, kind: str) -> None:
        tree = self._calibration_trees[kind]
        item = tree.identify_row(event.y)
        self._calibration_drag = (kind, item) if item else None

    def _calibration_drag_end(self, event: tk.Event, kind: str) -> None:
        drag = self._calibration_drag
        self._calibration_drag = None
        if drag is None or drag[0] != kind or self._calibration_draft is None:
            return
        tree = self._calibration_trees[kind]
        target = tree.identify_row(event.y)
        children = list(tree.get_children())
        if not target or drag[1] not in children or target not in children:
            return
        source_index = children.index(drag[1])
        target_index = children.index(target)
        if source_index == target_index:
            return
        if kind == "axis":
            self._calibration_draft.axes = reorder_mapping_slots(
                self._calibration_draft.axes, source_index, target_index
            )
        else:
            self._calibration_draft.buttons = reorder_mapping_slots(
                self._calibration_draft.buttons, source_index, target_index
            )
        self._populate_calibration_trees()

    def _apply_calibration(self) -> None:
        if self._calibration_draft is None:
            return
        name = self._calibration_name.get().strip()
        if name:
            self._calibration_draft.name = name
        self._config = copy.deepcopy(self._calibration_draft)
        if self._parser is not None:
            self._parser.mapping = self._config
        self._rebuild_panels()
        self._calibration_draft = copy.deepcopy(self._config)
        self._populate_calibration_trees()
        self._status_var.set(f"Calibration applied: {self._config.name}")

    def _save_calibration(self) -> None:
        draft = self._calibration_draft
        if draft is None:
            return
        name = self._calibration_name.get().strip()
        if name:
            draft.name = name
        filename = re.sub(r"[^a-z0-9]+", "_", draft.name.lower()).strip("_")
        filename = (filename or "joystick_mapping") + ".yaml"
        initial_dir = Path(
            os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        ) / "joystick_watch" / "mappings"
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save calibrated joystick mapping",
            initialdir=str(initial_dir),
            initialfile=filename,
            defaultextension=".yaml",
            filetypes=(("YAML mapping", "*.yaml"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            import yaml

            Path(path).write_text(
                yaml.safe_dump(mapping_to_dict(draft), sort_keys=False),
                encoding="utf-8",
            )
        except (ImportError, OSError) as exc:
            messagebox.showerror("Save Mapping", f"Could not save mapping:\n{exc}")
            return
        self._status_var.set(f"Mapping saved: {path}")
        messagebox.showinfo(
            "Mapping Saved",
            f"Saved calibrated mapping to:\n{path}\n\n"
            "Refresh Mappings to select it in Joystick Watch.",
        )

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
                self._update_calibration_event(ev)

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

    def _update_calibration_event(self, ev: JoystickEvent) -> None:
        """Expose the latest raw event in the calibration assignment list."""
        draft = self._calibration_draft
        if not self._calibration_mode.get() or draft is None:
            return

        mappings = draft.axes if ev.event_type == "axis" else draft.buttons
        if ev.number not in mappings:
            # An incorrect preset may omit a physical control entirely.  Add
            # a visible placeholder so it can still participate in dragging
            # and be preserved in the exported mapping.
            if ev.event_type == "axis":
                mappings[ev.number] = AxisMapping(
                    f"axis_{ev.number}", f"Axis {ev.number}", -32768, 32767
                )
            else:
                mappings[ev.number] = ButtonMapping(
                    f"button_{ev.number}", f"Button {ev.number}"
                )
            self._populate_calibration_trees()

        tree = self._calibration_trees[ev.event_type]
        item = f"{ev.event_type}:{ev.number}"
        if not tree.exists(item):
            return
        for child in tree.get_children():
            tree.item(child, tags=())
        values = list(tree.item(item, "values"))
        values[2] = ev.value
        tree.item(item, values=values, tags=("changed",))
        tree.see(item)

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
        help="Mapping to use: 'xbox', 'xbox_new', 'ps5', 'beitong_kp20', or a config file path. Default: xbox.",
        default="xbox",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print detected /dev/input/js* devices and exit.",
    )
    parser.add_argument(
        "--scaling",
        type=float,
        default=None,
        help="Tkinter UI scaling factor for HiDPI displays (e.g. 2.0 for 200%%). Auto-detected when omitted.",
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
        for name in BUILTIN_MAPPINGS:
            cfg = get_mapping(name)
            print(f"  {name:8s}  {cfg.name}")
        print()
        print("Filesystem mappings:")
        discovered = [
            (display, path)
            for display, path in discover_configs()
            if os.path.splitext(os.path.basename(path))[0] not in BUILTIN_MAPPINGS
        ]
        if discovered:
            for display, path in discovered:
                print(f"  {display:<30s}  {path}")
        else:
            print("  (none found - place .yaml files in ~/.config/joystick_watch/mappings/)")
        return 0

    # -- GUI mode --
    if not os.environ.get("DISPLAY"):
        print("No DISPLAY environment variable found. Use --list-devices or --list-mappings, or run from a desktop session.")
        return 1

    from .tk_scaling import apply_scaling

    root = tk.Tk()
    apply_scaling(root, args.scaling)
    ttk.Style(root).theme_use("clam")
    JoystickWatchApp(root, device_path=args.device)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
