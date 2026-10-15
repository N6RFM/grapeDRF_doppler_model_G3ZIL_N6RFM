#!/usr/bin/env python3
"""
grape_gui.py -- Tkinter front end for the grapeDRF_doppler_model workflow

Author: Bob, N6RFM. Written with Claude (Anthropic), October 2026.
Built on N6RFM's drf_data_loader_apf107_check.py and run_pipeline.py, which drive
G3ZIL's grapeDRF_doppler_model (https://github.com/g3zil/grapeDRF_doppler_model).

Combines what drf_data_loader_apf107_check.py and run_pipeline.py do, in one window:

  1. Choose the GRAPE dataset (OBS*.zip or an already-extracted ch0_* folder in
     data/library/), extract it, write its UT timestamp into
     config/<CALLSIGN>_config.ini and copy it to data/psws_grapeDRF/ch0_<CALLSIGN>/
  2. Check that apf107.dat covers the dataset date and update it from ECHAIM if not
  3. Run pathfinder -> modefinder -> synthspec -> spectrogram, with live output and
     per-step timing

Place this file in the root of the grapeDRF_doppler_model project (next to
pathfinder.sh and the config/ folder) and run it from the same Python
environment you use for the pipeline:

    python3 grape_gui.py

Paths are taken from the location of this file. The apf107.dat location and the
last-used options are remembered in grape_gui_settings.json (keep it out of git).

The ClickHouse password is NOT stored here. For the DB option, export it before
starting the GUI:   export CLICKHOUSE_PASSWORD='...'

Dependencies: Python standard library only (tkinter included).
"""

import ast
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from datetime import date, datetime

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ----------------------------------------------------------------------
# PATHS (derived from the location of this file, so nothing is hardcoded)
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, "data", "library")
DATA_ROOT = os.path.join(BASE_DIR, "data", "psws_grapeDRF")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CSV_OUTPUT_BASE = os.path.join(BASE_DIR, "output", "csv")
SETTINGS_FILE = os.path.join(BASE_DIR, "grape_gui_settings.json")

# Daily-updated apf107.dat from the UNB ECHAIM project (IRI Working Group)
APF107_URL = os.environ.get("APF107_URL") or "https://chain-new.chain-project.net/echaim_downloads/DBFiles/apf107.dat"

# apf107.dat used by PHaRLAP/PyLap. Override with the APF107_PATH environment
# variable, or with the Browse button in the GUI (remembered afterwards).
DEFAULT_APF107 = os.environ.get("APF107_PATH") or os.path.expanduser(
    "~/PyLap_Project/PHARLAP/pharlap_4.5.0/dat/iri2016/apf107.dat"
)

UT_LINE = re.compile(r"^\s*ut\s*=")

STEP_DEFS = [
    ("pathfinder", "Pathfinder (ray tracing)"),
    ("modefinder", "Modefinder"),
    ("synthspec", "Synthspec"),
    ("spectrogram", "Spectrogram"),
]


