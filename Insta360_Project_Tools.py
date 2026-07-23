#!/usr/bin/env python3
import json
import math
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

CFG = os.path.expanduser("~/.insta360_project_tools.json")

INTRO_TEXT = (
    "Batch-modify camera keyframes (FOV, orientation, distance) across an entire Insta360 Studio project.\n"
    "Load an .insproj file, enable the parameters to change, pick a mode and value, then click Apply."
)

MODE_HELP = (
    "Modes:\n"
    "  • Scale  — multiply each existing value  (e.g. 1.5 = 50% larger)\n"
    "  • Offset — add to each existing value  (e.g. +10 shifts by 10°)\n"
    "  • Set    — replace every value with this exact number"
)

PARAM_HINTS = {
    "fov":      "Field of view multiplier per keyframe. Scale zooms all keyframes proportionally; Set forces an exact FOV.",
    "pan":      "Horizontal camera rotation (yaw), in degrees. Offset shifts all keyframes by ±amount; Set forces an exact angle.",
    "tilt":     "Vertical camera rotation (pitch), in degrees. Offset shifts all keyframes by ±amount; Set forces an exact angle.",
    "roll":     "Camera roll rotation, in degrees. Offset shifts all keyframes by ±amount; Set forces an exact angle.",
    "distance": "Camera distance from subject. Scale multiplies all keyframes proportionally; Set forces an exact distance.",
}

# FOV scene preview tabs. Each tab renders the current framing in its
# "source" aspect ratio and the predicted framing in its "target" aspect
# ratio, so you can see the shape of the crop change, not just the size.
# aspect_ratio = width / height
FOV_TABS = [
    ("9:16 → 16:9",   9.0 / 16.0,   16.0 / 9.0),
    ("16:9 → 9:16",   16.0 / 9.0,   9.0 / 16.0),
    ("1:1 square",    1.0,          1.0),
]

# Built-in presets. Only include the parameters the preset actively sets;
# everything else is reset to defaults (disabled) when a preset is loaded.
BUILTIN_PRESETS = {
    "9:16 → 16:9  (widen FOV ×2.1)": {
        "fov": {"enabled": True, "mode": "scale", "value": "2.1"},
    },
    "16:9 → 9:16  (narrow FOV ×0.5)": {
        "fov": {"enabled": True, "mode": "scale", "value": "0.5"},
    },
    "Level horizon (roll → 0)": {
        "roll": {"enabled": True, "mode": "set", "value": "0"},
    },
}
DEFAULT_PRESET_LABEL = "— Preset —"


class Tooltip:
    """Small delayed hover tooltip for tk widgets."""

    def __init__(self, widget, text, delay=450, wraplength=300):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._unschedule()
        self.after_id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.tip,
            text=self.text,
            background="#ffffe0",
            foreground="#222",
            relief="solid",
            borderwidth=1,
            wraplength=self.wraplength,
            justify="left",
            padx=6,
            pady=3,
            font=("TkDefaultFont", 9),
        ).pack()

    def _hide(self, _event=None):
        self._unschedule()
        if self.tip:
            self.tip.destroy()
            self.tip = None


SUPPORTED_PARAMS = ("fov", "pan", "tilt", "roll", "distance")
PARAM_CONFIG = {
    "fov": {
        "label": "FOV",
        "modes": (("scale", "Scale"), ("set", "Set")),
        "default": "1",
        "slider": {"from": 0.0, "to": 3.0, "resolution": 0.01},
    },
    "pan": {
        "label": "Pan",
        "modes": (("offset", "Offset"), ("set", "Set")),
        "default": "0",
        "slider": {"from": -180.0, "to": 180.0, "resolution": 0.1},
    },
    "tilt": {
        "label": "Tilt",
        "modes": (("offset", "Offset"), ("set", "Set")),
        "default": "0",
        "slider": {"from": -180.0, "to": 180.0, "resolution": 0.1},
    },
    "roll": {
        "label": "Roll",
        "modes": (("offset", "Offset"), ("set", "Set")),
        "default": "0",
        "slider": {"from": -180.0, "to": 180.0, "resolution": 0.1},
    },
    "distance": {
        "label": "Distance",
        "modes": (("scale", "Scale"), ("set", "Set")),
        "default": "1",
        "slider": {"from": 0.0, "to": 3.0, "resolution": 0.01},
    },
}


