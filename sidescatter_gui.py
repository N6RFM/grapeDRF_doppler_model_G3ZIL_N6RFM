#!/usr/bin/env python3
"""
sidescatter_gui.py - a window for the two-hop sidescatter tools of
G3ZIL's grapeDRF_doppler_model (SS_sidescatter.sh, SS_sidescatter_plot.py,
SS_animate.sh).

It reads and writes the same config/<CALL>_config.ini files as grape_gui.py
(the Doppler / synthetic-spectrogram window), so a station set up in one is
ready in the other. All the modelling is done by G3ZIL's scripts; this window
only sets their inputs, runs them, and shows where the results went.

Place it in the project root next to grape_gui.py and run:

    python3 sidescatter_gui.py            (or press "Two-hop sidescatter..." in grape_gui.py)

User interface written with Claude (Anthropic).
"""
import ast
import configparser
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Shared helpers and settings (Python choice, config folder) come from grape_gui.py
import grape_gui as gg

BASE_DIR = gg.BASE_DIR
CONFIG_DIR = gg.CONFIG_DIR

SCRIPTS = ("SS_sidescatter.sh", "SS_sidescatter.py", "SS_sidescatter_plot.py")
MAX_LAT = 58.0          # upstream limit: the northernmost station must be below 58 N

# (section, key, label, width, kind)
PARAMS = [
    ("settings", "freq", "Frequency (MHz)", 8, "float"),
    ("settings", "r12", "R12 (sunspot no.)", 8, "int"),
    ("settings", "nhops", "Hops", 8, "int"),
    ("settings", "elev_start", "Elevation start (deg)", 8, "float"),
    ("settings", "elev_stop", "Elevation stop (deg)", 8, "float"),
    ("settings", "tx_grid", "Transmitter grid", 10, "grid"),
    ("settings", "rx_grid", "Receiver grid", 10, "grid"),
    ("3d_sidescatter", "ray_inc", "Azimuth step (deg)", 8, "float"),
    ("3d_sidescatter", "contour_max", "Metric contour max", 8, "float"),
]
RESULT_KEYS = [("settings", "distance", "Path length (km)"), ("settings", "bearing", "Bearing (deg)"),
               ("3d_sidescatter", "max_metric", "Peak metric"),
               ("3d_sidescatter", "metric_max_lat", "Peak latitude"),
               ("3d_sidescatter", "metric_max_lon", "Peak longitude")]


# ----------------------------------------------------------------------
# PURE HELPERS
# ----------------------------------------------------------------------
def grid_to_latlon(grid):
    """Centre of a 4- or 6-character Maidenhead square as (lat, lon)."""
    g = grid.strip().upper()
    if len(g) not in (4, 6) or not re.fullmatch(r"[A-R]{2}\d{2}([A-X]{2})?", g):
        raise ValueError(f"'{grid}' is not a 4- or 6-character Maidenhead locator")
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        lon += (ord(g[4]) - 65) * (2 / 24) + (1 / 24)
        lat += (ord(g[5]) - 65) * (1 / 24) + (1 / 48)
    else:
        lon += 1
        lat += 0.5
    return lat, lon


