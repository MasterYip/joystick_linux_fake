"""Tkinter GUI for the virtual joystick — layout built dynamically from the mapping config."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from .controller import JoystickController, SimulationSession
from .device import DeviceError, format_environment_report, get_environment_report
from .state import (
    AXIS_LABELS,
    BUTTON_LABELS,
    BUTTON_NAMES,
    COMBO_PRESETS,
    axis_labels_from_config,
    axis_ranges_from_config,
    button_labels_from_config,
)


def _hat_value(value: str) -> int:
    return max(-1, min(1, int(round(float(value)))))


def _percent_for_range(value: str, min_val: int, max_val: int) -> int:
    """Convert a slider percentage to a raw axis value."""
    span = max_val - min_val
    return int(round(float(value) * span / 100 + min_val))


class JoystickApp:
    def __init__(
        self, root: tk.Tk, device_name: str, update_rate_hz: int, config=None
    ) -> None:
        self.root = root
        self.root.title("Joystick Linux Fake")
        self.root.minsize(860, 620)
        self.controller: JoystickController | None = None
        self.simulation: SimulationSession | None = None
        self.device_name = device_name
        self.update_rate_hz = update_rate_hz
        self.config = config

        # Config-derived data
        if config is not None:
            self._axis_names: list[str] = [
                am.logical for _n, am in sorted(config.axes.items())
            ]
            self._axis_labels: dict[str, str] = axis_labels_from_config(config)
            self._axis_ranges: dict[str, tuple[int, int]] = axis_ranges_from_config(config)
            self._button_names: list[str] = [
                bm.logical for _n, bm in sorted(config.buttons.items())
            ]
            self._button_labels: dict[str, str] = button_labels_from_config(config)
        else:
            from .state import AXIS_NAMES as _AN, AXIS_RANGES as _AR
            self._axis_names = list(_AN)
            self._axis_labels = dict(AXIS_LABELS)
            self._axis_ranges = dict(_AR)
            self._button_names = list(BUTTON_NAMES)
            self._button_labels = dict(BUTTON_LABELS)

        self.status_var = tk.StringVar(value="Device not started.")
        self.pattern_var = tk.StringVar(value="circle")
        self.combo_var = tk.StringVar(value=next(iter(COMBO_PRESETS), ""))

        self.axis_vars: dict[str, tk.IntVar] = {}
        for name in self._axis_names:
            lo, hi = self._axis_ranges.get(name, (-32768, 32767))
            self.axis_vars[name] = tk.IntVar(value=max(lo, min(hi, 0)))

        self.button_vars = {name: tk.BooleanVar(value=False) for name in self._button_names}
        self.manual_widgets: list[tk.Widget] = []
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build_ui()
        self._set_manual_controls_enabled(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        import tkinter.font as _tkfont
        _title_font = _tkfont.Font(font="TkDefaultFont")
        _title_font.configure(weight="bold")
        ttk.Label(header, text="Joystick Linux Fake", font=_title_font).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.status_var).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )

        toolbar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        toolbar.grid(row=1, column=0, sticky="ew")
        for column in range(8):
            toolbar.columnconfigure(column, weight=1 if column == 6 else 0)

        start_button = ttk.Button(toolbar, text="Start Device", command=self.start_device)
        stop_button = ttk.Button(toolbar, text="Stop Device", command=self.stop_device)
        check_button = ttk.Button(
            toolbar, text="Check Setup", command=self.show_environment_report
        )
        reset_button = ttk.Button(toolbar, text="Reset Controls", command=self.reset_controls)
        start_button.grid(row=0, column=0, padx=(0, 8), sticky="w")
        stop_button.grid(row=0, column=1, padx=(0, 8), sticky="w")
        check_button.grid(row=0, column=2, padx=(0, 8), sticky="w")
        reset_button.grid(row=0, column=3, padx=(0, 8), sticky="w")

        ttk.Label(toolbar, text="Simulation").grid(row=0, column=4, padx=(8, 6), sticky="e")
        pattern_box = ttk.Combobox(
            toolbar,
            textvariable=self.pattern_var,
            values=["circle", "figure8", "trigger-pulse", "combo-demo", "idle"],
            width=18,
            state="readonly",
        )
        pattern_box.grid(row=0, column=5, padx=(0, 8), sticky="w")
        run_button = ttk.Button(toolbar, text="Run Pattern", command=self.start_simulation)
        stop_pattern_button = ttk.Button(toolbar, text="Stop Pattern", command=self.stop_simulation)
        run_button.grid(row=0, column=6, padx=(0, 8), sticky="e")
        stop_pattern_button.grid(row=0, column=7, sticky="e")

        content = ttk.Frame(self.root, padding=16)
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        self._build_axis_panel(content)
        self._build_button_panel(content)

    # ------------------------------------------------------------------
    # Axis panel — built dynamically from config
    # ------------------------------------------------------------------

    def _build_axis_panel(self, content: ttk.Frame) -> None:
        axis_frame = ttk.LabelFrame(content, text="Axes and Triggers", padding=12)
        axis_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        for col in range(2):
            axis_frame.columnconfigure(col, weight=1)

        axes_list = list(self._axis_names)
        for idx, name in enumerate(axes_list):
            row = idx // 2
            col = idx % 2
            lo, hi = self._axis_ranges.get(name, (-32768, 32767))
            label = self._axis_labels.get(name, name)
            span = hi - lo
            if span >= 65535:
                # Stick axis
                self._add_axis_row(axis_frame, name, label, row, col, -100, 100,
                                   lambda v, lo_=lo, hi_=hi: _percent_for_range(v, lo_, hi_))
            elif span <= 10:
                # Hat axis
                self._add_axis_row(axis_frame, name, label, row, col, -1, 1,
                                   lambda v: _hat_value(v))
            else:
                # Trigger axis
                self._add_axis_row(axis_frame, name, label, row, col, 0, 100,
                                   lambda v, lo_=lo, hi_=hi: _percent_for_range(v, lo_, hi_))

    def _add_axis_row(self, parent, name, label, row, col, from_, to, convert):
        frame = ttk.Frame(parent, padding=(0, 0, 12, 12))
        frame.grid(row=row, column=col, sticky="ew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=label).grid(row=0, column=0, sticky="w")
        scale = ttk.Scale(
            frame,
            from_=from_,
            to=to,
            variable=self.axis_vars[name],
            command=lambda value, n=name, c=convert: self._on_axis_change(n, c(value)),
        )
        scale.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.axis_vars[name], width=5).grid(
            row=1, column=1, padx=(8, 0)
        )
        self.manual_widgets.append(scale)

    # ------------------------------------------------------------------
    # Button panel — built dynamically from config
    # ------------------------------------------------------------------

    def _build_button_panel(self, content: ttk.Frame) -> None:
        buttons_frame = ttk.LabelFrame(content, text="Buttons and Combos", padding=12)
        buttons_frame.grid(row=0, column=1, sticky="nsew")
        buttons_frame.columnconfigure(0, weight=1)
        buttons_frame.columnconfigure(1, weight=1)
        ttk.Label(
            buttons_frame,
            text="Checked buttons stay pressed together.",
            wraplength=280,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Dynamic button checkboxes
        btn_count = len(self._button_names)
        for index, name in enumerate(self._button_names):
            display = self._button_labels.get(name, name)
            button = ttk.Checkbutton(
                buttons_frame,
                text=display,
                variable=self.button_vars[name],
                command=lambda n=name: self._on_button_toggle(n),
            )
            button.grid(row=1 + index // 2, column=index % 2, sticky="w", pady=4)
            self.manual_widgets.append(button)

        # Combo presets — keyed by display labels; filter to available buttons
        combo_row = 1 + (btn_count + 1) // 2 + 1
        ttk.Separator(buttons_frame, orient="horizontal").grid(
            row=combo_row, column=0, columnspan=2, sticky="ew", pady=10
        )
        ttk.Label(buttons_frame, text="Preset combo").grid(
            row=combo_row + 1, column=0, sticky="w"
        )

        available_combos = []
        for label_, names in COMBO_PRESETS.items():
            if all(n in self._button_names for n in names):
                available_combos.append(label_)
        if not available_combos:
            available_combos = list(COMBO_PRESETS)

        self.combo_var.set(available_combos[0])
        combo_box = ttk.Combobox(
            buttons_frame,
            textvariable=self.combo_var,
            values=available_combos,
            state="readonly",
            width=18,
        )
        combo_box.grid(row=combo_row + 1, column=1, sticky="ew")
        combo_button = ttk.Button(buttons_frame, text="Tap Combo", command=self.tap_combo)
        combo_button.grid(row=combo_row + 2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.manual_widgets.extend([combo_box, combo_button])

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def _set_manual_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self.manual_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                continue

    def start_device(self) -> None:
        if self.controller is not None:
            self.status_var.set(f"Device running: {self.device_name}")
            return
        try:
            controller = JoystickController(
                self.device_name, self.update_rate_hz, config=self.config
            )
            controller.start()
        except DeviceError as exc:
            messagebox.showerror("Unable to start virtual joystick", str(exc))
            return
        self.controller = controller
        self.simulation = SimulationSession(controller)
        self._set_manual_controls_enabled(True)
        self.status_var.set(f"Device running: {self.device_name}")
        self.reset_controls()

    def stop_device(self) -> None:
        if self.simulation is not None:
            self.simulation.stop(reset=True)
        if self.controller is not None:
            self.controller.close()
        self.controller = None
        self.simulation = None
        self._set_manual_controls_enabled(False)
        self.status_var.set("Device stopped.")

    def show_environment_report(self) -> None:
        messagebox.showinfo(
            "Environment check", format_environment_report(get_environment_report())
        )

    def reset_controls(self) -> None:
        if self.simulation is not None and self.simulation.running:
            return
        for name, var in self.axis_vars.items():
            lo, hi = self._axis_ranges.get(name, (-32768, 32767))
            var.set(max(lo, min(hi, 0)))
        for var in self.button_vars.values():
            var.set(False)
        if self.controller is not None:
            self.controller.reset()

    def _on_axis_change(self, axis_name: str, value: int) -> None:
        if self.controller is None or (
            self.simulation is not None and self.simulation.running
        ):
            return
        self.controller.set_axis(axis_name, value)

    def _on_button_toggle(self, button_name: str) -> None:
        if self.controller is None or (
            self.simulation is not None and self.simulation.running
        ):
            return
        self.controller.set_button(button_name, self.button_vars[button_name].get())

    def tap_combo(self) -> None:
        if self.controller is None:
            return
        combo_label = self.combo_var.get()
        names = COMBO_PRESETS.get(combo_label, ())
        available = tuple(n for n in names if n in self._button_names)
        if available:
            self.controller.tap_buttons(available)

    def start_simulation(self) -> None:
        self.start_device()
        if self.controller is None or self.simulation is None:
            return
        self.simulation.start(self.pattern_var.get())
        self._set_manual_controls_enabled(False)
        self.status_var.set(f"Running simulation: {self.pattern_var.get()}")

    def stop_simulation(self) -> None:
        if self.simulation is None:
            return
        self.simulation.stop(reset=True)
        if self.controller is not None:
            self._set_manual_controls_enabled(True)
            self.status_var.set(f"Device running: {self.device_name}")
        self.reset_controls()

    def on_close(self) -> None:
        self.stop_device()
        self.root.destroy()


def launch_gui(
    device_name: str = "Joystick Linux Fake",
    update_rate_hz: int = 125,
    scaling: float | None = None,
    config=None,
) -> int:
    if not os.environ.get("DISPLAY"):
        print(
            "No DISPLAY environment variable found. "
            "Use --mode simulate or run from a desktop session."
        )
        return 1

    try:
        from joystick_watch.tk_scaling import apply_scaling as _apply_scaling
    except ImportError:
        _apply_scaling = None

    root = tk.Tk()
    if _apply_scaling is not None:
        _apply_scaling(root, scaling)
    elif scaling is not None:
        root.tk.call("tk", "scaling", scaling)

    ttk.Style(root).theme_use("clam")
    JoystickApp(
        root, device_name=device_name, update_rate_hz=update_rate_hz, config=config
    )
    root.mainloop()
    return 0