def is_numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_cfg():
    data = {}
    if os.path.exists(CFG):
        try:
            with open(CFG, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except Exception:
            data = {}
    data.setdefault("recent", [])
    data.setdefault("presets", {})
    return data


def save_cfg():
    with open(CFG, "w", encoding="utf-8") as file_obj:
        json.dump(cfg, file_obj, indent=2)


def load_project(path):
    with open(path, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def modify_parameter(current_value, mode, amount):
    if mode == "scale":
        return current_value * amount
    if mode == "offset":
        return current_value + amount
    return amount


def traverse_project(node, on_transform_dict=None):
    if isinstance(node, dict):
        numeric_supported = {
            name: value
            for name, value in node.items()
            if name in SUPPORTED_PARAMS and is_numeric(value)
        }
        if numeric_supported and on_transform_dict is not None:
            on_transform_dict(node, numeric_supported)
        for value in node.values():
            traverse_project(value, on_transform_dict)
    elif isinstance(node, list):
        for item in node:
            traverse_project(item, on_transform_dict)


def collect_series(data):
    """Collect ordered lists of values per parameter, in traversal order."""
    series = {name: [] for name in SUPPORTED_PARAMS}

    def collect(_node, numeric_supported):
        for name in SUPPORTED_PARAMS:
            if name in numeric_supported:
                series[name].append(numeric_supported[name])

    traverse_project(data, collect)
    return series


def scan_project(data):
    ranges = {name: {"min": None, "max": None} for name in SUPPORTED_PARAMS}
    unsupported = set()
    keyframe_count = 0

    def scan_transform_dict(node, numeric_supported):
        nonlocal keyframe_count
        keyframe_count += 1
        for name, value in numeric_supported.items():
            stats = ranges[name]
            stats["min"] = value if stats["min"] is None else min(stats["min"], value)
            stats["max"] = value if stats["max"] is None else max(stats["max"], value)
        for name, value in node.items():
            if name not in SUPPORTED_PARAMS and is_numeric(value):
                unsupported.add(name)

    traverse_project(data, scan_transform_dict)
    return {
        "keyframe_count": keyframe_count,
        "ranges": ranges,
        "unsupported": sorted(unsupported, key=str.lower),
    }


def save_project(path, data, overwrite_original):
    if overwrite_original:
        base, ext = os.path.splitext(path)
        backup = base + "_backup" + ext
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        output_path = path
    else:
        base, ext = os.path.splitext(path)
        output_path = base + "_modified" + ext

    with open(output_path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, separators=(",", ":"))
    return output_path


def format_range_text(stats, unit=""):
    if stats["min"] is None:
        return "—"
    return f"{stats['min']:g}{unit} / {stats['max']:g}{unit}"


def update_scan_display(scan_result):
    keyframe_count_var.set(str(scan_result["keyframe_count"]))
    for name in SUPPORTED_PARAMS:
        stats = scan_result["ranges"][name]
        if name in ("pan", "tilt", "roll") and stats["min"] is not None:
            # File stores radians; display as degrees.
            display_stats = {
                "min": math.degrees(stats["min"]),
                "max": math.degrees(stats["max"]),
            }
            range_vars[name].set(format_range_text(display_stats, "°"))
        else:
            range_vars[name].set(format_range_text(stats))
    unsupported = scan_result["unsupported"]
    unsupported_var.set(", ".join(unsupported) if unsupported else "None")


def clear_scan_display():
    keyframe_count_var.set("0")
    for name in SUPPORTED_PARAMS:
        range_vars[name].set("—")
    unsupported_var.set("None")


def remember(path):
    path = os.path.abspath(path)
    recent = [item for item in cfg["recent"] if item != path]
    recent.insert(0, path)
    cfg["recent"] = recent[:10]
    save_cfg()
    refresh_recent()


def refresh_recent():
    recent_menu["menu"].delete(0, "end")
    if not cfg["recent"]:
        recent_menu["menu"].add_command(label="(empty)")
        return
    for path in cfg["recent"]:
        recent_menu["menu"].add_command(
            label=os.path.basename(path),
            command=lambda selected_path=path: open_project(selected_path),
        )


def get_current_settings_snapshot():
    return {
        name: {
            "enabled": parameter_enabled[name].get(),
            "mode": parameter_modes[name].get(),
            "value": parameter_values[name].get(),
        }
        for name in SUPPORTED_PARAMS
    }


def reset_all_parameters():
    for name in SUPPORTED_PARAMS:
        config = PARAM_CONFIG[name]
        parameter_enabled[name].set(False)
        parameter_modes[name].set(config["modes"][0][0])
        parameter_values[name].set(config["default"])
        try:
            parameter_sliders[name].set(float(config["default"]))
        except (ValueError, tk.TclError):
            pass


def apply_preset_settings(preset_data):
    reset_all_parameters()
    for name, params in preset_data.items():
        if name not in SUPPORTED_PARAMS:
            continue
        parameter_enabled[name].set(bool(params.get("enabled", False)))
        parameter_modes[name].set(
            params.get("mode", PARAM_CONFIG[name]["modes"][0][0])
        )
        value_str = str(params.get("value", PARAM_CONFIG[name]["default"]))
        parameter_values[name].set(value_str)
        try:
            parameter_sliders[name].set(float(value_str))
        except (ValueError, tk.TclError):
            pass


def get_all_presets():
    combined = dict(BUILTIN_PRESETS)
    combined.update(cfg.get("presets", {}))
    return combined


def apply_preset(name):
    presets = get_all_presets()
    if name in presets:
        apply_preset_settings(presets[name])
        preset_var.set(name)


def refresh_presets():
    preset_menu["menu"].delete(0, "end")
    for name in BUILTIN_PRESETS:
        preset_menu["menu"].add_command(
            label=name,
            command=lambda selected_name=name: apply_preset(selected_name),
        )
    user_presets = sorted(cfg.get("presets", {}).keys(), key=str.lower)
    if user_presets:
        preset_menu["menu"].add_separator()
        for name in user_presets:
            preset_menu["menu"].add_command(
                label=name,
                command=lambda selected_name=name: apply_preset(selected_name),
            )


def save_preset():
    name = simpledialog.askstring(
        "Save preset",
        "Preset name:",
        parent=root,
    )
    if not name:
        return
    name = name.strip()
    if not name:
        return
    if name == DEFAULT_PRESET_LABEL:
        messagebox.showerror("Error", "Choose a different name.")
        return
    if name in BUILTIN_PRESETS:
        messagebox.showerror("Error", "That name is used by a built-in preset. Pick another.")
        return
    user_presets = cfg.setdefault("presets", {})
    if name in user_presets:
        if not messagebox.askyesno("Overwrite?", f"Preset '{name}' exists. Overwrite?"):
            return
    user_presets[name] = get_current_settings_snapshot()
    save_cfg()
    refresh_presets()
    preset_var.set(name)


def delete_preset():
    name = preset_var.get()
    if not name or name == DEFAULT_PRESET_LABEL:
        messagebox.showinfo("Delete preset", "Select a preset first.")
        return
    if name in BUILTIN_PRESETS:
        messagebox.showerror("Error", "Built-in presets cannot be deleted.")
        return
    user_presets = cfg.get("presets", {})
    if name not in user_presets:
        return
    if not messagebox.askyesno("Delete?", f"Delete preset '{name}'?"):
        return
    del user_presets[name]
    save_cfg()
    refresh_presets()
    preset_var.set(DEFAULT_PRESET_LABEL)


def open_project(path):
    if not os.path.exists(path):
        messagebox.showerror("Error", "Project file not found.")
        return
    try:
        data = load_project(path)
    except Exception as exc:
        messagebox.showerror("Error", f"Could not open project:\n{exc}")
        return
    selected.set(path)
    remember(path)
    current_series.clear()
    current_series.update(collect_series(data))
    update_scan_display(scan_project(data))
    schedule_preview_redraw()


def browse():
    initial = os.path.dirname(selected.get()) if selected.get() else (
        os.path.dirname(cfg["recent"][0]) if cfg["recent"] else os.path.expanduser("~")
    )
    file_path = filedialog.askopenfilename(
        initialdir=initial,
        filetypes=[("Insta360 Project", "*.insproj *.insprj"), ("All files", "*.*")],
    )
    if file_path:
        open_project(file_path)


def reveal():
    path = selected.get()
    if not path or not os.path.exists(path):
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def get_parameter_settings():
    settings = {}
    for name in SUPPORTED_PARAMS:
        try:
            value = float(parameter_values[name].get().strip())
        except ValueError:
            label = PARAM_CONFIG[name]["label"]
            raise ValueError(f"{label}: enter a valid number.")
        # Angular parameters: the UI is in degrees for readability, but the
        # .insproj file stores radians — convert here so modify_parameter
        # works in the file's own units.
        if name in ("pan", "tilt", "roll"):
            value = math.radians(value)
        settings[name] = {
            "enabled": parameter_enabled[name].get(),
            "mode": parameter_modes[name].get(),
            "value": value,
        }
    return settings


def process():
    path = selected.get()
    if not path:
        messagebox.showerror("Error", "Choose project")
        return
    try:
        settings = get_parameter_settings()
        data = load_project(path)
    except Exception as exc:
        messagebox.showerror("Error", str(exc))
        return

    if not any(s["enabled"] for s in settings.values()):
        messagebox.showinfo("Nothing to do", "Enable at least one parameter to modify.")
        return

    modified_counts = {name: 0 for name in SUPPORTED_PARAMS}
    touched_keyframes = 0

    def edit_transform_dict(node, numeric_supported):
        nonlocal touched_keyframes
        touched = False
        for name in SUPPORTED_PARAMS:
            if settings[name]["enabled"] and name in numeric_supported:
                new_value = modify_parameter(
                    node[name],
                    settings[name]["mode"],
                    settings[name]["value"],
                )
                if new_value != node[name]:
                    node[name] = new_value
                    modified_counts[name] += 1
                    touched = True
        if touched:
            touched_keyframes += 1

    traverse_project(data, edit_transform_dict)

    try:
        output_path = save_project(path, data, overwrite.get())
    except Exception as exc:
        messagebox.showerror("Error", f"Could not save project:\n{exc}")
        return

    update_scan_display(scan_project(data))
    current_series.clear()
    current_series.update(collect_series(data))
    schedule_preview_redraw()
    changed_names = [
        f"{PARAM_CONFIG[name]['label']}: {modified_counts[name]}"
        for name in SUPPORTED_PARAMS
        if modified_counts[name]
    ]
    if not changed_names:
        changed_names.append("No numeric transform values changed.")
    messagebox.showinfo(
        "Done",
        f"Modified {touched_keyframes} keyframes.\n"
        f"Saved to:\n{output_path}\n\n"
        + "\n".join(changed_names),
    )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
cfg = load_cfg()
root = tk.Tk()
root.title("Insta360 Project Tools — Mass Keyframe Modifier")
root.geometry("960x700")
root.minsize(900, 620)

selected = tk.StringVar()
overwrite = tk.BooleanVar(value=True)
recent_var = tk.StringVar(value="Recent")
preset_var = tk.StringVar(value=DEFAULT_PRESET_LABEL)
preview_param_var = tk.StringVar(value="fov")

# Latest series collected from the loaded project (name -> [values in traversal order])
current_series = {name: [] for name in SUPPORTED_PARAMS}
_preview_after_id = None
keyframe_count_var = tk.StringVar(value="0")
range_vars = {name: tk.StringVar(value="—") for name in SUPPORTED_PARAMS}
unsupported_var = tk.StringVar(value="None")
parameter_enabled = {}
parameter_modes = {}
parameter_values = {}
parameter_sliders = {}

main = ttk.Frame(root, padding=10)
main.pack(fill="both", expand=True)
main.columnconfigure(0, weight=1, minsize=280)
main.columnconfigure(1, weight=2)
main.rowconfigure(2, weight=0)
main.rowconfigure(3, weight=1)

# --- Row 0: Intro / description ------------------------------------------
intro = ttk.Label(main, text=INTRO_TEXT, justify="left", foreground="#555")
intro.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

# --- Row 1: Project selector (spans both columns) --------------------------
project_row = ttk.Frame(main)
project_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
project_row.columnconfigure(1, weight=1)

ttk.Label(project_row, text="Project:").grid(row=0, column=0, padx=(0, 6))
project_entry = ttk.Entry(project_row, textvariable=selected)
project_entry.grid(row=0, column=1, sticky="ew")
browse_btn = ttk.Button(project_row, text="Browse", command=browse, width=8)
browse_btn.grid(row=0, column=2, padx=(6, 0))
reveal_btn = ttk.Button(project_row, text="Reveal", command=reveal, width=8)
reveal_btn.grid(row=0, column=3, padx=(4, 0))
recent_menu = tk.OptionMenu(project_row, recent_var, "")
recent_menu.configure(width=8)
recent_menu.grid(row=0, column=4, padx=(4, 0))

Tooltip(project_entry, "Path to the loaded Insta360 Studio project file (.insproj / .insprj).")
Tooltip(browse_btn, "Open an Insta360 Studio project file (.insproj or .insprj).\n"
                    "The project file lives in the folder Insta360 Studio creates when you save.")
Tooltip(reveal_btn, "Show the currently loaded project in your system file manager.")
Tooltip(recent_menu, "Recently opened projects — click one to reload it.")

# --- Row 2: Analysis (left) | Adjustments (right) --------------------------
stats_frame = ttk.LabelFrame(main, text="Project Analysis", padding=(10, 6))
stats_frame.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
Tooltip(stats_frame, "Read-only summary of the loaded project:\n"
                     "how many keyframes it has, and the min/max value observed for each supported parameter.\n"
                     "'Unsupported' lists numeric keys the tool won't touch.")
stats_frame.columnconfigure(1, weight=1)

ttk.Label(stats_frame, text="Keyframes:").grid(row=0, column=0, sticky="w", padx=(0, 8))
ttk.Label(stats_frame, textvariable=keyframe_count_var).grid(row=0, column=1, sticky="w")

for row_index, name in enumerate(SUPPORTED_PARAMS, start=1):
    ttk.Label(stats_frame, text=f"{PARAM_CONFIG[name]['label']}:").grid(
        row=row_index, column=0, sticky="w", padx=(0, 8), pady=(2, 0)
    )
    ttk.Label(stats_frame, textvariable=range_vars[name]).grid(
        row=row_index, column=1, sticky="w", pady=(2, 0)
    )

ttk.Separator(stats_frame, orient="horizontal").grid(
    row=6, column=0, columnspan=2, sticky="ew", pady=(8, 6)
)
ttk.Label(stats_frame, text="Unsupported:").grid(row=7, column=0, sticky="nw", padx=(0, 8))
ttk.Label(
    stats_frame,
    textvariable=unsupported_var,
    wraplength=200,
    justify="left",
).grid(row=7, column=1, sticky="w")

controls = ttk.LabelFrame(main, text="Adjustments", padding=(10, 6))
controls.grid(row=2, column=1, sticky="nsew")
controls.columnconfigure(2, weight=1)
Tooltip(controls, "Choose which parameters to modify and how.\n\n" + MODE_HELP)

# --- Preset row (top of Adjustments) --------------------------------------
preset_row = ttk.Frame(controls)
preset_row.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 4))
preset_row.columnconfigure(1, weight=1)

