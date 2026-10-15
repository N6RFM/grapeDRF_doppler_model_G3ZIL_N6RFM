#!/usr/bin/env python3
"""
pipeline.py — Python replacement for run_pipeline.sh

Author: N6RFM + ChatGPT (2026) March 2026

Features:
- Reads UT timestamp from config (read-only)
- Prompts user to confirm UT before proceeding
- Extracts callsign from config filename
- Runs pathfinder via bash to avoid Exec format errors
- Runs modefinder, synthspec, and spectrogram
- Wraps each step with timing and prints elapsed time
- Checks that pathfinder output exists before continuing
"""

import subprocess
import sys
import os
from datetime import datetime
import re

# -----------------------------
# CONFIGURATION
# -----------------------------
CONFIG_DIR = "/home/bob/grapeDRF_doppler_model/config"
DEFAULT_CONFIG = "N6RFM_config.ini"
CSV_OUTPUT_BASE = "./output/csv"  # pathfinder CSV output base directory

# -----------------------------
# STEP FUNCTION WITH TIMING
# -----------------------------
def run_step(name, *cmd):
    """
    Run a command-line step and measure elapsed time.
    
    Args:
        name (str): Name of the step (for logging)
        cmd (list): Command and arguments to execute
    """
    print("-" * 40)
    print(f"Starting: {name}")
    start = datetime.now()
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Step '{name}' failed: {e}")
        sys.exit(1)
    end = datetime.now()
    elapsed = end - start
    h, remainder = divmod(elapsed.total_seconds(), 3600)
    m, s = divmod(remainder, 60)
    print(f"Finished: {name} (Elapsed: {int(h):02d}:{int(m):02d}:{int(s):02d})")

# -----------------------------
# CONFIG SELECTION
# -----------------------------
def select_config():
    """
    List all config files and allow the user to select one.
    Defaults to DEFAULT_CONFIG if present.
    
    Returns:
        str: Config filename selected
    """
    configs = sorted([f for f in os.listdir(CONFIG_DIR) if f.endswith(".ini")])
    if not configs:
        print("ERROR: No .ini files found in config directory")
        sys.exit(1)

    print("\nAvailable config files:")
    default_index = 0
    for i, cfg in enumerate(configs):
        if cfg == DEFAULT_CONFIG:
            default_index = i
            print(f"{i+1}) {cfg} [default]")
        else:
            print(f"{i+1}) {cfg}")

    choice = input(f"Select config [1-{len(configs)}] (default={default_index+1}): ").strip()
    if not choice:
        choice = str(default_index + 1)

    if not choice.isdigit() or not (1 <= int(choice) <= len(configs)):
        print("ERROR: Invalid selection")
        sys.exit(1)

    config_file = configs[int(choice) - 1]
    print(f"\nUsing config: {config_file}")
    return config_file

# -----------------------------
# UT PARSING FROM CONFIG
# -----------------------------
def parse_ut_from_config(config_path):
    """
    Extract the UT timestamp from a config file.
    
    Expects a line like: ut = [2026, 3, 25, 12, 30]
    
    Returns:
        tuple: (year, month, day, hour, minute)
    """
    with open(config_path, "r") as f:
        for line in f:
            if line.strip().startswith("ut"):
                match = re.search(r"\[([0-9, ]+)\]", line)
                if match:
                    ut_values = [int(x.strip()) for x in match.group(1).split(",")]
                    if len(ut_values) != 5:
                        raise ValueError(f"Expected 5 values for UT, got {ut_values}")
                    return tuple(ut_values)
    raise ValueError("No 'ut' line found in config")

# -----------------------------
# MAIN PROGRAM
# -----------------------------
def main():
    # 1️⃣ Select config
    config_file = select_config()
    config_path = os.path.join(CONFIG_DIR, config_file)

    # 2️⃣ Read UT timestamp
    year, month, day, hour, minute = parse_ut_from_config(config_path)
    timestamp = f"{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}"
    print(f"Timestamp from config: {timestamp}")

    # 3️⃣ Prompt user to confirm UT
    confirm = input("Proceed with this UT timestamp? (y/n) [y]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("Aborted by user.")
        sys.exit(0)

    # 4️⃣ Extract callsign from config filename
    callsign = config_file.split("_")[0]
    print(f"Callsign: {callsign}")
    csv_dir = os.path.join(CSV_OUTPUT_BASE, callsign)

    # 5️⃣ Run pathfinder (via bash to avoid exec format error)
    run_step("pathfinder", "bash", "./pathfinder.sh", config_file, "1400")

    # 6️⃣ Verify pathfinder output exists
    expected_file = os.path.join(csv_dir, f"{timestamp}_pathfinder.csv")
    if not os.path.isfile(expected_file):
        print(f"ERROR: Expected file not found:\n  {expected_file}\nAvailable files:")
        if os.path.isdir(csv_dir):
            for f in sorted(os.listdir(csv_dir)):
                print(f"  {f}")
        sys.exit(1)
    print(f"Found: {expected_file}")

    # 7️⃣ Continue pipeline
    run_step("modefinder", "python3", "modefinder_quiet.py", callsign, timestamp)
    run_step("synthspec", "python3", "synthspec_ch_quiet.py", callsign, timestamp, "DB")
    run_step(
        "spectrogram",
        "python3",
        "grape_fft_spectrogram_ch_quiet.py",
        f"ch0_{callsign}",
        "0",
        "0",
        "24",
        "DB",
    )

    # 8️⃣ Done
    print("-" * 40)
    print("Pipeline complete.")

# -----------------------------
# ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    main()
