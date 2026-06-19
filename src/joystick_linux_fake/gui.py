"""Tkinter GUI for the virtual joystick."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from .controller import JoystickController, SimulationSession
from .device import DeviceError, format_environment_report, get_environment_report
from .state import AXIS_LABELS, BUTTON_LABELS, BUTTON_NAMES, COMBO_PRESETS


def _stick_percent_to_axis(value: str) -> int:
    return int(round(float(value) * 32767 / 100))


def _trigger_percent_to_axis(value: str) -> int:
    return int(round(float(value) * 255 / 100))


def _hat_value(value: str) -> int:
    return max(-1, min(1, int(round(float(value)))))


class JoystickApp:
    def __init__(self, root: tk.Tk, device_name: str, update_rate_hz: int) -> None:
        self.root = root
        self.root.title("Joystick Linux Fake")
        self.root.minsize(860, 620)
        self.controller: JoystickController | None = None
        self.simulation: SimulationSession | None = None
        self.device_name = device_name
        self.update_rate_hz = update_rate_hz
        self.status_var = tk.StringVar(value="Device not started.")
        self.pattern_var = tk.StringVar(value="circle")
        self.combo_var = tk.StringVar(value=next(iter(COMBO_PRESETS)))
        self.axis_vars = {
            "left_x": tk.IntVar(value=0),
            "left_y": tk.IntVar(value=0),
            "right_x": tk.IntVar(value=0),
            "right_y": tk.IntVar(value=0),
            "l2": tk.IntVar(value=0),
            "r2": tk.IntVar(value=0),
            "dpad_x": tk.IntVar(value=0),
            "dpad_y": tk.IntVar(value=0),
        }
        self.button_vars = {name: tk.BooleanVar(value=False) for name in BUTTON_NAMES}
        self.manual_widgets: list[tk.Widget] = []
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build_ui()
        self._set_manual_controls_enabled(False)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Joystick Linux Fake", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(6, 0))

        toolbar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        toolbar.grid(row=1, column=0, sticky="ew")
        for column in range(8):
            toolbar.columnconfigure(column, weight=1 if column == 6 else 0)

        start_button = ttk.Button(toolbar, text="Start Device", command=self.start_device)
        stop_button = ttk.Button(toolbar, text="Stop Device", command=self.stop_device)
        check_button = ttk.Button(toolbar, text="Check Setup", command=self.show_environment_report)
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

        axis_frame = ttk.LabelFrame(content, text="Axes and Triggers", padding=12)
        axis_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        axis_frame.columnconfigure(0, weight=1)
        axis_frame.columnconfigure(1, weight=1)

        self._add_stick_scale(axis_frame, "left_x", row=0, column=0)
        self._add_stick_scale(axis_frame, "left_y", row=1, column=0)
        self._add_stick_scale(axis_frame, "right_x", row=0, column=1)
        self._add_stick_scale(axis_frame, "right_y", row=1, column=1)
        self._add_trigger_scale(axis_frame, "l2", row=2, column=0)
        self._add_trigger_scale(axis_frame, "r2", row=2, column=1)
        self._add_hat_scale(axis_frame, "dpad_x", row=3, column=0)
        self._add_hat_scale(axis_frame, "dpad_y", row=3, column=1)

        buttons_frame = ttk.LabelFrame(content, text="Buttons and Combos", padding=12)
        buttons_frame.grid(row=0, column=1, sticky="nsew")
        buttons_frame.columnconfigure(0, weight=1)
        buttons_frame.columnconfigure(1, weight=1)
        ttk.Label(
            buttons_frame,
            text="Checked buttons stay pressed together, so manual combinations are supported directly.",
            wraplength=280,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        for index, name in enumerate(BUTTON_NAMES):
            button = ttk.Checkbutton(
                buttons_frame,
                text=BUTTON_LABELS[name],
                variable=self.button_vars[name],
                command=lambda control=name: self._on_button_toggle(control),
            )
            button.grid(row=1 + index // 2, column=index % 2, sticky="w", pady=4)
            self.manual_widgets.append(button)

        combo_row = 1 + (len(BUTTON_NAMES) + 1) // 2 + 1
        ttk.Separator(buttons_frame, orient="horizontal").grid(
            row=combo_row, column=0, columnspan=2, sticky="ew", pady=10
        )
        ttk.Label(buttons_frame, text="Preset combo").grid(row=combo_row + 1, column=0, sticky="w")
        combo_box = ttk.Combobox(
            buttons_frame,
            textvariable=self.combo_var,
            values=list(COMBO_PRESETS),
            state="readonly",
            width=18,
        )
        combo_box.grid(row=combo_row + 1, column=1, sticky="ew")
        combo_button = ttk.Button(buttons_frame, text="Tap Combo", command=self.tap_combo)
        combo_button.grid(row=combo_row + 2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.manual_widgets.extend([combo_box, combo_button, pattern_box, reset_button])

    def _add_stick_scale(self, parent: ttk.Frame, axis_name: str, row: int, column: int) -> None:
        frame = ttk.Frame(parent, padding=(0, 0, 12, 12))
        frame.grid(row=row, column=column, sticky="ew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=AXIS_LABELS[axis_name]).grid(row=0, column=0, sticky="w")
        scale = ttk.Scale(
            frame,
            from_=-100,
            to=100,
            variable=self.axis_vars[axis_name],
            command=lambda value, control=axis_name: self._on_stick_change(control, value),
        )
        scale.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.axis_vars[axis_name], width=5).grid(row=1, column=1, padx=(8, 0))
        self.manual_widgets.append(scale)

    def _add_trigger_scale(self, parent: ttk.Frame, axis_name: str, row: int, column: int) -> None:
        frame = ttk.Frame(parent, padding=(0, 0, 12, 0))
        frame.grid(row=row, column=column, sticky="ew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=AXIS_LABELS[axis_name]).grid(row=0, column=0, sticky="w")
        scale = ttk.Scale(
            frame,
            from_=0,
            to=100,
            variable=self.axis_vars[axis_name],
            command=lambda value, control=axis_name: self._on_trigger_change(control, value),
        )
        scale.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.axis_vars[axis_name], width=5).grid(row=1, column=1, padx=(8, 0))
        self.manual_widgets.append(scale)

    def _add_hat_scale(self, parent: ttk.Frame, axis_name: str, row: int, column: int) -> None:
        frame = ttk.Frame(parent, padding=(0, 12, 12, 0))
        frame.grid(row=row, column=column, sticky="ew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=AXIS_LABELS[axis_name]).grid(row=0, column=0, sticky="w")
        scale = ttk.Scale(
            frame,
            from_=-1,
            to=1,
            variable=self.axis_vars[axis_name],
            command=lambda value, control=axis_name: self._on_hat_change(control, value),
        )
        scale.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.axis_vars[axis_name], width=5).grid(row=1, column=1, padx=(8, 0))
        self.manual_widgets.append(scale)

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
            controller = JoystickController(self.device_name, self.update_rate_hz)
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
        messagebox.showinfo("Environment check", format_environment_report(get_environment_report()))

    def reset_controls(self) -> None:
        if self.simulation is not None and self.simulation.running:
            return
        for variable in self.axis_vars.values():
            variable.set(0)
        for variable in self.button_vars.values():
            variable.set(False)
        if self.controller is not None:
            self.controller.reset()

    def _on_stick_change(self, axis_name: str, value: str) -> None:
        if self.controller is None or (self.simulation is not None and self.simulation.running):
            return
        self.controller.set_axis(axis_name, _stick_percent_to_axis(value))

    def _on_trigger_change(self, axis_name: str, value: str) -> None:
        if self.controller is None or (self.simulation is not None and self.simulation.running):
            return
        self.controller.set_axis(axis_name, _trigger_percent_to_axis(value))

    def _on_hat_change(self, axis_name: str, value: str) -> None:
        if self.controller is None or (self.simulation is not None and self.simulation.running):
            return
        self.controller.set_axis(axis_name, _hat_value(value))

    def _on_button_toggle(self, button_name: str) -> None:
        if self.controller is None or (self.simulation is not None and self.simulation.running):
            return
        self.controller.set_button(button_name, self.button_vars[button_name].get())

    def tap_combo(self) -> None:
        if self.controller is None:
            return
        self.controller.tap_buttons(tuple(COMBO_PRESETS[self.combo_var.get()]))

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


def launch_gui(device_name: str = "Joystick Linux Fake", update_rate_hz: int = 125) -> int:
    if not os.environ.get("DISPLAY"):
        print("No DISPLAY environment variable found. Use --mode simulate or run from a desktop session.")
        return 1
    root = tk.Tk()
    ttk.Style(root).theme_use("clam")
    JoystickApp(root, device_name=device_name, update_rate_hz=update_rate_hz)
    root.mainloop()
    return 0