ttk.Label(preset_row, text="Preset:").grid(row=0, column=0, padx=(0, 6))
preset_menu = tk.OptionMenu(preset_row, preset_var, "")
preset_menu.grid(row=0, column=1, sticky="ew")
save_preset_btn = ttk.Button(preset_row, text="Save…", command=save_preset, width=7)
save_preset_btn.grid(row=0, column=2, padx=(4, 0))
delete_preset_btn = ttk.Button(preset_row, text="Delete", command=delete_preset, width=7)
delete_preset_btn.grid(row=0, column=3, padx=(4, 0))

Tooltip(
    preset_menu,
    "Load a saved preset — settings below are updated but nothing is applied to the project until you click Apply.\n\n"
    "Built-in presets are always available.\n"
    "Your own presets can be added with 'Save…' and removed with 'Delete'.",
)
Tooltip(
    save_preset_btn,
    "Save the current parameter settings (checkboxes, modes, values) as a named preset for reuse.",
)
Tooltip(
    delete_preset_btn,
    "Delete the currently selected preset. Built-in presets cannot be deleted.",
)

ttk.Separator(controls, orient="horizontal").grid(
    row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6)
)


def format_slider_value(raw_value, resolution):
    decimals = 0
    text = f"{resolution:.10f}".rstrip("0")
    if "." in text:
        decimals = len(text.split(".", 1)[1])
    return f"{float(raw_value):.{decimals}f}"


