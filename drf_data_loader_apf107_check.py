#!/usr/bin/env python3
"""
Grape_DRF Loader (ZIP or pre-extracted folder support)

Author: N6RFM + ChatGPT (rewritten) 22April26

PURPOSE
-------
Prepares GRAPE DRF datasets for the G3ZIL grapeDRF_doppler_model pipeline.

Behavior:
    - ZIPs are prioritized, but user can choose an existing folder if desired.
    - Flatten ZIPs (remove top-level folder).
    - Update config/<CALLSIGN>_config.ini ut timestamp.
    - Copy data into working directory safely.
    - Check apf107.dat coverage against config UT and offer to update.

TYPICAL USAGE
-------------
    python drf_data_loader_apf107_check.py

    The script will:
        1. List available ZIP files and extracted folders in LIBRARY_DIR
        2. Prompt for a selection
        3. Prompt for callsign (default N6RFM)
        4. Extract ZIP (if selected) into a flattened folder in LIBRARY_DIR
        5. Update the UT timestamp in config/<CALLSIGN>_config.ini
        6. Verify apf107.dat covers the dataset date; offer to download if not
        7. Copy the dataset into the pipeline working directory

DIRECTORY LAYOUT
----------------
    BASE_DIR/
        config/
            N6RFM_config.ini        <- UT timestamp updated here
        data/
            library/
                OBS2026-04-20T00-00.zip   <- input ZIPs go here
                ch0_N6RFM_202604200000/   <- extracted folders stored here
            psws_grapeDRF/
                ch0_N6RFM/               <- pipeline working directory

DEPENDENCIES
------------
    Standard library only (os, shutil, re, zipfile, urllib.request, datetime)
"""

import os
import shutil
import re
import zipfile
import urllib.request
from datetime import date, datetime

# -----------------------------
# PATH CONFIGURATION
# -----------------------------
# Root of the grapeDRF_doppler_model project
BASE_DIR = "/home/bob/grapeDRF_doppler_model"

# Library directory: where input ZIPs are stored and extracted folders are kept
LIBRARY_DIR = os.path.join(BASE_DIR, "data/library")

# Pipeline working directory: where data is copied for active processing
DATA_ROOT = os.path.join(BASE_DIR, "data/psws_grapeDRF")

# Config directory: contains per-callsign .ini files with UT timestamps
CONFIG_DIR = os.path.join(BASE_DIR, "config")

# Full path to the IRI2016 apf107.dat solar/geomagnetic indices file used by
# PHaRLAP/PyLap. This file must cover the dataset date or IRI will substitute
# fill values (-111), leading to bad ionospheric profiles or a pathfinder crash.
APF107_PATH = "/home/bob/PyLap_Project/PHARLAP/pharlap_4.5.0/dat/iri2016/apf107.dat"

# Daily-updated source for apf107.dat provided by the University of New Brunswick
# ECHAIM project on behalf of the IRI Working Group. Updated at ~08:00 EST daily.
APF107_URL = "https://chain-new.chain-project.net/echaim_downloads/apf107.dat"


# -----------------------------
# APF107 COVERAGE CHECK
# -----------------------------
def apf107_last_date(path):
    """
    Parse apf107.dat and return the last date covered as a date object.

    apf107.dat contains one row per day of observed F10.7 solar flux and
    Ap geomagnetic index. Each row starts with: YY MM DD ...
    where YY is a 2-digit year (50-99 = 1950-1999, 00-49 = 2000-2049).

    Args:
        path (str): Full path to apf107.dat

    Returns:
        date: The last date present in the file

    Raises:
        ValueError: If the file is empty or the last line cannot be parsed
    """
    last_line = None
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line    # keep updating — we want the final non-empty line

    if last_line is None:
        raise ValueError("apf107.dat appears to be empty")

    parts = last_line.split()
    yy, mm, dd = int(parts[0]), int(parts[1]), int(parts[2])

    # Convert 2-digit year to 4-digit year
    year = 2000 + yy if yy < 50 else 1900 + yy

    return date(year, mm, dd)


