#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

CFG = os.path.expanduser("~/.insta360_project_tools.json")
SUPPORTED_PARAMS = ("fov", "pan", "tilt", "roll", "distance")
PARAM_CONFIG = {
    "fov": {
        "label": "FOV",
        "modes": (("scale", "Scale"), ("set", "Set")),
        "default": "0",
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
        "default": "0",
        "slider": {"from": 0.0, "to": 3.0, "resolution": 0.01},
    },
}


def is_numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_cfg():
    if os.path.exists(CFG):
        try:
            with open(CFG, "r", encoding="utf-8") as file_obj:
                return json.load(file_obj)
        except Exception:
            pass
    return {"recent": []}


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


def format_range_text(stats):
    if stats["min"] is None:
        return "Not present"
    return f"{stats['min']} / {stats['max']}"


def update_scan_display(scan_result):
    keyframe_count_var.set(str(scan_result["keyframe_count"]))
    for name in SUPPORTED_PARAMS:
        range_vars[name].set(format_range_text(scan_result["ranges"][name]))
    unsupported = scan_result["unsupported"]
    unsupported_var.set(", ".join(unsupported) if unsupported else "None")


def clear_scan_display():
    keyframe_count_var.set("0")
    for name in SUPPORTED_PARAMS:
        range_vars[name].set("Not present")
    unsupported_var.set("None")


def remember(path):
    path = os.path.abspath(path)
    recent = [item for item in cfg["recent"] if item != path]
    recent.insert(0, path)
    cfg["recent"] = recent[:10]
    save_cfg()
    refresh_recent()


def refresh_recent():
    menu["menu"].delete(0, "end")
    if not cfg["recent"]:
        menu["menu"].add_command(label="(empty)")
        return
    for path in cfg["recent"]:
        menu["menu"].add_command(
            label=os.path.basename(path),
            command=lambda selected_path=path: open_project(selected_path),
        )


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
    update_scan_display(scan_project(data))


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


def get_parameter_settings():
    settings = {}
    for name in SUPPORTED_PARAMS:
        try:
            settings[name] = {
                "enabled": parameter_enabled[name].get(),
                "mode": parameter_modes[name].get(),
                "value": float(parameter_values[name].get().strip()),
            }
        except ValueError:
            label = PARAM_CONFIG[name]["label"]
            raise ValueError(f"{label}: enter a valid number.")
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


cfg = load_cfg()
root = tk.Tk()
root.title("Insta360 Project Tools")
root.geometry("860x540")
root.minsize(780, 500)

selected = tk.StringVar()
overwrite = tk.BooleanVar(value=True)
recent_var = tk.StringVar(value="Recent")
keyframe_count_var = tk.StringVar(value="0")
range_vars = {name: tk.StringVar(value="Not present") for name in SUPPORTED_PARAMS}
unsupported_var = tk.StringVar(value="None")
parameter_enabled = {}
parameter_modes = {}
parameter_values = {}
parameter_sliders = {}

main = ttk.Frame(root, padding=12)
main.pack(fill="both", expand=True)
main.columnconfigure(0, weight=3)
main.columnconfigure(1, weight=2)

ttk.Label(main, text="Project").grid(row=0, column=0, sticky="w")
ttk.Label(
    main,
    text="Load an .insproj project file from the project folder to batch-change keyframe values.",
    justify="left",
).grid(row=0, column=1, sticky="w")
project_row = ttk.Frame(main)
project_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))
project_row.columnconfigure(0, weight=1)

ttk.Entry(project_row, textvariable=selected).grid(row=0, column=0, sticky="ew")
ttk.Button(project_row, text="Browse", command=browse).grid(row=0, column=1, padx=(6, 0))
ttk.Button(project_row, text="Reveal", command=reveal).grid(row=0, column=2, padx=(6, 0))
menu = tk.OptionMenu(project_row, recent_var, "")
menu.grid(row=0, column=3, padx=(6, 0))
refresh_recent()

stats_frame = ttk.LabelFrame(main, text="Project Analysis", padding=8)
stats_frame.grid(row=2, column=0, sticky="new", padx=(0, 8))
stats_frame.columnconfigure(1, weight=1)
stats_frame.columnconfigure(3, weight=1)