def make_slider_handler(name, resolution):
    def handle_slider(raw_value):
        parameter_values[name].set(format_slider_value(raw_value, resolution))
    return handle_slider


def sync_slider_from_entry(name):
    try:
        parameter_sliders[name].set(float(parameter_values[name].get().strip()))
    except ValueError:
        pass


for row_index, name in enumerate(SUPPORTED_PARAMS):
    param_row = row_index + 2  # offset for preset row + separator
    config = PARAM_CONFIG[name]
    slider_cfg = config["slider"]

    parameter_enabled[name] = tk.BooleanVar(value=(name == "fov"))
    parameter_modes[name] = tk.StringVar(value=config["modes"][0][0])
    parameter_values[name] = tk.StringVar(value=config["default"])

    # Column 0: checkbox with label
    checkbox = ttk.Checkbutton(
        controls,
        text=config["label"],
        variable=parameter_enabled[name],
        width=9,
    )
    checkbox.grid(row=param_row, column=0, sticky="w", pady=3)
    Tooltip(checkbox, PARAM_HINTS[name] + "\n\nCheck to include this parameter when Apply is clicked.")

    # Column 1: mode radios
    mode_frame = ttk.Frame(controls)
    mode_frame.grid(row=param_row, column=1, sticky="w", padx=(0, 6))
    Tooltip(mode_frame, MODE_HELP)
    for mode_name, label_text in config["modes"]:
        ttk.Radiobutton(
            mode_frame,
            text=label_text,
            value=mode_name,
            variable=parameter_modes[name],
        ).pack(side="left", padx=(0, 4))

    # Column 2: slider (expandable)
    parameter_sliders[name] = tk.Scale(
        controls,
        from_=slider_cfg["from"],
        to=slider_cfg["to"],
        resolution=slider_cfg["resolution"],
        orient="horizontal",
        showvalue=False,
        length=140,
        command=make_slider_handler(name, slider_cfg["resolution"]),
    )
    parameter_sliders[name].set(float(config["default"]))
    parameter_sliders[name].grid(row=param_row, column=2, sticky="ew", padx=(4, 6))
    Tooltip(
        parameter_sliders[name],
        f"Drag to set the value  (range {slider_cfg['from']:g} to {slider_cfg['to']:g}).\n"
        "Or type an exact number in the entry — it can exceed the slider range.",
    )

    # Column 3: value entry
    entry = ttk.Entry(controls, textvariable=parameter_values[name], width=7)
    entry.grid(row=param_row, column=3, sticky="e")
    entry.bind("<FocusOut>", lambda _e, n=name: sync_slider_from_entry(n))
    entry.bind("<Return>", lambda _e, n=name: sync_slider_from_entry(n))
    Tooltip(entry, "Exact value. Press Enter or click away to sync the slider.\n"
                   "Values outside the slider range are allowed.")