# ----------------------------------------------------------------------
# PURE HELPERS (no GUI; easy to test)
# ----------------------------------------------------------------------
def fmt_elapsed(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def apf107_last_date(path):
    """Return the last date covered by apf107.dat (rows start: YY MM DD ...)."""
    last_line = None
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    if last_line is None:
        raise ValueError("apf107.dat appears to be empty")
    parts = last_line.split()
    yy, mm, dd = int(parts[0]), int(parts[1]), int(parts[2])
    year = 2000 + yy if yy < 50 else 1900 + yy
    return date(year, mm, dd)


def download_apf107(path, url=APF107_URL, timeout=30):
    """
    Download a fresh apf107.dat to a temporary file, check it parses, then
    atomically replace the old file. Returns the last date the new file covers.
    """
    tmp = path + ".tmp"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        new_last = apf107_last_date(tmp)   # raises if it is not a valid file
        os.replace(tmp, path)
        return new_last
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def parse_zip_datetime(zip_name):
    """OBS2026-04-20T00-00.zip -> (2026, 4, 20, 0, 0)"""
    m = re.search(r"OBS(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})", zip_name)
    if not m:
        raise ValueError(f"Invalid ZIP filename format: {zip_name}")
    return tuple(map(int, m.groups()))


def parse_folder_datetime(folder_name):
    """ch0_N6RFM_202604200000 -> (2026, 4, 20, 0, 0)"""
    m = re.search(r"(\d{12})$", folder_name)
    if not m:
        raise ValueError(
            f"Cannot parse timestamp from folder name: {folder_name}\n"
            "Expected format: ch0_<CALLSIGN>_YYYYMMDDHHMM"
        )
    dt = m.group(1)
    return (int(dt[0:4]), int(dt[4:6]), int(dt[6:8]), int(dt[8:10]), int(dt[10:12]))


def source_datetime(stype, name):
    return parse_zip_datetime(name) if stype == "zip" else parse_folder_datetime(name)


def find_sources():
    """List (type, name) for OBS*.zip files and ch0_* folders in data/library."""
    if not os.path.isdir(LIBRARY_DIR):
        return []
    zips, folders = [], []
    for item in sorted(os.listdir(LIBRARY_DIR)):
        full = os.path.join(LIBRARY_DIR, item)
        if item.startswith("OBS") and item.endswith(".zip"):
            zips.append(("zip", item))
        elif os.path.isdir(full) and item.startswith("ch0_"):
            folders.append(("folder", item))
    return zips + folders


def list_configs():
    """Station configs (<CALL>_config.ini); heuristics.ini is not a station config."""
    if not os.path.isdir(CONFIG_DIR):
        return []
    return sorted(f for f in os.listdir(CONFIG_DIR) if f.endswith("_config.ini"))


def read_ut(config_path):
    """Return (year, month, day, hour, minute) from the 'ut = [...]' config line."""
    with open(config_path, "r") as f:
        for line in f:
            if UT_LINE.match(line):
                m = re.search(r"\[([0-9,\s]+)\]", line)
                if m:
                    vals = [int(x) for x in m.group(1).split(",") if x.strip()]
                    if len(vals) != 5:
                        raise ValueError(f"Expected 5 values for UT, got {vals}")
                    return tuple(vals)
    raise ValueError(f"No 'ut = [...]' line found in {config_path}")


def update_config(callsign, year, month, day, hour, minute):
    """Rewrite only the 'ut' line of <CALLSIGN>_config.ini; all else is preserved."""
    config_file = os.path.join(CONFIG_DIR, f"{callsign}_config.ini")
    if not os.path.exists(config_file):
        raise FileNotFoundError(config_file)
    new_ut = f"ut = [{year},{month},{day},{hour},{minute}]"
    with open(config_file) as f:
        lines = f.readlines()
    found = False
    with open(config_file, "w") as f:
        for line in lines:
            if UT_LINE.match(line):
                f.write(new_ut + "\n")
                found = True
            else:
                f.write(line)
    if not found:
        raise ValueError(f"No 'ut' line found in {config_file}; nothing was updated")
    return config_file


def extract_zip_flat(zip_file, callsign, log):
    """
    Extract a GRAPE ZIP into data/library/ch0_<CALLSIGN>_<YYYYMMDDHHMM>/ with a
    single top-level wrapper folder (if any) removed. Returns the folder name.
    """
    y, mo, d, h, mi = parse_zip_datetime(zip_file)
    folder_name = f"ch0_{callsign}_{y:04d}{mo:02d}{d:02d}{h:02d}{mi:02d}"
    dest_path = os.path.join(LIBRARY_DIR, folder_name)
    os.makedirs(dest_path, exist_ok=True)
    dest_real = os.path.realpath(dest_path)
    log(f"Extracting {zip_file} -> {folder_name}")

    with zipfile.ZipFile(os.path.join(LIBRARY_DIR, zip_file), "r") as zf:
        tops = {m.filename.split("/")[0] for m in zf.infolist() if m.filename.strip()}
        top_level = next(iter(tops)) if len(tops) == 1 else None
        for m in zf.infolist():
            if m.is_dir():
                continue
            parts = m.filename.split("/")
            if top_level and parts[0] == top_level:
                parts = parts[1:]
            if not parts:
                continue
            target = os.path.join(dest_path, *parts)
            # refuse entries that would land outside the destination folder
            if os.path.commonpath([dest_real, os.path.realpath(target)]) != dest_real:
                raise ValueError(f"Unsafe path in ZIP: {m.filename}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    log("Extraction complete (flattened)")
    return folder_name


def copy_data(folder_name, callsign, log):
    """Replace data/psws_grapeDRF/ch0_<CALLSIGN>/ with the chosen dataset."""
    src = os.path.join(LIBRARY_DIR, folder_name)
    dest = os.path.join(DATA_ROOT, f"ch0_{callsign}")
    os.makedirs(dest, exist_ok=True)
    for item in os.listdir(dest):
        p = os.path.join(dest, item)
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.unlink(p)
    log(f"Copying -> {dest}")
    for item in os.listdir(src):
        s, d = os.path.join(src, item), os.path.join(dest, item)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
    log("Copy complete")
    return dest


CH_SERVICE = os.environ.get("CLICKHOUSE_SERVICE", "clickhouse-server")
# tables the DB steps write to (upstream README, Appendix A)
CH_REQUIRED_TABLES = ["synth_spec"]
# output lines that mean a step failed even though it exited normally
FAIL_MARKERS = ("Unable to connect or insert",)
CH_PING_URL = os.environ.get("CLICKHOUSE_PING_URL", "http://localhost:8123/ping")


def ch_running(timeout=1.5):
    """True if the ClickHouse HTTP interface answers (the port clickhouse_connect uses)."""
    try:
        with urllib.request.urlopen(CH_PING_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def ch_service(action, log, wait_secs=90):
    """
    Start or stop the ClickHouse system service. Uses pkexec (graphical password
    prompt), then passwordless sudo, or runs directly when already root.
    Returns True on success; waits for the server to answer (start) or go quiet (stop).
    """
    base = ["systemctl", action, CH_SERVICE]
    if os.geteuid() == 0:
        attempts = [base]
    else:
        attempts = []
        if shutil.which("pkexec"):
            attempts.append(["pkexec"] + base)
        attempts.append(["sudo", "-n"] + base)
    ok = False
    for cmd in attempts:
        log("$ " + " ".join(cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"  could not run: {e}")
            continue
        if r.returncode == 0:
            ok = True
            break
        log(f"  failed (exit {r.returncode}): {(r.stderr or r.stdout).strip()}")
    if not ok:
        log(f"Could not {action} ClickHouse automatically. Run in a terminal:  sudo systemctl {action} {CH_SERVICE}")
        return False
    want_up = action == "start"
    deadline = datetime.now().timestamp() + wait_secs
    while datetime.now().timestamp() < deadline:
        if ch_running() == want_up:
            return True
        time.sleep(1)
    log(f"ClickHouse did not {'answer' if want_up else 'shut down'} within {wait_secs} s")
    return False


def ch_params():
    """
    Connection settings the pipeline really uses: read the constant keyword
    arguments of the get_client(...) call in synthspec_ch_quiet.py (host, port,
    username, database). The password always comes from CLICKHOUSE_PASSWORD.
    """
    params, source = {}, None
    for name in ("synthspec_ch_quiet.py", "grape_fft_spectrogram_ch_quiet.py"):
        path = os.path.join(BASE_DIR, name)
        try:
            tree = ast.parse(open(path).read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "get_client":
                for kw in node.keywords:
                    if kw.arg in ("host", "port", "username", "user", "database", "interface", "secure") \
                            and isinstance(kw.value, ast.Constant):
                        params["username" if kw.arg == "user" else kw.arg] = kw.value.value
                source = name
                break
        if source:
            break
    return params, source


CH_CHECK_SCRIPT = r"""
import json, os, sys
p = json.loads(sys.argv[1])
required = p.pop("_require", [])
try:
    import clickhouse_connect
except ImportError:
    print("FAIL: the clickhouse_connect module is not installed in this Python (pip install clickhouse-connect)")
    sys.exit(2)
try:
    from importlib.metadata import version as _ver
    _v = _ver("clickhouse-connect")
except Exception:
    _v = "?"
print("clickhouse_connect", _v)
kw = dict(p)
kw["password"] = os.environ.get("CLICKHOUSE_PASSWORD", "")
try:
    c = clickhouse_connect.get_client(**kw)
    print("connected as", c.query("SELECT currentUser()").result_rows[0][0],
          "| server", getattr(c, "server_version", "?"), "| database", c.database)
    assert c.query("SELECT 1").result_rows[0][0] == 1
    dbs = [r[0] for r in c.query("SHOW DATABASES").result_rows if r[0] not in ("system", "INFORMATION_SCHEMA", "information_schema")]
    print("databases:", ", ".join(dbs) or "(none besides system)")
    tabs = c.query("SELECT database, name, total_rows FROM system.tables WHERE database NOT IN ('system','INFORMATION_SCHEMA','information_schema') ORDER BY 1,2").result_rows
    for d, t, n in tabs[:30]:
        print(f"  {d}.{t}: {n} rows")
    have = {(d, t) for d, t, _ in tabs}
    db = c.database
    missing = [t for t in required if (db, t) not in have]
    if missing:
        print(f"FAIL: required table(s) missing in database '{db}': {', '.join(missing)} "
              "(create them from Appendix A of the upstream README)")
        sys.exit(3)
    if required:
        print("required tables present:", ", ".join(required))
    print("OK")
except Exception as e:
    print("FAIL:", type(e).__name__, str(e).splitlines()[0][:300] if str(e) else "")
    sys.exit(1)
"""


def ch_check(py, log):
    """Preflight: can the pipeline's own Python log in and run queries? True/False."""
    params, source = ch_params()
    log(f"ClickHouse check using {py}")
    log("  settings from " + (f"{source}: {params}" if source else "defaults (no get_client() call found)"))
    if not os.environ.get("CLICKHOUSE_PASSWORD"):
        log("  note: CLICKHOUSE_PASSWORD is not set in this environment (fine only if the user has no password)")
    try:
        r = subprocess.run([py, "-c", CH_CHECK_SCRIPT, json.dumps(dict(params, _require=CH_REQUIRED_TABLES))],
                           capture_output=True, text=True, timeout=60, cwd=BASE_DIR)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"  FAIL: could not run the check: {e}")
        return False
    for line in (r.stdout + r.stderr).splitlines():
        log("  " + line)
    return r.returncode == 0 and "OK" in r.stdout.splitlines()[-1:]


def describe_data(callsign, ut, settings):
    """
    Which dataset is in data/psws_grapeDRF/ch0_<CALL>/ ?  Returns (text, warn).
    Uses what this window recorded when the data was loaded; otherwise a best guess
    from the library by the date in the config's UT.
    """
    dest = os.path.join(DATA_ROOT, f"ch0_{callsign}")
    if not (os.path.isdir(dest) and os.listdir(dest)):
        return (f"Data: nothing in data/psws_grapeDRF/ch0_{callsign}  (load a dataset first)", True)
    rec = (settings.get("loaded") or {}).get(callsign)
    cfg_day = tuple(ut[:3]) if ut else None
    if rec:
        text = f"Data: {rec['source']}  ->  ch0_{callsign}   (day {rec['ut'][0]:04d}-{rec['ut'][1]:02d}-{rec['ut'][2]:02d}, loaded {rec['when']})"
        if cfg_day and tuple(rec["ut"][:3]) != cfg_day:
            return (text + f"   WARNING: config UT day is {cfg_day[0]:04d}-{cfg_day[1]:02d}-{cfg_day[2]:02d}", True)
        return (text, False)
    guess = []
    for stype, name in find_sources():
        try:
            if cfg_day and tuple(source_datetime(stype, name)[:3]) == cfg_day:
                guess.append(name)
        except ValueError:
            pass
    if guess:
        return (f"Data: not loaded through this window; the config day matches {', '.join(guess)}", False)
    return ("Data: not loaded through this window; source unknown", True)


SCAN_SKIP = {".git", "data", "venv", ".venv", "env", "__pycache__", "node_modules"}


def snapshot_files():
    """{relative path: (mtime, size)} for project files, skipping data/, venvs and .git."""
    snap = {}
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP]
        for f in files:
            if f == os.path.basename(SETTINGS_FILE) or f.endswith((".pyc", ".tmp")):
                continue
            full = os.path.join(root, f)
            try:
                st = os.stat(full)
                snap[os.path.relpath(full, BASE_DIR)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
    return snap


def changed_files(before, after):
    """Files that are new or were rewritten between two snapshots."""
    return sorted(rel for rel, sig in after.items() if before.get(rel) != sig)


def open_path(path):
    """Open a file or folder with the desktop's default application."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)            # noqa: F821
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def detect_python():
    """Interpreter for the pipeline steps: saved choice, GRAPE_PYTHON, a venv in the
    project (venv/.venv/env), the venv this GUI runs in, else this interpreter."""
    saved = load_settings().get("python")
    if saved and os.path.isfile(saved):
        return saved
    if os.environ.get("GRAPE_PYTHON"):
        return os.environ["GRAPE_PYTHON"]
    for name in ("venv", ".venv", "env"):
        cand = os.path.join(BASE_DIR, name, "bin", "python")
        if os.path.isfile(cand):
            return cand
    return sys.executable


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.base_title = "GRAPE DRF Doppler Model launcher"
        self.title(self.base_title)
        self.geometry("1000x820")
        self.minsize(820, 640)

        self.settings = load_settings()
        self.q = queue.Queue()
        self.proc = None
        self.cancel_flag = threading.Event()
        self.busy = False
        self.sources = []
        self.py_path = sys.executable
        self.ch_auto = self.ch_stop = True
        self.flagged = None
        self.run_data_text = ""
        self.ch_op = False
        self.ch_started_by_gui = False

        self._build()
        self.refresh_sources()
        self.refresh_configs()
        self.refresh_apf107_status()
        self.refresh_ch()
        self._update_last_button()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        self.log(f"Project folder: {BASE_DIR}")
        self.log(f"GUI Python: {sys.executable}")
        self.log(f"Pipeline Python: {self.py_var.get()}")
        for needed in ("pathfinder.sh", "config"):
            if not os.path.exists(os.path.join(BASE_DIR, needed)):
                self.log(f"WARNING: {needed} not found here. Is grape_gui.py in the project root?")
        if not os.environ.get("CLICKHOUSE_PASSWORD"):
            self.log("Note: CLICKHOUSE_PASSWORD is not set in this environment "
                     "(needed for the DB option of synthspec/spectrogram).")

    # ---------- layout ----------
    def _build(self):
        # status bar first so it always stays visible at the bottom
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

        # whole-window vertical scroll bar at the far right edge
        vbar = ttk.Scrollbar(self, orient="vertical")
        vbar.pack(side="right", fill="y")
        canvas = tk.Canvas(self, highlightthickness=0, yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.configure(command=canvas.yview)
        main = ttk.Frame(canvas, padding=8)
        win = canvas.create_window((0, 0), window=main, anchor="nw")

        def fit(_event=None):
            # follow the window width; use the window height when taller than the content
            canvas.itemconfigure(win, width=canvas.winfo_width(),
                                 height=max(canvas.winfo_height(), main.winfo_reqheight()))
            canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.bind("<Configure>", fit)
        main.bind("<Configure>", fit)

        def wheel(event):
            if isinstance(event.widget, (tk.Text, tk.Listbox, ttk.Treeview, ttk.Combobox)):
                return   # those scroll themselves
            if canvas.bbox("all") and canvas.bbox("all")[3] <= canvas.winfo_height():
                return   # everything fits; nothing to scroll
            step = -1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else 1
            canvas.yview_scroll(step * 3, "units")
        self.bind_all("<MouseWheel>", wheel)
        self.bind_all("<Button-4>", wheel)
        self.bind_all("<Button-5>", wheel)

        # 1. data
        f1 = ttk.LabelFrame(main, text="1. Choose data to analyze  (data/library)", padding=6)
        f1.pack(fill="x", pady=4)
        lf = ttk.Frame(f1)
        lf.pack(fill="x")
        self.src_list = tk.Listbox(lf, height=7, exportselection=False)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.src_list.yview)
        self.src_list.configure(yscrollcommand=sb.set)
        self.src_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.src_list.bind("<<ListboxSelect>>", lambda e: self.refresh_apf107_status())

        rf = ttk.Frame(f1)
        rf.pack(fill="x", pady=(6, 0))
        ttk.Label(rf, text="Callsign:").pack(side="left")
        self.callsign_var = tk.StringVar(value=self.settings.get("callsign", "N6RFM"))
        ttk.Entry(rf, textvariable=self.callsign_var, width=10).pack(side="left", padx=4)
        self.btn_refresh = ttk.Button(rf, text="Refresh list", command=self.refresh_sources)
        self.btn_refresh.pack(side="left", padx=4)
        self.btn_load = ttk.Button(
            rf, text="Load selected data  (extract, set UT in config, copy)", command=self.on_load
        )
        self.btn_load.pack(side="right")

        # 2. indices
        f2 = ttk.LabelFrame(main, text="2. Solar / geomagnetic indices  (apf107.dat)", padding=6)
        f2.pack(fill="x", pady=4)
        pr = ttk.Frame(f2)
        pr.pack(fill="x")
        ttk.Label(pr, text="File:").pack(side="left")
        self.apf_var = tk.StringVar(value=self.settings.get("apf107_path", DEFAULT_APF107))
        e = ttk.Entry(pr, textvariable=self.apf_var)
        e.pack(side="left", fill="x", expand=True, padx=4)
        e.bind("<FocusOut>", lambda ev: self._apf_path_changed())
        ttk.Button(pr, text="Browse...", command=self.on_browse_apf).pack(side="left")
        sr = ttk.Frame(f2)
        sr.pack(fill="x", pady=(6, 0))
        self.apf_status = tk.StringVar()
        self.apf_label = ttk.Label(sr, textvariable=self.apf_status)
        self.apf_label.pack(side="left")
        self.btn_apf_update = ttk.Button(sr, text="Update from ECHAIM", command=self.on_update_apf)
        self.btn_apf_update.pack(side="right")
        self.btn_apf_check = ttk.Button(sr, text="Re-check", command=self.refresh_apf107_status)
        self.btn_apf_check.pack(side="right", padx=4)

        # 3. pipeline
        f3 = ttk.LabelFrame(main, text="3. Run the pipeline", padding=6)
        f3.pack(fill="x", pady=4)
        r1 = ttk.Frame(f3)
        r1.pack(fill="x")
        ttk.Label(r1, text="Config:").pack(side="left")
        self.config_var = tk.StringVar()
        self.config_box = ttk.Combobox(r1, textvariable=self.config_var, state="readonly", width=24)
        self.config_box.pack(side="left", padx=4)
        self.config_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_ut())
        self.ut_var = tk.StringVar()
        ttk.Label(r1, textvariable=self.ut_var, font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=12)

        r2 = ttk.Frame(f3)
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="Pathfinder arg:").pack(side="left")
        self.pf_var = tk.StringVar(value=self.settings.get("pathfinder_arg", "1400"))
        ttk.Entry(r2, textvariable=self.pf_var, width=7).pack(side="left", padx=4)
        ttk.Label(r2, text="Spectrogram args:").pack(side="left", padx=(12, 0))
        self.spec_var = tk.StringVar(value=self.settings.get("spec_args", "0 0 24"))
        ttk.Entry(r2, textvariable=self.spec_var, width=10).pack(side="left", padx=4)
        self.db_var = tk.BooleanVar(value=self.settings.get("db", True))
        ttk.Checkbutton(r2, text="Use ClickHouse DB (DB flag)", variable=self.db_var).pack(side="left", padx=12)

        self.data_var = tk.StringVar()
        self.data_label = ttk.Label(f3, textvariable=self.data_var, font=("TkDefaultFont", 10, "bold"),
                                    wraplength=960, justify="left")
        self.data_label.pack(fill="x", pady=(6, 0))

        rc = ttk.Frame(f3)
        rc.pack(fill="x", pady=(6, 0))
        ttk.Label(rc, text="ClickHouse:").pack(side="left")
        self.ch_var = tk.StringVar(value="checking ...")
        self.ch_label = ttk.Label(rc, textvariable=self.ch_var, width=12, font=("TkDefaultFont", 10, "bold"))
        self.ch_label.pack(side="left", padx=4)
        self.btn_ch_start = ttk.Button(rc, text="Start", command=lambda: self.on_ch("start"))
        self.btn_ch_start.pack(side="left")
        self.btn_ch_stop = ttk.Button(rc, text="Stop", command=lambda: self.on_ch("stop"))
        self.btn_ch_stop.pack(side="left", padx=4)
        self.btn_ch_test = ttk.Button(rc, text="Test", command=self.on_ch_test)
        self.btn_ch_test.pack(side="left")
        self.ch_auto_var = tk.BooleanVar(value=self.settings.get("ch_auto_start", True))
        ttk.Checkbutton(rc, text="Auto-start if needed", variable=self.ch_auto_var).pack(side="left", padx=(12, 0))
        self.ch_stop_var = tk.BooleanVar(value=self.settings.get("ch_stop_after", True))
        ttk.Checkbutton(rc, text="Stop afterwards (if I started it)", variable=self.ch_stop_var).pack(side="left", padx=8)

        rp = ttk.Frame(f3)
        rp.pack(fill="x", pady=(6, 0))
        ttk.Label(rp, text="Python (venv):").pack(side="left")
        self.py_var = tk.StringVar(value=detect_python())
        ttk.Entry(rp, textvariable=self.py_var).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(rp, text="Browse...", command=self.on_browse_python).pack(side="left")

        r3 = ttk.Frame(f3)
        r3.pack(fill="x", pady=(6, 0))
        ttk.Label(r3, text="Steps:").pack(side="left")
        saved = self.settings.get("steps", [k for k, _ in STEP_DEFS])
        self.step_vars = {}
        for key, label in STEP_DEFS:
            v = tk.BooleanVar(value=key in saved)
            self.step_vars[key] = v
            ttk.Checkbutton(r3, text=label, variable=v).pack(side="left", padx=6)

        self.tree = ttk.Treeview(f3, columns=("status", "elapsed"), height=4)
        self.tree.heading("#0", text="Step")
        self.tree.heading("status", text="Status")
        self.tree.heading("elapsed", text="Elapsed")
        self.tree.column("#0", width=220)
        self.tree.column("status", width=260)
        self.tree.column("elapsed", width=100, anchor="center")
        for key, label in STEP_DEFS:
            self.tree.insert("", "end", iid=key, text=label, values=("", ""))
        self.tree.pack(fill="x", pady=(8, 0))

        r4 = ttk.Frame(f3)
        r4.pack(fill="x", pady=(8, 0))
        self.btn_run = ttk.Button(r4, text="Run pipeline", command=self.on_run)
        self.btn_run.pack(side="left")
        self.btn_cancel = ttk.Button(r4, text="Cancel", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=6)
        self.btn_last = ttk.Button(r4, text="Show last results", command=self.on_show_last, state="disabled")
        self.btn_last.pack(side="left", padx=6)
        ttk.Button(r4, text="Open results folder (output/)", command=self.on_open_output).pack(side="left")

        # log: header row (label left, buttons right) above a dark console
        f4 = ttk.Frame(main)
        f4.pack(fill="both", expand=True, pady=(8, 4))
        hdr = ttk.Frame(f4)
        hdr.pack(fill="x", pady=(0, 4))
        ttk.Label(hdr, text="Output:").pack(side="left")
        ttk.Button(hdr, text="Clear", command=self._clear_log).pack(side="right")
        ttk.Button(hdr, text="Copy", command=self._copy_best).pack(side="right", padx=8)
        ttk.Button(hdr, text="Save to file...", command=self._save_log).pack(side="right")
        self.log_box = scrolledtext.ScrolledText(
            f4, height=12, state="disabled", wrap="none", bg="#111111", fg="#e6e6e6",
            insertbackground="#e6e6e6", selectbackground="#3d6fb4", selectforeground="#ffffff",
            relief="flat", font=("TkFixedFont", 10))
        self.log_box.pack(fill="both", expand=True)
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.wrap_var = tk.BooleanVar(value=False)

        # selecting/copying works even though the box is read-only
        self.log_box.bind("<Button-1>", lambda e: self.log_box.focus_set())
        self.log_box.bind("<Control-c>", lambda e: (self._copy_best(), "break")[1])
        self.log_box.bind("<Control-a>", lambda e: (self._select_all(), "break")[1])
        self.log_box.bind("<Control-l>", lambda e: (self._clear_log(), "break")[1])
        menu = tk.Menu(self.log_box, tearoff=0)
        menu.add_command(label="Copy selection", command=self._copy_selection)
        menu.add_command(label="Copy all", command=self._copy_all)
        menu.add_command(label="Select all", command=self._select_all)
        menu.add_separator()
        menu.add_checkbutton(label="Auto-scroll", variable=self.autoscroll_var)
        menu.add_checkbutton(label="Wrap lines", variable=self.wrap_var,
                             command=lambda: self.log_box.configure(wrap="word" if self.wrap_var.get() else "none"))
        menu.add_separator()
        menu.add_command(label="Save to file...", command=self._save_log)
        menu.add_command(label="Clear", command=self._clear_log)
        for ev in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.log_box.bind(ev, lambda e, m=menu: (self.log_box.focus_set(), m.tk_popup(e.x_root, e.y_root), "break")[2])

        self._action_buttons = [
            self.btn_refresh, self.btn_load, self.btn_apf_update, self.btn_apf_check, self.btn_run
        ]

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

    def _clipboard_set(self, text):
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()

    def _copy_selection(self):
        try:
            self._clipboard_set(self.log_box.get("sel.first", "sel.last"))
        except tk.TclError:
            pass   # nothing selected

    def _copy_best(self):
        """Copy the selection if there is one, otherwise the whole output."""
        if self.log_box.tag_ranges("sel"):
            self._copy_selection()
        else:
            self._copy_all()

    def _copy_all(self):
        self._clipboard_set(self.log_box.get("1.0", "end-1c"))

    def _select_all(self):
        self.log_box.tag_add("sel", "1.0", "end-1c")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            title="Save log", defaultextension=".txt", initialdir=BASE_DIR,
            initialfile=f"grape_gui_log_{datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            try:
                with open(path, "w") as f:
                    f.write(self.log_box.get("1.0", "end-1c") + "\n")
            except OSError as e:
                messagebox.showerror("Save failed", str(e))

    def _append_log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        if self.autoscroll_var.get():
            self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy, status=None):
        self.busy = busy
        for b in self._action_buttons:
            b.configure(state="disabled" if busy else "normal")
        if status:
            self.status_var.set(status)

    def _tree_set(self, key, status, elapsed):
        self.tree.item(key, values=(status, elapsed))

    # ---------- section 1: data ----------
    def refresh_sources(self):
        self.sources = find_sources()
        self.src_list.delete(0, "end")
        for stype, name in self.sources:
            self.src_list.insert("end", f"[{stype:6}] {name}")
        if not self.sources:
            self.src_list.insert("end", f"(no OBS*.zip or ch0_* folders in {LIBRARY_DIR})")

    def _selected_source(self):
        sel = self.src_list.curselection()
        if not sel or sel[0] >= len(self.sources):
            return None
        return self.sources[sel[0]]

    def on_load(self):
        if self.busy:
            return
        src = self._selected_source()
        if not src:
            messagebox.showwarning("Choose data", "Select a ZIP or folder from the list first.")
            return
        stype, name = src
        callsign = self.callsign_var.get().strip().upper()
        if not callsign:
            messagebox.showwarning("Callsign", "Enter a callsign.")
            return
        cfg_path = os.path.join(CONFIG_DIR, f"{callsign}_config.ini")
        if not os.path.exists(cfg_path):
            messagebox.showerror(
                "Config not found",
                f"No config file for {callsign}:\n{cfg_path}\n\n"
                "Copy an existing config (e.g. N6RFM_config.ini) to that name and edit it.",
            )
            return
        try:
            y, mo, d, h, mi = source_datetime(stype, name)
        except ValueError as e:
            messagebox.showerror("Bad name", str(e))
            return

        # indices must cover the dataset date BEFORE anything is overwritten
        if not self._ensure_apf107(date(y, mo, d)):
            return

        dest = os.path.join(DATA_ROOT, f"ch0_{callsign}")
        if os.path.isdir(dest) and os.listdir(dest):
            if not messagebox.askyesno(
                "Replace working data?",
                f"This will DELETE the current contents of:\n{dest}\n\nand replace them with {name}.\n\nContinue?",
            ):
                return

        self.settings["callsign"] = callsign
        save_settings(self.settings)
        self._set_busy(True, f"Loading {name} ...")

        def worker():
            try:
                folder = extract_zip_flat(name, callsign, self.log) if stype == "zip" else name
                update_config(callsign, y, mo, d, h, mi)
                self.log(f"Updated config: {cfg_path}  ut = [{y},{mo},{d},{h},{mi}]")
                copy_data(folder, callsign, self.log)
                self.log(f"READY -> {dest}")
                info = dict(source=name, kind=stype, folder=folder, ut=[y, mo, d, h, mi],
                            when=datetime.now().strftime("%Y-%m-%d %H:%M"))
                self.post(lambda: self._load_done(callsign, info))
            except Exception as e:
                msg = str(e)
                self.log(f"ERROR: {msg}")
                self.post(lambda: messagebox.showerror("Load failed", msg))
                self.post(lambda: self._set_busy(False, "Load failed"))

        threading.Thread(target=worker, daemon=True).start()

    def _load_done(self, callsign, info=None):
        if info:
            self.settings.setdefault("loaded", {})[callsign] = info
            save_settings(self.settings)
        self.refresh_sources()
        self.refresh_configs(select=f"{callsign}_config.ini")
        self._set_busy(False, f"Data loaded for {callsign}. Ready to run the pipeline.")

    # ---------- section 2: indices ----------
    def _apf_path_changed(self):
        self.settings["apf107_path"] = self.apf_var.get().strip()
        save_settings(self.settings)
        self.refresh_apf107_status()

    def on_browse_apf(self):
        path = filedialog.askopenfilename(
            title="Locate apf107.dat",
            initialfile="apf107.dat",
            initialdir=os.path.dirname(self.apf_var.get()) or os.path.expanduser("~"),
        )
        if path:
            self.apf_var.set(path)
            self._apf_path_changed()

    def refresh_apf107_status(self):
        path = self.apf_var.get().strip()
        color = "black"
        if not os.path.isfile(path):
            text = "apf107.dat not found. Use Browse to point at PHaRLAP's dat/iri2016/apf107.dat"
            color = "red"
        else:
            try:
                last = apf107_last_date(path)
                text = f"Covers through {last:%Y-%m-%d}."
                src = self._selected_source()
                if src:
                    try:
                        y, mo, d, _, _ = source_datetime(*src)
                        want = date(y, mo, d)
                        if want <= last:
                            text += f"  Selected data ({want:%Y-%m-%d}): covered."
                            color = "dark green"
                        else:
                            text += f"  Selected data ({want:%Y-%m-%d}): NOT covered, update needed."
                            color = "red"
                    except ValueError:
                        pass
            except Exception as e:
                text = f"Could not read apf107.dat: {e}"
                color = "red"
        self.apf_status.set(text)
        self.apf_label.configure(foreground=color)

    def on_update_apf(self):
        if self.busy:
            return
        path = self.apf_var.get().strip()
        if not path:
            messagebox.showwarning("apf107.dat", "Set the apf107.dat location first.")
            return
        self._set_busy(True, "Downloading apf107.dat ...")
        self.log(f"Downloading {APF107_URL}")

        def worker():
            try:
                last = download_apf107(path)
                self.log(f"apf107.dat updated: now covers through {last:%Y-%m-%d}")
            except Exception as e:
                self.log(f"ERROR: download failed: {e}")
            self.post(self.refresh_apf107_status)
            self.post(lambda: self._set_busy(False, "Ready"))

        threading.Thread(target=worker, daemon=True).start()

    def _ensure_apf107(self, run_date):
        """Blocking check used before loading data. True means OK to proceed."""
        path = self.apf_var.get().strip()
        if not os.path.isfile(path):
            messagebox.showerror(
                "apf107.dat not found",
                f"Not found at:\n{path}\n\nUse Browse to locate it, or get a current copy from:\n{APF107_URL}",
            )
            return False
        try:
            last = apf107_last_date(path)
        except Exception as e:
            return messagebox.askyesno(
                "apf107.dat unreadable",
                f"Could not parse apf107.dat to check coverage:\n{e}\n\nContinue anyway?",
            )
        if run_date <= last:
            self.log(f"apf107.dat covers {run_date:%Y-%m-%d} (through {last:%Y-%m-%d}) - OK")
            return True

        short = (run_date - last).days
        if not messagebox.askyesno(
            "apf107.dat out of date",
            f"apf107.dat ends {last:%Y-%m-%d}, {short} day(s) before the data date "
            f"{run_date:%Y-%m-%d}.\n\nIRI would use fill values, which can crash pathfinder or give "
            f"unreliable ray traces.\n\nDownload an updated copy from ECHAIM now?",
        ):
            return False
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            new_last = download_apf107(path)
        except Exception as e:
            messagebox.showerror("Download failed", str(e))
            return False
        finally:
            self.config(cursor="")
        self.log(f"apf107.dat updated: now covers through {new_last:%Y-%m-%d}")
        self.refresh_apf107_status()
        if run_date > new_last:
            return messagebox.askyesno(
                "Still not covered",
                f"Even the updated file ends {new_last:%Y-%m-%d} (ECHAIM usually lags 1-2 days).\n"
                "IRI results for this date may be degraded.\n\nContinue anyway?",
            )
        return True

    # ---------- section 3: pipeline ----------
    def refresh_configs(self, select=None):
        configs = list_configs()
        self.config_box["values"] = configs
        want = select or self.config_var.get() or self.settings.get("config", "")
        if want in configs:
            self.config_var.set(want)
        elif configs:
            self.config_var.set(configs[0])
        else:
            self.config_var.set("")
        self.refresh_ut()

    # ---------- ClickHouse on demand ----------
    def refresh_ch(self):
        """Poll the server in a thread (never blocks the window); reschedules itself."""
        def probe():
            up = ch_running()
            self.post(lambda: self._show_ch(up))
        threading.Thread(target=probe, daemon=True).start()
        self.after(5000, self.refresh_ch)

    def _show_ch(self, up):
        self.ch_var.set("running" if up else "stopped")
        self.ch_label.configure(foreground="#1a7f1a" if up else "#b00000")

    def on_ch_test(self):
        """Start the server if needed (asks first), then log in and query it."""
        if self.busy or self.ch_op:
            return
        py = self.py_var.get().strip()
        if not (py and os.path.isfile(py)):
            messagebox.showerror("Python not found", f"Not a file:\n{py}")
            return
        start_first = False
        if not ch_running():
            start_first = messagebox.askyesno("ClickHouse is stopped", "ClickHouse is not running. Start it for the test?\n(It will be stopped again afterwards.)")
            if not start_first:
                return
        self.ch_op = True
        for b in (self.btn_ch_start, self.btn_ch_stop, self.btn_ch_test):
            b.configure(state="disabled")

        def worker():
            ok, started = False, False
            try:
                if start_first:
                    self.log("Starting ClickHouse for the test ...")
                    started = ch_service("start", self.log)
                    if not started:
                        return
                ok = ch_check(py, self.log)
            finally:
                if started:
                    self.log("Stopping ClickHouse again ...")
                    ch_service("stop", self.log, wait_secs=60)
                def done():
                    self.ch_op = False
                    for b in (self.btn_ch_start, self.btn_ch_stop, self.btn_ch_test):
                        b.configure(state="normal")
                    self._show_ch(ch_running(0.5))
                    (messagebox.showinfo if ok else messagebox.showerror)(
                        "ClickHouse test", "ClickHouse is working." if ok else "ClickHouse test FAILED - see the Output box.")
                self.post(done)
        threading.Thread(target=worker, daemon=True).start()

    def on_ch(self, action):
        if self.busy or self.ch_op:
            return
        self.ch_op = True
        self.btn_ch_start.configure(state="disabled")
        self.btn_ch_stop.configure(state="disabled")

        def worker():
            if action == "start" and ch_running():
                self.log("ClickHouse is already running")
                ok = True
            elif action == "stop" and not ch_running():
                self.log("ClickHouse is already stopped")
                ok = True
            else:
                self.log(f"{'Starting' if action == 'start' else 'Stopping'} ClickHouse ...")
                ok = ch_service(action, self.log)
                if ok:
                    self.log(f"ClickHouse {'started' if action == 'start' else 'stopped'}")
                    self.ch_started_by_gui = (action == "start")
            def done():
                self.ch_op = False
                self.btn_ch_start.configure(state="normal")
                self.btn_ch_stop.configure(state="normal")
                self._show_ch(ch_running(0.5))
            self.post(done)
        threading.Thread(target=worker, daemon=True).start()

    def on_browse_python(self):
        path = filedialog.askopenfilename(
            title="Select the python executable of your venv (e.g. venv/bin/python)",
            initialdir=BASE_DIR)
        if path:
            self.py_var.set(path)

    def refresh_data_banner(self):
        cfg = self.config_var.get()
        if not cfg:
            self.data_var.set("")
            return
        callsign = cfg.split("_")[0]
        try:
            ut = read_ut(os.path.join(CONFIG_DIR, cfg))
        except Exception:
            ut = None
        text, warn = describe_data(callsign, ut, self.settings)
        self.data_var.set(text)
        self.data_label.configure(foreground="#b36b00" if warn else "#1a5fb4")

    def refresh_ut(self):
        cfg = self.config_var.get()
        self.refresh_data_banner()
        if not cfg:
            self.ut_var.set("No config files found")
            return
        try:
            y, mo, d, h, mi = read_ut(os.path.join(CONFIG_DIR, cfg))
            self.ut_var.set(f"UT in config: {y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}")
        except Exception as e:
            self.ut_var.set("No 'ut = [...]' line in this config (load data for this station first)" if "No 'ut" in str(e) else f"UT unreadable: {e}")

    def on_run(self):
        if self.busy:
            return
        cfg = self.config_var.get()
        if not cfg:
            messagebox.showwarning("Config", "No config selected.")
            return
        try:
            y, mo, d, h, mi = read_ut(os.path.join(CONFIG_DIR, cfg))
        except Exception as e:
            messagebox.showerror("Config", str(e))
            return
        timestamp = f"{y:04d}{mo:02d}{d:02d}{h:02d}{mi:02d}"
        callsign = cfg.split("_")[0]
        steps = [k for k, _ in STEP_DEFS if self.step_vars[k].get()]
        if not steps:
            messagebox.showwarning("Steps", "Tick at least one step.")
            return
        use_db = self.db_var.get()
        if use_db and not os.environ.get("CLICKHOUSE_PASSWORD"):
            if not messagebox.askyesno(
                "ClickHouse password",
                "CLICKHOUSE_PASSWORD is not set in the environment this GUI was started from, "
                "so the DB steps will likely fail to log in.\n\nContinue anyway?",
            ):
                return
        if not messagebox.askyesno(
            "Confirm",
            f"Run {', '.join(steps)}\nconfig: {cfg}\nUT: {y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}  ({timestamp})\n\nProceed?",
        ):
            return

        py = self.py_var.get().strip()
        if not (py and os.path.isfile(py) and os.access(py, os.X_OK)):
            messagebox.showerror("Python not found", f"Not an executable file:\n{py}\n\nBrowse to your venv's bin/python.")
            return
        self.py_path = py
        self.settings["python"] = py

        pf_arg = self.pf_var.get().strip() or "1400"
        spec_args = self.spec_var.get().split() or ["0", "0", "24"]
        self.settings.update(
            config=cfg, pathfinder_arg=pf_arg, spec_args=" ".join(spec_args), db=use_db, steps=steps,
            ch_auto_start=self.ch_auto_var.get(), ch_stop_after=self.ch_stop_var.get(),
        )
        save_settings(self.settings)
        # snapshot Tk variables here; worker threads must not touch Tk
        self.ch_auto, self.ch_stop = self.ch_auto_var.get(), self.ch_stop_var.get()

        for key, label in STEP_DEFS:
            self._tree_set(key, "Pending" if key in steps else "Skipped", "")
        self.cancel_flag.clear()
        self.settings.pop("last_run", None)      # replaced by this run's results
        save_settings(self.settings)
        self._update_last_button()
        data_text, _warn = describe_data(callsign, (y, mo, d, h, mi), self.settings)
        self.run_data_text = data_text
        rec = (self.settings.get("loaded") or {}).get(callsign)
        data_name = rec["source"] if rec else f"ch0_{callsign}"
        self.title(f"{self.base_title}  -  {callsign} {y:04d}-{mo:02d}-{d:02d}")
        self._set_busy(True, f"Running pipeline for {callsign}  |  {data_name}  |  UT {y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}")
        self.btn_cancel.configure(state="normal")
        threading.Thread(
            target=self._pipeline_worker,
            args=(cfg, callsign, timestamp, steps, pf_arg, spec_args, use_db),
            daemon=True,
        ).start()

    def on_open_output(self):
        out = os.path.join(BASE_DIR, "output")
        os.makedirs(out, exist_ok=True)
        if not open_path(out):
            messagebox.showinfo("Results folder", f"Your results are in:\n{out}")

    def _finish_results(self, last, show):
        """Remember this run's results (survives closing the window) and optionally show them."""
        self.settings["last_run"] = last
        save_settings(self.settings)
        self._update_last_button()
        if show:
            self.on_show_last()

    def _update_last_button(self):
        has = bool((self.settings.get("last_run") or {}).get("results"))
        self.btn_last.configure(state="normal" if has else "disabled")

    def on_show_last(self):
        last = self.settings.get("last_run")
        if not last:
            messagebox.showinfo("Last results", "No results to show yet. They appear after a run.")
            return
        self.show_results(last["title"], last["headline"], [(k, f) for k, f in last["results"]],
                          last.get("db_note"), data=last.get("data"), when=last.get("when"))

    def show_results(self, title, headline, results, db_note, data=None, when=None):
        """Dialog that says exactly where the results are; double-click a file to open it."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=headline, font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        if when:
            ttk.Label(frm, text=f"Run finished: {when}").pack(anchor="w", pady=(4, 0))
        if data:
            ttk.Label(frm, text=data, wraplength=620, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Label(frm, text=f"Project folder: {BASE_DIR}").pack(anchor="w", pady=(6, 0))
        if db_note:
            ttk.Label(frm, text=db_note, wraplength=620, justify="left").pack(anchor="w", pady=(6, 0))
        paths = [(step, rel) for step, files in results for rel in files]
        if paths:
            ttk.Label(frm, text="Files written by this run (double-click to open):").pack(anchor="w", pady=(10, 2))
            lf = ttk.Frame(frm)
            lf.pack(fill="both", expand=True)
            lb = tk.Listbox(lf, height=min(max(len(paths), 4), 14), width=90, exportselection=False)
            sb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            lb.pack(side="left", fill="both", expand=True)
            sb.pack(side="left", fill="y")
            for step, rel in paths:
                lb.insert("end", f"[{step}]  {rel}")

            def open_sel(_e=None):
                sel = lb.curselection()
                if sel:
                    full = os.path.join(BASE_DIR, paths[sel[0]][1])
                    if not open_path(full):
                        messagebox.showinfo("Open", f"Could not open it automatically:\n{full}", parent=dlg)
            lb.bind("<Double-Button-1>", open_sel)
        else:
            ttk.Label(frm, text="No new files were found in the project folder. Check the Output log.").pack(anchor="w", pady=(10, 0))
            open_sel = None
        bf = ttk.Frame(frm)
        bf.pack(fill="x", pady=(10, 0))
        ttk.Button(bf, text="Close", command=dlg.destroy).pack(side="right")
        ttk.Button(bf, text="Open results folder", command=self.on_open_output).pack(side="right", padx=6)
        if open_sel:
            ttk.Button(bf, text="Open selected file", command=open_sel).pack(side="right")
        dlg.update_idletasks()
        dlg.lift()

    def on_cancel(self):
        self.cancel_flag.set()
        self._kill_proc()
        self.log("Cancel requested ...")

    def _kill_proc(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    p.terminate()
                except OSError:
                    pass

    def _run_cmd(self, cmd):
        env = os.environ.copy()
        # make bash steps (pathfinder.sh) see the same venv as the Python steps
        py_dir = os.path.dirname(self.py_path)
        venv_root = os.path.dirname(py_dir)
        if os.path.isfile(os.path.join(venv_root, "pyvenv.cfg")):
            env["VIRTUAL_ENV"] = venv_root
            env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        env["MPLBACKEND"] = "Agg"        # never pop up plot windows; files are still saved
        self.log("$ " + " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd, cwd=BASE_DIR, env=env, text=True, bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.flagged = None
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            self.log(line)
            if self.flagged is None and any(m in line for m in FAIL_MARKERS):
                self.flagged = line.strip()
        rc = self.proc.wait()
        self.proc = None
        return rc

    def _pipeline_worker(self, cfg, callsign, timestamp, steps, pf_arg, spec_args, use_db):
        py = self.py_path
        csv_dir = os.path.join(CSV_OUTPUT_BASE, callsign)
        csv_file = os.path.join(csv_dir, f"{timestamp}_pathfinder.csv")
        db = ["DB"] if use_db else []
        cmds = {
            "pathfinder": ["bash", "./pathfinder.sh", cfg, pf_arg],
            "modefinder": [py, "modefinder_quiet.py", callsign, timestamp],
            "synthspec": [py, "synthspec_ch_quiet.py", callsign, timestamp] + db,
            "spectrogram": [py, "grape_fft_spectrogram_ch_quiet.py", f"ch0_{callsign}"] + spec_args + db,
        }

        def csv_missing():
            self.log(f"ERROR: expected pathfinder output not found:\n  {csv_file}")
            if os.path.isdir(csv_dir):
                self.log("Available files:")
                for f in sorted(os.listdir(csv_dir)):
                    self.log(f"  {f}")

        total_start = datetime.now()
        self.log("=" * 60)
        self.log(self.run_data_text)
        self.log(f"Config: {cfg}   UT: {timestamp}   Steps: {', '.join(steps)}")
        self.log("=" * 60)
        outcome, detail = "ok", ""
        needs_db = use_db and any(k in steps for k in ("synthspec", "spectrogram"))
        results = []     # [(step, [relative paths])]
        try:
            if needs_db and not ch_running():
                if not self.ch_auto:
                    raise RuntimeError("ClickHouse is not running. Click Start (or tick 'Start automatically').")
                self.log("ClickHouse is not running - starting it ...")
                self.post(lambda: self.status_var.set("Starting ClickHouse ..."))
                if not ch_service("start", self.log):
                    raise RuntimeError("could not start ClickHouse")
                self.ch_started_by_gui = True
                self.log("ClickHouse is up")
            if needs_db:
                # fail now, not after an hour of ray tracing
                if not ch_check(py, self.log):
                    raise RuntimeError("ClickHouse check failed (see Output). Nothing was run.")
            for key in [k for k, _ in STEP_DEFS if k in steps]:
                if self.cancel_flag.is_set():
                    outcome = "cancelled"
                    break
                if key == "modefinder" and not os.path.isfile(csv_file):
                    csv_missing()
                    self.post(lambda k=key: self._tree_set(k, "Failed: pathfinder output missing", ""))
                    outcome, detail = "failed", "pathfinder output not found"
                    break

                self.post(lambda k=key: self._tree_set(k, "Running ...", ""))
                self.log("-" * 40)
                self.log(f"Starting: {key}")
                t0 = datetime.now()
                before = snapshot_files()
                rc = self._run_cmd(cmds[key])
                el = fmt_elapsed((datetime.now() - t0).total_seconds())
                step_files = changed_files(before, snapshot_files())
                if step_files:
                    results.append((key, step_files))
                    self.log(f"Files written by {key}:")
                    for rel in step_files[:12]:
                        self.log(f"   {rel}")
                    if len(step_files) > 12:
                        self.log(f"   ... and {len(step_files) - 12} more")

                if self.cancel_flag.is_set():
                    self.post(lambda k=key, e=el: self._tree_set(k, "Cancelled", e))
                    outcome = "cancelled"
                    break
                if rc != 0:
                    self.log(f"ERROR: step '{key}' failed (exit code {rc})")
                    self.post(lambda k=key, e=el, r=rc: self._tree_set(k, f"Failed (exit {r})", e))
                    outcome, detail = "failed", f"{key} exited with code {rc}"
                    break
                if self.flagged:
                    self.log(f"ERROR: step '{key}' reported a problem although it exited normally: {self.flagged}")
                    self.post(lambda k=key, e=el: self._tree_set(k, "Failed: database insert error", e))
                    outcome, detail = "failed", f"{key}: {self.flagged}"
                    break
                if key == "pathfinder" and not os.path.isfile(csv_file):
                    csv_missing()
                    self.post(lambda k=key, e=el: self._tree_set(k, "Failed: no CSV produced", e))
                    outcome, detail = "failed", "pathfinder produced no CSV"
                    break
                self.log(f"Finished: {key} (Elapsed: {el})")
                self.post(lambda k=key, e=el: self._tree_set(k, "Done", e))
        except Exception as e:
            outcome, detail = "failed", str(e)
            self.log(f"ERROR: {e}")

        if self.ch_started_by_gui and self.ch_stop:
            self.log("Stopping ClickHouse (it was started by this window) ...")
            if ch_service("stop", self.log, wait_secs=60):
                self.ch_started_by_gui = False
                self.log("ClickHouse stopped")
        self.post(lambda: self._show_ch(ch_running(0.5)))

        total = fmt_elapsed((datetime.now() - total_start).total_seconds())
        self.log("-" * 40)
        db_note = None
        if use_db and "synthspec" in steps and any(k == "synthspec" for k, _f in results):
            dbp, _src = ch_params()
            db_note = (f"Synthetic spectra were written to the ClickHouse table "
                       f"{dbp.get('database', 'psws')}.synth_spec (query it with clickhouse-client).")
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        if outcome == "ok":
            headline = f"Finished in {total}."
            title_txt = "Pipeline complete"
        elif outcome == "cancelled":
            headline = f"Cancelled after {total}. Partial results:"
            title_txt = "Pipeline cancelled"
        else:
            headline = f"FAILED after {total} ({detail}). Partial results:"
            title_txt = "Pipeline failed"
        last = dict(title=title_txt, headline=headline, results=results, db_note=db_note,
                    data=self.run_data_text, when=when)
        if outcome == "ok":
            self.log(f"Pipeline complete. Total elapsed {total}")
            status = f"Pipeline complete ({total})"
            self.log("RESULTS: files are under " + os.path.join(BASE_DIR, "output") + (f"   |   {db_note}" if db_note else ""))
            self.post(lambda: self._finish_results(last, show=True))
        elif outcome == "cancelled":
            self.log("Pipeline cancelled.")
            status = "Cancelled"
            self.post(lambda: self._finish_results(last, show=False))
        else:
            status = f"Pipeline failed: {detail}"
            self.post(lambda: messagebox.showerror("Pipeline failed", detail))
            self.post(lambda: self._finish_results(last, show=False))
        self.post(lambda: self.btn_cancel.configure(state="disabled"))
        self.post(lambda: self.title(self.base_title))
        self.post(lambda: self._set_busy(False, status))

    # ---------- shutdown ----------
    def on_close(self):
        if self.busy and not messagebox.askyesno("Quit", "A task is running. Stop it and quit?"):
            return
        self.cancel_flag.set()
        self._kill_proc()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