ttk.Label(stats_frame, text="Keyframes").grid(row=0, column=0, sticky="w", padx=(0, 8))
ttk.Label(stats_frame, textvariable=keyframe_count_var).grid(row=0, column=1, sticky="w")

stats_layout = [
    ("fov", "FOV min/max", 1, 0),
    ("pan", "Pan min/max", 1, 2),
    ("tilt", "Tilt min/max", 2, 0),
    ("roll", "Roll min/max", 2, 2),
    ("distance", "Distance min/max", 3, 0),
]
for name, label_text, row_index, column_index in stats_layout:
    ttk.Label(stats_frame, text=label_text).grid(
        row=row_index,
        column=column_index,
        sticky="w",
        padx=(0, 8),
        pady=(6, 0),
    )
    ttk.Label(stats_frame, textvariable=range_vars[name]).grid(
        row=row_index,
        column=column_index + 1,
        sticky="w",
        pady=(6, 0),
    )

ttk.Separator(stats_frame, orient="horizontal").grid(
    row=4, column=0, columnspan=4, sticky="ew", pady=(8, 6)
)
ttk.Label(stats_frame, text="Unsupported").grid(row=5, column=0, sticky="nw", padx=(0, 8))
ttk.Label(
    stats_frame,
    textvariable=unsupported_var,
    wraplength=500,
    justify="left",
).grid(row=5, column=1, columnspan=3, sticky="w")

controls = ttk.LabelFrame(main, text="Adjustments", padding=8)
controls.grid(row=2, column=1, rowspan=4, sticky="nsew")
controls.columnconfigure(0, weight=1)
controls.columnconfigure(1, weight=1)


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

for index, name in enumerate(SUPPORTED_PARAMS):
    config = PARAM_CONFIG[name]
    slider_cfg = config["slider"]
    frame = ttk.Frame(controls, padding=6)
    frame.grid(row=index, column=0, columnspan=2, sticky="ew", pady=2)
    frame.columnconfigure(1, weight=1)
    parameter_enabled[name] = tk.BooleanVar(value=False)
    parameter_modes[name] = tk.StringVar(value=config["modes"][0][0])
    parameter_values[name] = tk.StringVar(value=config["default"])
    ttk.Checkbutton(
        frame,
        text=config["label"],
        variable=parameter_enabled[name],
    ).grid(row=0, column=0, sticky="w")

    mode_frame = ttk.Frame(frame)
    mode_frame.grid(row=0, column=1, sticky="e")
    for mode_name, label_text in config["modes"]:
        ttk.Radiobutton(
            mode_frame,
            text=label_text,
            value=mode_name,
            variable=parameter_modes[name],
        ).pack(side="left", padx=(0, 6))

    parameter_sliders[name] = tk.Scale(
        frame,
        from_=slider_cfg["from"],
        to=slider_cfg["to"],
        resolution=slider_cfg["resolution"],
        orient="horizontal",
        showvalue=False,
        command=make_slider_handler(name, slider_cfg["resolution"]),
    )
    parameter_sliders[name].set(float(config["default"]))
    parameter_sliders[name].grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    value_row = ttk.Frame(frame)
    value_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0))
    value_row.columnconfigure(1, weight=1)
    ttk.Label(value_row, text="Value").grid(row=0, column=0, sticky="w", padx=(0, 6))
    entry = ttk.Entry(value_row, textvariable=parameter_values[name], width=8)
    entry.grid(row=0, column=1, sticky="w")
    entry.bind("<FocusOut>", lambda _event, selected_name=name: sync_slider_from_entry(selected_name))
    entry.bind("<Return>", lambda _event, selected_name=name: sync_slider_from_entry(selected_name))

ttk.Checkbutton(
    main,
    text="Overwrite original (backup once)",
    variable=overwrite,
).grid(row=6, column=0, sticky="w", pady=(10, 0))

ttk.Button(main, text="Apply", command=process).grid(
    row=6, column=1, sticky="e", pady=(10, 0)
)

clear_scan_display()

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    open_project(sys.argv[1])
elif cfg["recent"]:
    selected.set(cfg["recent"][0])
    if os.path.exists(cfg["recent"][0]):
        open_project(cfg["recent"][0])

root.mainloop()