# --- Row 3: Preview panel (spans both columns) -----------------------------
preview_frame = ttk.LabelFrame(main, text="Preview  —  predicted values after Apply", padding=(10, 6))
preview_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
preview_frame.columnconfigure(0, weight=3)
preview_frame.columnconfigure(1, weight=1, minsize=250)
preview_frame.rowconfigure(2, weight=1)

preview_header = ttk.Frame(preview_frame)
preview_header.grid(row=0, column=0, columnspan=2, sticky="ew")

ttk.Label(preview_header, text="Show:").pack(side="left", padx=(0, 6))
for _name in SUPPORTED_PARAMS:
    ttk.Radiobutton(
        preview_header,
        text=PARAM_CONFIG[_name]["label"],
        value=_name,
        variable=preview_param_var,
    ).pack(side="left", padx=(0, 4))

# Legend on the right
tk.Label(preview_header, text=" predicted", fg="#e67e22").pack(side="right")
tk.Label(preview_header, text="●", fg="#e67e22").pack(side="right")
tk.Label(preview_header, text="   current", fg="#666").pack(side="right")
tk.Label(preview_header, text="●", fg="#666").pack(side="right")

# Caption row — makes it unambiguous what each panel below is showing.
caption_row = ttk.Frame(preview_frame)
caption_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
caption_row.columnconfigure(0, weight=3)
caption_row.columnconfigure(1, weight=1, minsize=250)

ttk.Label(
    caption_row,
    text="Keyframe Timeline Preview",
    font=("TkDefaultFont", 9, "bold"),
    foreground="#444",
).grid(row=0, column=0, sticky="w")
ttk.Label(
    caption_row,
    text="Camera FOV Preview",
    font=("TkDefaultFont", 9, "bold"),
    foreground="#444",
).grid(row=0, column=1, sticky="w", padx=(6, 0))

preview_canvas = tk.Canvas(
    preview_frame,
    height=150,
    bg="#fafafa",
    highlightthickness=1,
    highlightbackground="#ccc",
)
preview_canvas.grid(row=2, column=0, sticky="nsew", pady=(4, 0))

fov_scene_notebook = ttk.Notebook(preview_frame)
fov_scene_notebook.grid(row=2, column=1, sticky="nsew", pady=(4, 0), padx=(6, 0))

fov_scene_canvases = []
for _tab_label, _src_aspect, _tgt_aspect in FOV_TABS:
    _tab_frame = ttk.Frame(fov_scene_notebook)
    _tab_canvas = tk.Canvas(
        _tab_frame,
        width=210,
        height=200,
        bg="#f5f5f5",
        highlightthickness=0,
    )
    _tab_canvas.pack(fill="both", expand=True)
    fov_scene_notebook.add(_tab_frame, text=_tab_label)
    fov_scene_canvases.append(_tab_canvas)