def check_and_update_apf107(ut_year, ut_month, ut_day):
    """
    Verify that apf107.dat covers the requested UT date.

    If the file does not exist, exit with an error message.
    If it exists but does not cover the UT date, warn the user and offer
    to download an updated copy from ECHAIM. If the user declines, exit —
    proceeding with an incomplete apf107.dat will cause IRI to substitute
    fill values, leading to bad ionospheric profiles or a pathfinder crash.

    After a successful download, re-checks coverage. If even the fresh file
    falls short (e.g. very recent date not yet published by ECHAIM, which
    typically has a 1-2 day lag), warns again and gives the user a final
    chance to continue or abort.

    Args:
        ut_year  (int): Year component of the dataset UT timestamp
        ut_month (int): Month component of the dataset UT timestamp
        ut_day   (int): Day component of the dataset UT timestamp
    """
    # --- Check file exists ---
    if not os.path.isfile(APF107_PATH):
        print(f"\nERROR: apf107.dat not found at:\n  {APF107_PATH}")
        print(f"Please obtain a current copy from:\n  {APF107_URL}")
        exit(1)

    # --- Parse last date in file ---
    try:
        last = apf107_last_date(APF107_PATH)
    except Exception as e:
        # If we cannot parse the file, warn but allow the loader to continue —
        # a parse failure here should not block the user outright.
        print(f"\nWARNING: Could not parse apf107.dat to check coverage: {e}")
        return

    run_date = date(ut_year, ut_month, ut_day)
    print(f"\napf107.dat coverage: up to {last.strftime('%Y-%m-%d')}"
          f"  |  Requested UT date: {run_date.strftime('%Y-%m-%d')}")

    # --- Coverage OK ---
    if run_date <= last:
        print("apf107.dat covers this date — OK")
        return

    # --- Coverage gap: warn user ---
    days_short = (run_date - last).days
    print(f"\nWARNING: apf107.dat does not cover {run_date.strftime('%Y-%m-%d')} "
          f"(file ends {days_short} day(s) earlier on {last.strftime('%Y-%m-%d')}).")
    print("IRI will use fill values for missing indices, which may cause")
    print("pathfinder errors or produce unreliable ionospheric ray traces.")

    # --- Offer download ---
    confirm = input("Download updated apf107.dat from ECHAIM now? (y/n) [y]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        # User declined — cannot safely proceed
        print("Aborted — apf107.dat must cover the requested UT date to proceed.")
        exit(1)

    # --- Attempt download ---
    # Download to a .tmp file first so the original is not overwritten unless
    # the download completes successfully (atomic replace via os.replace).
    print("Downloading apf107.dat...")
    try:
        tmp_path = APF107_PATH + ".tmp"
        urllib.request.urlretrieve(APF107_URL, tmp_path)
        os.replace(tmp_path, APF107_PATH)   # atomic replace on POSIX systems

        # Verify the newly downloaded file actually covers the requested date
        new_last = apf107_last_date(APF107_PATH)
        print(f"apf107.dat updated successfully — now covers up to {new_last.strftime('%Y-%m-%d')}")

        if run_date > new_last:
            # This can happen if the dataset date is very recent and ECHAIM
            # has not yet published indices for it (typically a 1-2 day lag)
            print(f"WARNING: Even the updated file does not cover {run_date.strftime('%Y-%m-%d')}.")
            print("IRI results for this date may be degraded.")
            confirm2 = input("Continue anyway? (y/n) [n]: ").strip().lower()
            if confirm2 not in ("y", "yes"):
                print("Aborted by user.")
                exit(1)

    except Exception as e:
        print(f"ERROR: Download failed: {e}")
        # Clean up partial download if present
        if os.path.exists(APF107_PATH + ".tmp"):
            os.remove(APF107_PATH + ".tmp")
        exit(1)


# -----------------------------
# FIND INPUT SOURCES
# -----------------------------
def find_sources(include_folders_if_zips=True):
    """
    Scan LIBRARY_DIR and return a list of available input sources.

    Sources are returned as (type, name) tuples where type is either
    'zip' or 'folder'.

    ZIP files (OBS*.zip) are always listed. Pre-extracted folders
    (ch0_*) are listed alongside ZIPs when include_folders_if_zips=True,
    or only when no ZIPs are present.

    This allows the user to re-use a previously extracted dataset without
    re-extracting the ZIP, which is useful when re-running the pipeline
    with a different callsign or config.

    Args:
        include_folders_if_zips (bool): If True, list folders even when
            ZIPs are available. Default True.

    Returns:
        list of (str, str): [(type, name), ...]
    """
    zips = []
    folders = []

    for item in os.listdir(LIBRARY_DIR):
        full_path = os.path.join(LIBRARY_DIR, item)
        if item.startswith("OBS") and item.endswith(".zip"):
            zips.append(("zip", item))
        elif os.path.isdir(full_path) and item.startswith("ch0_"):
            folders.append(("folder", item))

    if zips:
        return zips + folders if include_folders_if_zips else zips
    else:
        return folders


# -----------------------------
# USER SELECTION
# -----------------------------
def select_source(sources):
    """
    Display available sources and prompt the user to select one by index.

    Args:
        sources (list): List of (type, name) tuples from find_sources()

    Returns:
        tuple: (type, name) of the selected source
    """
    print("\nAvailable sources:\n")
    for i, (stype, name) in enumerate(sources):
        print(f"  {i}: [{stype}] {name}")
    idx = int(input("\nSelect index: "))
    return sources[idx]


# -----------------------------
# ZIP TIMESTAMP PARSING
# -----------------------------
def parse_zip_datetime(zip_name):
    """
    Extract the UT datetime components from a GRAPE ZIP filename.

    Expected filename format: OBSYYYY-MM-DDTHH-MM.zip
    Example: OBS2026-04-20T00-00.zip -> (2026, 4, 20, 0, 0)

    Args:
        zip_name (str): ZIP filename (basename only, not full path)

    Returns:
        tuple of int: (year, month, day, hour, minute)

    Raises:
        ValueError: If the filename does not match the expected pattern
    """
    match = re.search(r"OBS(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})", zip_name)
    if not match:
        raise ValueError(f"Invalid ZIP filename format: {zip_name}")
    return tuple(map(int, match.groups()))


def format_dt(year, month, day, hour, minute):
    """
    Convert individual datetime components to a compact 12-digit string.

    This format is used in folder names and pipeline timestamps.

    Args:
        year, month, day, hour, minute (int): datetime components

    Returns:
        str: e.g. '202604200000'
    """
    return f"{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}"


# -----------------------------
# CALLSIGN INPUT
# -----------------------------
def get_callsign():
    """
    Prompt the user to enter a callsign.

    The callsign is used to:
        - Name the extracted dataset folder (ch0_<CALLSIGN>_<timestamp>)
        - Locate the correct config file (<CALLSIGN>_config.ini)
        - Name the pipeline working directory (ch0_<CALLSIGN>)

    Returns:
        str: Uppercase callsign, defaults to 'N6RFM' if blank
    """
    callsign = input("\nEnter callsign (default N6RFM): ").strip().upper()
    return callsign if callsign else "N6RFM"


# -----------------------------
# ZIP EXTRACTION (FLATTENED)
# -----------------------------
def extract_zip_flat(zip_file, callsign):
    """
    Extract a GRAPE ZIP into a named folder with the top-level directory
    stripped out (flattened).

    GRAPE ZIPs typically contain a single top-level folder (e.g. 'ch0/')
    that wraps all the data. This function detects and removes that wrapper
    so the extracted folder contains the data files directly, matching the
    structure expected by the pipeline.

    The destination folder is named: ch0_<CALLSIGN>_<YYYYMMDDHHMM>
    and is created inside LIBRARY_DIR for later re-use without re-extraction.

    Args:
        zip_file (str): ZIP filename (basename, not full path)
        callsign (str): Callsign used to name the output folder

    Returns:
        tuple: (folder_name, (year, month, day, hour, minute))
            folder_name (str): Name of the created folder (not full path)
            datetime tuple (ints): Extracted from the ZIP filename
    """
    year, month, day, hour, minute = parse_zip_datetime(zip_file)
    dt_str = format_dt(year, month, day, hour, minute)
    folder_name = f"ch0_{callsign}_{dt_str}"
    dest_path = os.path.join(LIBRARY_DIR, folder_name)
    os.makedirs(dest_path, exist_ok=True)

    zip_path = os.path.join(LIBRARY_DIR, zip_file)
    print(f"\nExtracting ZIP -> {folder_name}")

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Identify a single top-level folder to strip during extraction.
        # If multiple top-level entries exist, no stripping is done.
        top_levels = set()
        for m in zip_ref.infolist():
            if m.filename.strip():
                top_levels.add(m.filename.split('/')[0])
        top_level = list(top_levels)[0] if len(top_levels) == 1 else None

        # Extract each file, skipping directory entries and stripping the
        # top-level folder prefix from paths when a single wrapper is detected
        for m in zip_ref.infolist():
            if m.is_dir():
                continue
            parts = m.filename.split('/')
            if top_level and parts[0] == top_level:
                parts = parts[1:]   # strip the top-level folder
            if not parts:
                continue
            target = os.path.join(dest_path, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zip_ref.open(m) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)

    print("Extraction complete (flattened)")
    return folder_name, (year, month, day, hour, minute)


# -----------------------------
# CONFIG UPDATE
# -----------------------------
def update_config(callsign, year, month, day, hour, minute):
    """
    Update the UT timestamp in the callsign's config .ini file.

    Searches for a line starting with 'ut' and replaces it with the
    new timestamp in the format expected by pathfinder:
        ut = [YYYY,MM,DD,HH,MM]

    All other lines in the config file are preserved unchanged.

    Args:
        callsign (str): Used to locate <CALLSIGN>_config.ini
        year, month, day, hour, minute (int): New UT timestamp values

    Raises:
        FileNotFoundError: If the config file does not exist
    """
    config_file = os.path.join(CONFIG_DIR, f"{callsign}_config.ini")
    if not os.path.exists(config_file):
        raise FileNotFoundError(config_file)

    new_ut = f"ut = [{year},{month},{day},{hour},{minute}]"

    with open(config_file) as f:
        lines = f.readlines()

    with open(config_file, "w") as f:
        for line in lines:
            if line.strip().startswith("ut"):
                f.write(new_ut + "\n")   # replace the ut line
            else:
                f.write(line)            # preserve everything else unchanged

    print(f"Updated config: {config_file}")


# -----------------------------
# CLEAR WORKING DIRECTORY
# -----------------------------
def clear_destination(dest_dir):
    """
    Prompt the user to confirm, then remove all contents of dest_dir.

    This is necessary before copying new data into the pipeline working
    directory to avoid mixing data from different datasets or dates.
    Directories are removed recursively; files are unlinked individually.

    Args:
        dest_dir (str): Full path to the directory to clear

    Exits:
        Calls exit(0) if the user does not confirm.
    """
    confirm = input(f"\n⚠️  Clear {dest_dir}? (y/n): ").lower()
    if confirm != "y":
        print("Aborted")
        exit(0)
    for item in os.listdir(dest_dir):
        path = os.path.join(dest_dir, item)
        if os.path.isdir(path):
            shutil.rmtree(path)      # recursively remove subdirectories
        else:
            os.unlink(path)          # remove individual files


# -----------------------------
# COPY DATA TO WORKING DIRECTORY
# -----------------------------
def copy_data(folder_name, callsign):
    """
    Copy the extracted dataset from LIBRARY_DIR into the pipeline working
    directory, replacing any existing contents after user confirmation.

    The source is:      LIBRARY_DIR/<folder_name>/
    The destination is: DATA_ROOT/ch0_<CALLSIGN>/

    Subdirectories are copied recursively; individual files are copied
    with metadata preserved (shutil.copy2).

    Args:
        folder_name (str): Name of the extracted folder in LIBRARY_DIR
        callsign (str): Used to name the destination directory

    Returns:
        str: Full path to the destination directory
    """
    src = os.path.join(LIBRARY_DIR, folder_name)
    dest = os.path.join(DATA_ROOT, f"ch0_{callsign}")
    os.makedirs(dest, exist_ok=True)

    clear_destination(dest)   # prompt before overwriting

    print(f"\nCopying -> {dest}")
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dest, item)
        if os.path.isdir(s):
            shutil.copytree(s, d)    # recursive directory copy
        else:
            shutil.copy2(s, d)       # file copy preserving timestamps
    print("Copy complete")
    return dest