def read_cfg(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read(path)
    return cp


def cfg_get(cp, section, key, default=""):
    try:
        return cp.get(section, key).strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


def parse_ut(text):
    v = ast.literal_eval(text)
    if len(v) != 5:
        raise ValueError("ut needs 5 values")
    return tuple(int(x) for x in v)


def same_value(a, b):
    try:
        return float(a) == float(b)
    except ValueError:
        return a.strip().upper() == b.strip().upper()


def cfg_set(path, section, updates):
    """Change keys in one section of an ini file line by line, so comments and layout
    elsewhere are kept. Missing keys are added to the section; a missing section is appended."""
    with open(path) as f:
        lines = f.read().splitlines()
    head = re.compile(r"^\s*\[\s*" + re.escape(section) + r"\s*\]", re.I)
    any_head = re.compile(r"^\s*\[")
    start = next((i for i, l in enumerate(lines) if head.match(l)), None)
    if start is None:
        lines += ["", f"[{section}]"] + [f"{k} = {v}" for k, v in updates.items()]
    else:
        end = next((i for i in range(start + 1, len(lines)) if any_head.match(lines[i])), len(lines))
        for k, v in updates.items():
            pat = re.compile(r"^\s*" + re.escape(k) + r"\s*[=:]", re.I)
            hit = next((i for i in range(start + 1, end) if pat.match(lines[i])), None)
            if hit is not None:
                lines[hit] = f"{k} = {v}"
            else:
                at = end
                while at > start + 1 and not lines[at - 1].strip():
                    at -= 1
                lines.insert(at, f"{k} = {v}")
                end += 1
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def station_call(cfg_name):
    """The callsign the upstream scripts use for their output folders."""
    return cfg_name.split("_")[0]


def stamp(ut):
    y, mo, d, h, mi = ut
    return f"{y:04d}{mo:02d}{d:02d}{h:02d}{mi:02d}"


def describe_result(rel):
    n = os.path.basename(rel)
    if n == "sidescatter.png":
        return "Map of ray landing spots (transmitter and receiver)"
    if n.startswith("2F_sidescatter_metric_") and n.endswith(".png"):
        return "Sidescatter likelihood map"
    if n.endswith(".mp4"):
        return "Animation"
    if n.endswith("_ground_coords.csv"):
        return "Data: ray landing coordinates"
    if n.endswith("_FF_metric.csv"):
        return "Data: metric grid"
    if n.endswith("_metrics.csv"):
        return "Data: peak position and value per time"
    return ""


def result_order(rel):
    n = rel.lower()
    return (0 if n.endswith((".png", ".mp4")) else 1, rel)


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class SSApp(tk.Tk):
    def __init__(self, preselect=None):
        super().__init__()
        self.title("Two-hop sidescatter")
        self.geometry("980x840")
        self.minsize(820, 640)
        self.settings = gg.load_settings()
        self.q = queue.Queue()
        self.proc = None
        self.cancel_flag = threading.Event()
        self.busy = False
        self.t0 = None
        self.cfg = None
        self.vars = {}
        self.ut_vars = [tk.StringVar() for _ in range(5)]
        self.result_vars = {}
        self._build()
        self.refresh_configs(preselect)
        self.show_saved_results()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        self.after(1000, self._tick)
        self.log(f"Project folder: {BASE_DIR}")
        self.log(f"Python: {self.py_var.get()}")
        missing = [s for s in SCRIPTS + ("SS_animate.sh",) if not os.path.isfile(os.path.join(BASE_DIR, s))]
        if missing:
            self.log("WARNING: not found in the project folder: " + ", ".join(missing) +
                     ". Pull them from upstream (git fetch upstream; git merge upstream/main).")

    # ---------- layout ----------
    def _build(self):
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")
        vbar = ttk.Scrollbar(self, orient="vertical")
        vbar.pack(side="right", fill="y")
        canvas = tk.Canvas(self, highlightthickness=0, yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.configure(command=canvas.yview)
        main = ttk.Frame(canvas, padding=8)
        win = canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

        # 1. station config
        f1 = ttk.LabelFrame(main, text="1. Station config (shared with the Doppler window)", padding=8)
        f1.pack(fill="x")
        r = ttk.Frame(f1)
        r.pack(fill="x")
        ttk.Label(r, text="Config:").pack(side="left")
        self.config_var = tk.StringVar()
        self.config_box = ttk.Combobox(r, textvariable=self.config_var, state="readonly", width=28)
        self.config_box.pack(side="left", padx=6)
        self.config_box.bind("<<ComboboxSelected>>", lambda e: self.load_cfg())
        ttk.Button(r, text="Reload from file", command=self.load_cfg).pack(side="left")
        self.station_var = tk.StringVar()
        ttk.Label(f1, textvariable=self.station_var, foreground="#1a5fb4",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(6, 0))

        # 2. inputs
        f2 = ttk.LabelFrame(main, text="2. Model inputs", padding=8)
        f2.pack(fill="x", pady=(8, 0))
        g = ttk.Frame(f2)
        g.pack(fill="x")
        ttk.Label(g, text="UT (y m d h m):").grid(row=0, column=0, sticky="w")
        ut_row = ttk.Frame(g)
        ut_row.grid(row=0, column=1, columnspan=5, sticky="w", padx=6)
        for i, (v, w) in enumerate(zip(self.ut_vars, (6, 4, 4, 4, 4))):
            ttk.Entry(ut_row, textvariable=v, width=w, justify="center").pack(side="left", padx=2)
        self.stamp_var = tk.StringVar()
        ttk.Label(ut_row, textvariable=self.stamp_var, foreground="gray40").pack(side="left", padx=10)
        for v in self.ut_vars:
            v.trace_add("write", lambda *a: self._update_stamp())
        for i, (sec, key, label, width, kind) in enumerate(PARAMS):
            row, col = 1 + i // 3, (i % 3) * 2
            ttk.Label(g, text=label + ":").grid(row=row, column=col, sticky="w", pady=3, padx=(0, 4))
            v = tk.StringVar()
            self.vars[(sec, key)] = v
            ttk.Entry(g, textvariable=v, width=width).grid(row=row, column=col + 1, sticky="w", padx=(0, 18))
        ttk.Label(f2, foreground="gray40", wraplength=900, justify="left",
                  text="These are the same entries the Doppler window uses. Changing one here changes it for both. "
                       "Upstream limits: Northern Hemisphere only, and the northernmost station must be below 58 N."
                  ).pack(anchor="w", pady=(6, 0))

        # 3. run
        f3 = ttk.LabelFrame(main, text="3. Run", padding=8)
        f3.pack(fill="x", pady=(8, 0))
        m = ttk.Frame(f3)
        m.pack(fill="x")
        self.mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(m, text="One time (the UT above)", variable=self.mode_var, value="single",
                        command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(m, text="Animation over time", variable=self.mode_var, value="anim",
                        command=self._mode_changed).pack(side="left", padx=14)
        self.anim_frame = ttk.Frame(m)
        self.anim_frame.pack(side="left")
        self.total_var = tk.StringVar(value="360")
        self.step_var = tk.StringVar(value="20")
        ttk.Label(self.anim_frame, text="total min").pack(side="left")
        ttk.Entry(self.anim_frame, textvariable=self.total_var, width=6).pack(side="left", padx=(2, 8))
        ttk.Label(self.anim_frame, text="every min").pack(side="left")
        ttk.Entry(self.anim_frame, textvariable=self.step_var, width=5).pack(side="left", padx=2)
        self.est_var = tk.StringVar()
        ttk.Label(f3, textvariable=self.est_var, foreground="#b36b00", wraplength=900,
                  justify="left").pack(anchor="w", pady=(6, 0))
        for v in (self.total_var, self.step_var, self.mode_var):
            v.trace_add("write", lambda *a: self._mode_changed())

        p = ttk.Frame(f3)
        p.pack(fill="x", pady=(8, 0))
        ttk.Label(p, text="Python (venv):").pack(side="left")
        self.py_var = tk.StringVar(value=gg.detect_python())
        ttk.Entry(p, textvariable=self.py_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(p, text="Browse...", command=self.on_browse_python).pack(side="left")
        ttk.Button(p, text="Check setup", command=self.on_check).pack(side="left", padx=(6, 0))

        self.tree = ttk.Treeview(f3, columns=("status", "time"), height=2)
        self.tree.heading("#0", text="Step")
        self.tree.heading("status", text="Status")
        self.tree.heading("time", text="Elapsed")
        self.tree.column("#0", width=380)
        self.tree.column("status", width=200)
        self.tree.column("time", width=100, anchor="e")
        self.tree.pack(fill="x", pady=(8, 0))

        b = ttk.Frame(f3)
        b.pack(fill="x", pady=(8, 0))
        self.btn_run = ttk.Button(b, text="Run sidescatter", command=self.on_run)
        self.btn_run.pack(side="left")
        self.btn_cancel = ttk.Button(b, text="Cancel", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=6)
        ttk.Button(b, text="Open results folder", command=self.on_open_folder).pack(side="right")

        # 4. results (always visible, not a pop-up)
        f4 = ttk.LabelFrame(main, text="4. Results of the last run (double-click to open)", padding=8)
        f4.pack(fill="x", pady=(8, 0))
        self.result_head = tk.StringVar(value="No run yet.")
        ttk.Label(f4, textvariable=self.result_head, foreground="#1a5fb4").pack(anchor="w")
        self.peak_var = tk.StringVar()
        ttk.Label(f4, textvariable=self.peak_var, foreground="gray25", wraplength=900,
                  justify="left").pack(anchor="w", pady=(2, 4))
        self.rtree = ttk.Treeview(f4, columns=("what",), height=5)
        self.rtree.heading("#0", text="File")
        self.rtree.heading("what", text="What it is")
        self.rtree.column("#0", width=470)
        self.rtree.column("what", width=380)
        self.rtree.pack(fill="x")
        self.rtree.bind("<Double-1>", lambda e: self.on_open_selected())
        self.rtree.bind("<Return>", lambda e: self.on_open_selected())
        ttk.Button(f4, text="Open selected", command=self.on_open_selected).pack(anchor="e", pady=(6, 0))

        # console
        f5 = ttk.Frame(main)
        f5.pack(fill="both", expand=True, pady=(8, 4))
        hdr = ttk.Frame(f5)
        hdr.pack(fill="x", pady=(0, 4))
        ttk.Label(hdr, text="Output:").pack(side="left")
        ttk.Button(hdr, text="Clear", command=self._clear_log).pack(side="right")
        ttk.Button(hdr, text="Copy", command=self._copy_best).pack(side="right", padx=8)
        ttk.Button(hdr, text="Save to file...", command=self._save_log).pack(side="right")
        self.log_box = scrolledtext.ScrolledText(
            f5, height=12, state="disabled", wrap="none", bg="#111111", fg="#e6e6e6",
            insertbackground="#e6e6e6", selectbackground="#3d6fb4", selectforeground="#ffffff",
            relief="flat", font=("TkFixedFont", 10))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.bind("<Button-1>", lambda e: self.log_box.focus_set())
        self.log_box.bind("<Control-c>", lambda e: (self._copy_best(), "break")[1])
        self.log_box.bind("<Control-a>", lambda e: (self._select_all(), "break")[1])
        self._mode_changed()

    # ---------- thread-safe plumbing ----------
    def log(self, text):
        self.q.put(("log", text))

    def post(self, fn):
        self.q.put(("do", fn))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                else:
                    payload()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _tick(self):
        if self.busy and self.t0:
            self.status_var.set(f"Running ... {gg.fmt_elapsed(time.time() - self.t0)}")
        self.after(1000, self._tick)

    def _append_log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _select_all(self):
        self.log_box.tag_add("sel", "1.0", "end-1c")

    def _copy_best(self):
        try:
            text = self.log_box.get("sel.first", "sel.last")
        except tk.TclError:
            text = self.log_box.get("1.0", "end-1c")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            title="Save log", defaultextension=".txt", initialdir=BASE_DIR,
            initialfile=f"sidescatter_log_{datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            try:
                with open(path, "w") as f:
                    f.write(self.log_box.get("1.0", "end-1c") + "\n")
            except OSError as e:
                messagebox.showerror("Save failed", str(e))

    def _set_busy(self, busy):
        self.busy = busy
        self.btn_run.configure(state="disabled" if busy else "normal")
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        if not busy:
            self.status_var.set("Ready")

    # ---------- config ----------
    def refresh_configs(self, select=None):
        names = gg.list_configs()
        self.config_box["values"] = names
        if not names:
            self.station_var.set(f"No *_config.ini files in {CONFIG_DIR}")
            return
        want = select if select in names else (self.settings.get("ss_config") if self.settings.get("ss_config") in names
                                               else (self.settings.get("config") if self.settings.get("config") in names
                                                     else names[0]))
        self.config_var.set(want)
        self.load_cfg()

    def cfg_path(self):
        return os.path.join(CONFIG_DIR, self.config_var.get())

    def load_cfg(self):
        name = self.config_var.get()
        if not name:
            return
        try:
            cp = read_cfg(self.cfg_path())
            ut = parse_ut(cfg_get(cp, "settings", "ut"))
        except Exception as e:
            self.station_var.set(f"Could not read {name}: {e}")
            return
        self.cfg = cp
        for v, x in zip(self.ut_vars, ut):
            v.set(str(x))
        for (sec, key), v in self.vars.items():
            v.set(cfg_get(cp, sec, key))
        tx, rx = cfg_get(cp, "metadata", "tx", "?"), cfg_get(cp, "metadata", "rx", "?")
        self.station_var.set(f"{tx} ({cfg_get(cp, 'settings', 'tx_grid')})  to  "
                             f"{rx} ({cfg_get(cp, 'settings', 'rx_grid')})")
        if not cp.has_section("3d_sidescatter"):
            self.log(f"Note: {name} has no [3d_sidescatter] section; it will be added with the values above when you run.")
        self.show_config_results()
        self._update_stamp()
        self.settings["ss_config"] = name
        gg.save_settings(self.settings)

    def _update_stamp(self):
        try:
            self.stamp_var.set("-> file time " + stamp(tuple(int(v.get()) for v in self.ut_vars)))
        except ValueError:
            self.stamp_var.set("")

    def _mode_changed(self):
        anim = self.mode_var.get() == "anim"
        for w in self.anim_frame.winfo_children():
            w.configure(state="normal" if anim else "disabled")
        if not anim:
            self.est_var.set("Ray tracing every azimuth takes several minutes for one time.")
            return
        try:
            n = int(self.total_var.get()) // int(self.step_var.get())
            self.est_var.set(f"About {n} frames; each takes several minutes, so this can run for hours. "
                             f"Needs ffmpeg for the MP4. The config's UT is changed during the run and restored after.")
        except (ValueError, ZeroDivisionError):
            self.est_var.set("")

    def show_config_results(self):
        """Values the scripts write back into the config (path length, bearing, peak position)."""
        if not self.cfg:
            return
        bits = []
        for sec, key, label in RESULT_KEYS:
            val = cfg_get(self.cfg, sec, key)
            if val:
                bits.append(f"{label}: {val}")
        self.peak_var.set("In the config now: " + ";  ".join(bits) if bits else "")

    # ---------- python / setup ----------
    def on_browse_python(self):
        p = filedialog.askopenfilename(title="Python interpreter", initialdir=BASE_DIR)
        if p:
            self.py_var.set(p)
            self.settings["python"] = p
            gg.save_settings(self.settings)

    def env_problems(self, py, need_ffmpeg):
        """List of things that would make the scripts fail, found before the long run starts."""
        problems = []
        if not os.environ.get("PYTHONPATH"):
            problems.append("PYTHONPATH is not set in this environment. SS_sidescatter.py reads it to find PyLap and "
                            "stops with a KeyError otherwise. Start this window from the terminal where PyLap works.")
        try:
            r = subprocess.run(
                [py, "-c", "import importlib.util,sys\nm=[n for n in ('numpy','matplotlib','cartopy','maidenhead',"
                           "'geographiclib') if importlib.util.find_spec(n) is None]\nprint('MISSING', *m)"],
                capture_output=True, text=True, timeout=60)
            line = next((l for l in r.stdout.splitlines() if l.startswith("MISSING")), None)
            if line is None:
                problems.append("Could not run the chosen Python: " + (r.stderr.strip().splitlines() or ["no output"])[-1])
            elif line.split()[1:]:
                problems.append("This Python lacks: " + ", ".join(line.split()[1:]) + "  (pip install "
                                + " ".join(line.split()[1:]) + ")")
        except (OSError, subprocess.TimeoutExpired) as e:
            problems.append(f"Could not run {py}: {e}")
        if need_ffmpeg and not shutil.which("ffmpeg"):
            problems.append("ffmpeg is not installed (sudo apt install ffmpeg); the animation step needs it.")
        return problems

    def on_check(self):
        probs = self.env_problems(self.py_var.get(), True)
        if probs:
            for p in probs:
                self.log("Setup problem: " + p)
            messagebox.showwarning("Setup check", "\n\n".join(probs))
        else:
            self.log("Setup check: PYTHONPATH set, Python modules present, ffmpeg found.")
            messagebox.showinfo("Setup check", "Everything the scripts need was found.\n"
                                "(PyLap itself is located by the script at run time.)")

    # ---------- run ----------
    def _collect(self):
        """Validate the entries. Returns (ut, {section: {key: value}}) or raises ValueError."""
        try:
            ut = tuple(int(v.get()) for v in self.ut_vars)
            datetime(*ut)
        except (ValueError, TypeError):
            raise ValueError("UT must be five whole numbers: year month day hour minute (a real date).")
        out = {}
        for sec, key, label, _w, kind in PARAMS:
            val = self.vars[(sec, key)].get().strip()
            if not val:
                raise ValueError(f"{label} is empty.")
            try:
                if kind == "float":
                    float(val)
                elif kind == "int":
                    int(val)
                elif kind == "grid":
                    grid_to_latlon(val)
            except ValueError as e:
                raise ValueError(f"{label}: {e}" if kind == "grid" else f"{label} must be a number (got '{val}').")
            out.setdefault(sec, {})[key] = val.upper() if kind == "grid" else val
        lats = [grid_to_latlon(out["settings"][k])[0] for k in ("tx_grid", "rx_grid")]
        if min(lats) < 0:
            raise ValueError("Both stations must be in the Northern Hemisphere (upstream limitation).")
        if max(lats) >= MAX_LAT:
            raise ValueError(f"The northernmost station must be below {MAX_LAT:g} N (upstream limitation); "
                             f"yours is at {max(lats):.1f} N.")
        if float(out["settings"]["elev_start"]) >= float(out["settings"]["elev_stop"]):
            raise ValueError("Elevation start must be less than elevation stop.")
        return ut, out

    def on_run(self):
        if self.busy:
            return
        name = self.config_var.get()
        if not name:
            messagebox.showerror("No config", "Choose a station config first.")
            return
        missing = [s for s in SCRIPTS if not os.path.isfile(os.path.join(BASE_DIR, s))]
        anim = self.mode_var.get() == "anim"
        if anim and not os.path.isfile(os.path.join(BASE_DIR, "SS_animate.sh")):
            missing.append("SS_animate.sh")
        if missing:
            messagebox.showerror("Scripts missing", "Not found in the project folder: " + ", ".join(missing) +
                                 "\n\nPull them from upstream:\ngit fetch upstream\ngit merge upstream/main")
            return
        try:
            ut, values = self._collect()
            total = step = 0
            if anim:
                total, step = int(self.total_var.get()), int(self.step_var.get())
                if total <= 0 or step <= 0 or step > total:
                    raise ValueError("Animation: total and interval must be positive, interval not larger than total.")
        except ValueError as e:
            messagebox.showerror("Check the inputs", str(e))
            return
        py = self.py_var.get().strip()
        if not os.path.isfile(py):
            messagebox.showerror("Python not found", f"Not a file: {py}")
            return
        probs = self.env_problems(py, anim)
        if probs:
            for p in probs:
                self.log("Setup problem: " + p)
            messagebox.showerror("Cannot start", "\n\n".join(probs))
            return
        if anim and not messagebox.askyesno(
                "Long run", f"This makes about {total // step} frames and can take hours. Continue?"):
            return
        self.settings["python"] = py
        gg.save_settings(self.settings)
        self.cancel_flag.clear()
        self._set_busy(True)
        self.t0 = time.time()
        steps = [("anim", "Animation (SS_animate.sh)")] if anim else \
                [("trace", "Ray tracing (SS_sidescatter.sh)"), ("plot", "Plots (SS_sidescatter_plot.py)")]
        for it in self.tree.get_children():
            self.tree.delete(it)
        for k, label in steps:
            self.tree.insert("", "end", iid=k, text=label, values=("waiting", ""))
        self.tree.configure(height=len(steps))
        threading.Thread(target=self._worker, args=(name, py, ut, values, anim, total, step, [k for k, _ in steps]),
                         daemon=True).start()

    def _tree_set(self, key, status, elapsed=""):
        self.post(lambda: self.tree.item(key, values=(status, elapsed)))

    def _run_cmd(self, cmd, py):
        env = os.environ.copy()
        py_dir = os.path.dirname(py)
        venv_root = os.path.dirname(py_dir)
        if os.path.isfile(os.path.join(venv_root, "pyvenv.cfg")):
            env["VIRTUAL_ENV"] = venv_root
            env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        env["MPLBACKEND"] = "Agg"
        self.log("$ " + " ".join(cmd))
        self.proc = subprocess.Popen(cmd, cwd=BASE_DIR, env=env, text=True, bufsize=1,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        for line in self.proc.stdout:
            self.log(line.rstrip("\n"))
        rc = self.proc.wait()
        self.proc = None
        return rc

    def _rc_text(self, rc):
        if rc == 0:
            return "done"
        return "cancelled" if self.cancel_flag.is_set() else f"FAILED (exit {rc})"

    def _worker(self, name, py, ut, values, anim, total, step, step_keys):
        path = os.path.join(CONFIG_DIR, name)
        call = station_call(name)
        rel_cfg = "./config/" + name          # upstream derives the callsign from this exact form
        original_ut = None
        ok = False
        before = gg.snapshot_files()
        try:
            shutil.copy2(path, path + ".bak")
            cp = read_cfg(path)
            original_ut = cfg_get(cp, "settings", "ut")
            changed = []
            new_ut = f"[{ut[0]},{ut[1]},{ut[2]},{ut[3]},{ut[4]}]"
            if original_ut.replace(" ", "") != new_ut:
                changed.append(("settings", "ut", new_ut))
            for sec, kv in values.items():
                for k, v in kv.items():
                    if not same_value(cfg_get(cp, sec, k), v) or not cp.has_option(sec, k):
                        changed.append((sec, k, v))
            for sec in {c[0] for c in changed}:
                cfg_set(path, sec, {k: v for s, k, v in changed if s == sec})
            if changed:
                self.log("Config updated (previous copy: " + name + ".bak): "
                         + ", ".join(f"{k}={v}" for _s, k, v in changed))
            else:
                self.log(f"Config {name} already matches these inputs.")
            original_ut = new_ut
            ts = stamp(ut)
            first = True
            if anim:
                t = time.time()
                self._tree_set("anim", "running")
                rc = self._run_cmd(["bash", "./SS_animate.sh", name, str(total), str(step)], py)
                self._tree_set("anim", self._rc_text(rc), gg.fmt_elapsed(time.time() - t))
                ok = rc == 0
            else:
                t = time.time()
                self._tree_set("trace", "running")
                rc = self._run_cmd(["bash", "./SS_sidescatter.sh", name, ts], py)
                csv = os.path.join(BASE_DIR, "output", "csv", "SS", call, f"{ts}_ground_coords.csv")
                good = rc == 0 and os.path.isfile(csv) and os.path.getsize(csv) > 0
                self._tree_set("trace", "done" if good else
                               (self._rc_text(rc) if rc else "FAILED: no landing coordinates"),
                               gg.fmt_elapsed(time.time() - t))
                if not good and rc == 0:
                    self.log("The ray tracing finished but wrote no landing coordinates. Check the log above "
                             "for PyLap messages.")
                if good and not self.cancel_flag.is_set():
                    t = time.time()
                    self._tree_set("plot", "running")
                    rc = self._run_cmd([py, "SS_sidescatter_plot.py", rel_cfg, ts, "0"], py)
                    self._tree_set("plot", self._rc_text(rc), gg.fmt_elapsed(time.time() - t))
                    ok = rc == 0
        except Exception as e:
            self.log(f"ERROR: {type(e).__name__}: {e}")
        finally:
            if anim and original_ut:           # SS_animate.sh moves the UT; make sure it is put back
                try:
                    cfg_set(path, "settings", {"ut": original_ut})
                except OSError:
                    pass
            cancelled = self.cancel_flag.is_set()
            files = [r for r in gg.changed_files(before, gg.snapshot_files())
                     if r.replace("\\", "/").startswith((f"output/plots/SS/{call}/", f"output/csv/SS/{call}/"))]
            files.sort(key=result_order)
            self.post(lambda: self._done(name, call, ok, cancelled, files))

    def _done(self, name, call, ok, cancelled, files):
        self._set_busy(False)
        elapsed = gg.fmt_elapsed(time.time() - self.t0) if self.t0 else ""
        self.settings["ss_last"] = {"config": name, "call": call, "ok": ok, "cancelled": cancelled,
                                    "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "files": files}
        gg.save_settings(self.settings)
        self.load_cfg()                         # also refreshes the peak values the scripts wrote back
        self.show_saved_results()
        if cancelled:
            self.log("Cancelled.")
            self.status_var.set("Cancelled")
        elif ok:
            self.log(f"Finished in {elapsed}. Results are in output/plots/SS/{call}/ and output/csv/SS/{call}/ .")
            self.status_var.set(f"Finished in {elapsed}")
        else:
            self.log("The run did not complete; see the messages above.")
            self.status_var.set("Failed")

    def on_cancel(self):
        self.cancel_flag.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                p.terminate()
        self.log("Cancel requested ...")

    # ---------- results ----------
    def show_saved_results(self):
        last = self.settings.get("ss_last") or {}
        for it in self.rtree.get_children():
            self.rtree.delete(it)
        files = [f for f in last.get("files", []) if os.path.isfile(os.path.join(BASE_DIR, f))]
        if not last:
            self.result_head.set("No run yet.")
            return
        state = "cancelled" if last.get("cancelled") else ("finished" if last.get("ok") else "did not complete")
        self.result_head.set(f"Run for {last.get('config', '?')} {state} at {last.get('when', '?')}. "
                             f"Files are in output/plots/SS/{last.get('call', '?')}/ (pictures) and "
                             f"output/csv/SS/{last.get('call', '?')}/ (data).")
        for f in files:
            self.rtree.insert("", "end", iid=f, text=f, values=(describe_result(f),))

    def on_open_selected(self):
        sel = self.rtree.selection()
        if not sel:
            kids = self.rtree.get_children()
            sel = kids[:1]
        if sel and not gg.open_path(os.path.join(BASE_DIR, sel[0])):
            messagebox.showinfo("Open", f"Could not open it automatically. It is here:\n{os.path.join(BASE_DIR, sel[0])}")

    def on_open_folder(self):
        call = station_call(self.config_var.get()) if self.config_var.get() else ""
        for d in (os.path.join(BASE_DIR, "output", "plots", "SS", call), os.path.join(BASE_DIR, "output", "plots", "SS"),
                  os.path.join(BASE_DIR, "output")):
            if os.path.isdir(d):
                gg.open_path(d)
                return
        messagebox.showinfo("Results folder", "Nothing has been written yet (output/plots/SS/ does not exist).")

    def on_close(self):
        if self.busy and not messagebox.askyesno("Quit", "A run is in progress. Stop it and quit?"):
            return
        self.cancel_flag.set()
        self.on_cancel() if self.proc else None
        self.destroy()


def main():
    pre = None
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        pre = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    SSApp(pre).mainloop()


if __name__ == "__main__":
    main()