Tooltip(
    fov_scene_notebook,
    "Preview of framing at the loaded project's average FOV.\n\n"
    "Tabs:\n"
    "  • 1:1 square — neutral view, doesn't assume an aspect ratio.\n"
    "  • 9:16 → 16:9 — starting from a portrait frame that nicely fits the subject,\n"
    "    shows what the same footage looks like once widened to landscape.\n"
    "  • 16:9 → 9:16 — starting from a landscape frame that nicely fits the subject,\n"
    "    shows what it looks like once narrowed to portrait.\n\n"
    "Grey rectangle = current framing (sized to just fit the subject in that tab's\n"
    "starting aspect ratio). Orange dashed = predicted after Apply.\n"
    "The person silhouette is the same size in every tab — the frame is what changes.\n"
    "Values are the .insproj FOV scale factor, not degrees.",
)

Tooltip(
    preview_frame,
    "Live preview of the values that would be written by Apply.\n"
    "Grey dots = current keyframe values in the loaded project.\n"
    "Orange dots = what those values would become with the currently enabled Adjustments.\n"
    "The X axis is keyframe index (in file traversal order); Y is the parameter value.",
)

# --- Row 4: Overwrite (left) | Apply (right) -------------------------------
bottom = ttk.Frame(main)
bottom.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
bottom.columnconfigure(0, weight=1)

overwrite_cb = ttk.Checkbutton(
    bottom,
    text="Overwrite original (backup created once)",
    variable=overwrite,
)
overwrite_cb.grid(row=0, column=0, sticky="w")
Tooltip(
    overwrite_cb,
    "ON  — the original file is replaced. First run creates <name>_backup.insproj alongside it.\n"
    "OFF — the modified project is saved as <name>_modified.insproj; the original is untouched.",
)

apply_btn = ttk.Button(bottom, text="Apply", command=process, width=12)
apply_btn.grid(row=0, column=1, sticky="e")
Tooltip(apply_btn, "Walk every keyframe in the project and update the enabled parameters.\n"
                   "A summary of how many keyframes changed is shown when done.")

def schedule_preview_redraw(*_args):
    global _preview_after_id
    if _preview_after_id is not None:
        try:
            root.after_cancel(_preview_after_id)
        except tk.TclError:
            pass
    _preview_after_id = root.after(60, _do_all_redraws)


def _do_all_redraws():
    redraw_preview()
    redraw_fov_scene()