# -----------------------------
# MAIN PROGRAM
# -----------------------------
def main():
    """
    Main entry point. Orchestrates the full data loading sequence:

        1. Scan LIBRARY_DIR for available ZIPs and extracted folders
        2. Prompt user to select a source
        3. Prompt for callsign
        4. Extract ZIP if selected (skip extraction if folder already exists)
        5. Update UT timestamp in the callsign's config .ini file
        6. Verify apf107.dat covers the dataset date; offer download if not
        7. Copy dataset into pipeline working directory

    The apf107.dat check (step 6) intentionally runs after the config update
    (step 5) so the UT date is known, and before the working directory copy
    (step 7) so the user can resolve the issue without having already cleared
    and overwritten their working data.

    All exceptions are caught and printed without a traceback to keep
    the output clean for non-developer users.
    """
    try:
        # Step 1: Find available sources
        # Folders are shown alongside ZIPs so the user can re-use a previously
        # extracted dataset without re-extracting the ZIP.
        sources = find_sources(include_folders_if_zips=True)
        if not sources:
            print("No ZIPs or folders found in library directory:")
            print(f"  {LIBRARY_DIR}")
            return

        # Step 2: User selects source
        stype, name = select_source(sources)

        # Step 3: Get callsign
        callsign = get_callsign()

        # Step 4: Extract ZIP or parse timestamp from existing folder name
        if stype == "zip":
            # Extract and flatten the ZIP; returns folder name and datetime tuple
            folder_name, (y, m, d, h, mi) = extract_zip_flat(name, callsign)
        else:
            # Folder already extracted — parse timestamp from folder name suffix
            # Expected suffix: 12-digit YYYYMMDDHHMM e.g. ch0_N6RFM_202604200000
            folder_name = name
            match = re.search(r"(\d{12})$", name)
            if not match:
                raise ValueError(
                    f"Cannot parse timestamp from folder name: {name}\n"
                    "Expected format: ch0_<CALLSIGN>_YYYYMMDDHHMM"
                )
            dt = match.group(1)
            y  = int(dt[0:4])
            m  = int(dt[4:6])
            d  = int(dt[6:8])
            h  = int(dt[8:10])
            mi = int(dt[10:12])

        # Step 5: Write UT timestamp into config file
        update_config(callsign, y, m, d, h, mi)

        # Step 6: Verify apf107.dat covers the dataset date.
        # Runs before copy_data so the user can fix the issue before the
        # working directory is cleared and overwritten.
        check_and_update_apf107(y, m, d)

        # Step 7: Copy dataset into pipeline working directory
        dest = copy_data(folder_name, callsign)

        print(f"\n✅ READY -> {dest}")

    except Exception as e:
        print(f"ERROR: {e}")


# -----------------------------
# ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    main()