def redraw_fov_scene():
    """Draw the currently active FOV scene tab."""
    try:
        active_index = fov_scene_notebook.index("current")
    except tk.TclError:
        return
    canvas = fov_scene_canvases[active_index]
    _tab_label, source_aspect, target_aspect = FOV_TABS[active_index]
    canvas.delete("all")
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    if width < 20 or height < 20:
        canvas.after(80, redraw_fov_scene)
        return

    fov_values = current_series.get("fov", [])
    if not fov_values:
        canvas.create_text(
            width / 2, height / 2,
            text="No FOV data",
            fill="#999",
        )
        return

    current_avg = sum(fov_values) / len(fov_values)
    predicted_avg = current_avg
    if parameter_enabled["fov"].get():
        try:
            value = float(parameter_values["fov"].get().strip())
            mode = parameter_modes["fov"].get()
            predicted_values = [
                modify_parameter(v, mode, value) for v in fov_values
            ]
            predicted_avg = sum(predicted_values) / len(predicted_values)
        except ValueError:
            pass

    # --- Scene is a WIDE panorama-like rectangle (2:1) to reflect that
    #     Insta360 sees 360° horizontally around the camera. Sky and ground
    #     span the full canvas width.
    label_top = 20
    label_bottom = 18
    scene_target_aspect = 2.0  # wide, panorama-like
    canvas_left = 4
    canvas_right = width - 4
    scene_w = canvas_right - canvas_left
    scene_h_max = height - label_top - label_bottom
    # Prefer wide scene; if the canvas is unusually tall, cap scene_h to fit aspect.
    scene_h = min(scene_h_max, scene_w / scene_target_aspect)
    scene_left = canvas_left
    scene_right = canvas_right
    scene_top = label_top + (scene_h_max - scene_h) / 2
    scene_bottom = scene_top + scene_h
    horizon_y = scene_top + scene_h * 0.62

    # Sky
    canvas.create_rectangle(scene_left, scene_top, scene_right, horizon_y,
                            fill="#dce7ee", outline="")
    # Ground
    canvas.create_rectangle(scene_left, horizon_y, scene_right, scene_bottom,
                            fill="#a8b09a", outline="")
    # Horizon line
    canvas.create_line(scene_left, horizon_y, scene_right, horizon_y,
                       fill="#7a8873")
    # Scene border
    canvas.create_rectangle(scene_left, scene_top, scene_right, scene_bottom,
                            outline="#999", width=1)

    # Distant reference marks — spread across the wide scene
    for frac in (0.1, 0.22, 0.36, 0.64, 0.78, 0.9):
        x = scene_left + frac * scene_w
        canvas.create_line(x, horizon_y, x, horizon_y - 5, fill="#5a6a52")
        if frac in (0.1, 0.36, 0.64, 0.9):
            canvas.create_oval(x - 2, horizon_y - 9, x + 2, horizon_y - 5,
                               fill="#5a6a52", outline="")

    # --- Person silhouette: fixed size, centered on horizon.
    cx = (scene_left + scene_right) / 2
    person_h = scene_h * 0.42
    py_feet = horizon_y
    py_head_top = horizon_y - person_h
    head_r = max(2.0, person_h * 0.10)
    py_head_center = py_head_top + head_r
    py_torso_end = py_head_center + person_h * 0.42

    canvas.create_oval(
        cx - head_r, py_head_center - head_r,
        cx + head_r, py_head_center + head_r,
        fill="#2a2a2a", outline="",
    )
    canvas.create_line(cx, py_head_center + head_r, cx, py_torso_end,
                       fill="#2a2a2a", width=2)
    canvas.create_line(cx, py_head_center + head_r + 2,
                       cx - person_h * 0.16, py_head_center + head_r + person_h * 0.22,
                       fill="#2a2a2a")
    canvas.create_line(cx, py_head_center + head_r + 2,
                       cx + person_h * 0.16, py_head_center + head_r + person_h * 0.22,
                       fill="#2a2a2a")
    canvas.create_line(cx, py_torso_end, cx - person_h * 0.14, py_feet,
                       fill="#2a2a2a")
    canvas.create_line(cx, py_torso_end, cx + person_h * 0.14, py_feet,
                       fill="#2a2a2a")

    # --- Compute pan offset for the PREDICTED frame only. The current frame
    #     always stays centered — it represents "how wide/narrow is my
    #     current framing", not "where was the camera actually pointed" (the
    #     footage's raw absolute pan isn't relevant to that question and was
    #     confusingly shifting the reference frame off-center).
    #     Pan values in .insproj files are in RADIANS; the UI field is in
    #     DEGREES. We map full scene width = 2π radians of pan delta.
    pan_delta_rad = 0.0
    if parameter_enabled["pan"].get():
        try:
            pan_delta_rad = math.radians(float(parameter_values["pan"].get().strip()))
            pan_mode = parameter_modes["pan"].get()
            if pan_mode == "set":
                # "Set" replaces the value outright — there's no single
                # "delta" from an average, so we don't shift the preview
                # (it would require picking a reference we don't have).
                pan_delta_rad = 0.0
        except ValueError:
            pan_delta_rad = 0.0

    def pan_to_offset(pan_radians):
        return (pan_radians / (2 * math.pi)) * scene_w

    current_pan_offset = 0.0
    predicted_pan_offset = pan_to_offset(pan_delta_rad)

    # --- FOV frames: current is a FIXED REFERENCE (never scales), predicted is
    #     scaled *relative to current* by the FOV ratio. So the current frame
    #     stays put and the predicted frame grows/shrinks by exactly the
    #     multiplier you dialed in — same intuition as scrubbing a slider.
    # Reference size for "current" is anchored to the PERSON'S HEIGHT (with a
    # small margin) rather than a fixed fraction of scene width. This way the
    # current frame always nicely bounds the full silhouette regardless of
    # which aspect ratio this tab uses — a wide (16:9) source aspect
    # naturally becomes a WIDE-and-just-tall-enough box, a narrow (9:16)
    # source aspect becomes a NARROW-and-tall box. Without this, a fixed
    # reference width made wide-aspect tabs render a frame too short to
    # contain the person.
    PERSON_FIT_MARGIN = 1.18  # a little headroom/footroom around the figure
    person_total_h = py_feet - py_head_top
    ref_h = person_total_h * PERSON_FIT_MARGIN
    ref_w = ref_h * source_aspect
    center_y = (py_head_top + py_feet) / 2

    def compute_half_dims(fov, aspect):
        if current_avg == 0:
            return 0, 0
        ratio = fov / current_avg
        frame_w = ref_w * ratio
        frame_h = frame_w / aspect
        return frame_w / 2, frame_h / 2

    def draw_frame(fov, aspect, x_offset, color, dash=None, line_width=2):
        hw, hh = compute_half_dims(fov, aspect)
        # No per-side clamp: the frame is always geometrically centered on
        # (cx + x_offset, center_y). The Tk canvas will clip anything outside
        # the widget by itself.
        x_center = cx + x_offset
        x1 = x_center - hw
        y1 = center_y - hh
        x2 = x_center + hw
        y2 = center_y + hh
        kwargs = {"fill": "", "outline": color, "width": line_width}
        if dash:
            kwargs["dash"] = dash
        canvas.create_rectangle(x1, y1, x2, y2, **kwargs)

    # Current: fixed reference size, solid grey, always centered
    draw_frame(current_avg, source_aspect, current_pan_offset, "#333", line_width=3)

    # Predicted: scaled + shifted by the pan adjustment delta, dashed orange.
    # Shown whenever FOV or Pan is enabled — even if the resulting value
    # happens to equal current (e.g. Scale ×1) — so the frame doesn't
    # disappear just because the math currently nets out to "no change".
    show_predicted = parameter_enabled["fov"].get() or parameter_enabled["pan"].get()
    if show_predicted:
        draw_frame(predicted_avg, target_aspect, predicted_pan_offset,
                   "#e67e22", dash=(5, 3), line_width=2)

    # Labels above scene
    label_y = label_top / 2
    canvas.create_text(scene_left, label_y,
                       text=f"current {current_avg:.2f}",
                       anchor="w", fill="#222", font=("TkDefaultFont", 9, "bold"))
    if show_predicted:
        ratio = predicted_avg / current_avg if current_avg != 0 else 0
        label = f"predicted {predicted_avg:.2f}  (×{ratio:.2f})"
        canvas.create_text(scene_right, label_y,
                           text=label,
                           anchor="e", fill="#e67e22", font=("TkDefaultFont", 9, "bold"))

    # Bottom hint
    canvas.create_text(
        width / 2, height - label_bottom / 2,
        text="tighter ← → wider     ·     pan shifts left/right",
        fill="#777", font=("TkDefaultFont", 8, "italic"),
    )


def redraw_preview():
    global _preview_after_id
    _preview_after_id = None
    canvas = preview_canvas
    canvas.delete("all")
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    if width < 20 or height < 20:
        # Canvas not laid out yet — retry once
        canvas.after(80, redraw_preview)
        return

    name = preview_param_var.get()
    current = list(current_series.get(name, []))
    if not current:
        canvas.create_text(
            width / 2, height / 2,
            text=(f"No '{PARAM_CONFIG[name]['label']}' keyframes in this project"
                  if any(current_series.values())
                  else "Load a project to see the preview"),
            fill="#999",
        )
        return

    is_angular = name in ("pan", "tilt", "roll")

    # Compute predicted series (in the file's native units — radians for
    # angular params) using the raw current values.
    predicted = list(current)
    if parameter_enabled[name].get():
        try:
            raw_value = float(parameter_values[name].get().strip())
            value = math.radians(raw_value) if is_angular else raw_value
            mode = parameter_modes[name].get()
            predicted = [modify_parameter(v, mode, value) for v in current]
        except ValueError:
            pass  # keep predicted == current on bad input

    # For angular params, display in degrees (the UI's unit) rather than
    # the file's raw radians.
    if is_angular:
        current = [math.degrees(v) for v in current]
        predicted = [math.degrees(v) for v in predicted]

    # Y range across both series (with a small margin)
    all_vals = current + predicted
    y_min = min(all_vals)
    y_max = max(all_vals)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    span = y_max - y_min
    y_min -= span * 0.08
    y_max += span * 0.08

    pad_l, pad_r, pad_t, pad_b = 46, 12, 8, 22
    plot_w = max(1, width - pad_l - pad_r)
    plot_h = max(1, height - pad_t - pad_b)

    def to_x(i):
        n = max(1, len(current) - 1)
        return pad_l + (i / n) * plot_w

    def to_y(v):
        return pad_t + (1 - (v - y_min) / (y_max - y_min)) * plot_h

    # Axes
    canvas.create_line(pad_l, pad_t, pad_l, pad_t + plot_h, fill="#bbb")
    canvas.create_line(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h, fill="#bbb")

    # Horizontal gridlines at 25/50/75%
    for frac in (0.25, 0.5, 0.75):
        y = pad_t + frac * plot_h
        canvas.create_line(pad_l, y, pad_l + plot_w, y, fill="#eee", dash=(2, 2))

    # Y-axis labels (min, mid, max)
    def fmt(v):
        av = abs(v)
        if av >= 100:
            return f"{v:.0f}"
        if av >= 10:
            return f"{v:.1f}"
        return f"{v:.2f}"
    canvas.create_text(pad_l - 4, pad_t, text=fmt(y_max), anchor="e", fill="#666", font=("TkDefaultFont", 8))
    canvas.create_text(pad_l - 4, pad_t + plot_h, text=fmt(y_min), anchor="e", fill="#666", font=("TkDefaultFont", 8))
    canvas.create_text(pad_l - 4, pad_t + plot_h / 2, text=fmt((y_min + y_max) / 2), anchor="e", fill="#666", font=("TkDefaultFont", 8))

    # X-axis labels: first, last, and center
    canvas.create_text(pad_l, pad_t + plot_h + 3, text="1", anchor="n", fill="#666", font=("TkDefaultFont", 8))
    canvas.create_text(pad_l + plot_w, pad_t + plot_h + 3, text=str(len(current)), anchor="n", fill="#666", font=("TkDefaultFont", 8))
    canvas.create_text(pad_l + plot_w / 2, pad_t + plot_h + 12,
                       text=f"{PARAM_CONFIG[name]['label']}  —  timeline of .insproj keyframes",
                       anchor="n", fill="#999", font=("TkDefaultFont", 8))

    def draw_series(values, color):
        pts = [(to_x(i), to_y(v)) for i, v in enumerate(values)]
        if len(pts) >= 2:
            flat = [coord for p in pts for coord in p]
            canvas.create_line(*flat, fill=color, width=2)
        radius = 2 if len(pts) > 30 else 3
        for x, y in pts:
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="")

    # Current in grey
    draw_series(current, "#888")

    # Predicted in orange — only if actually different
    if any(abs(c - p) > 1e-9 for c, p in zip(current, predicted)):
        draw_series(predicted, "#e67e22")


# Wire up live updates
preview_canvas.bind("<Configure>", schedule_preview_redraw)
for _c in fov_scene_canvases:
    _c.bind("<Configure>", schedule_preview_redraw)
fov_scene_notebook.bind("<<NotebookTabChanged>>", schedule_preview_redraw)
preview_param_var.trace_add("write", schedule_preview_redraw)
for _name in SUPPORTED_PARAMS:
    parameter_enabled[_name].trace_add("write", schedule_preview_redraw)
    parameter_modes[_name].trace_add("write", schedule_preview_redraw)
    parameter_values[_name].trace_add("write", schedule_preview_redraw)

refresh_recent()
refresh_presets()
clear_scan_display()

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    open_project(sys.argv[1])
elif cfg["recent"] and os.path.exists(cfg["recent"][0]):
    open_project(cfg["recent"][0])

root.mainloop()