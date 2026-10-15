# grapeDRF_doppler_model — N6RFM convenience additions

**All credit for this project goes to Gwyn Griffiths, G3ZIL.**
This repository is a copy of his work, and the model, the science and the documentation are all his:

**➡️ https://github.com/g3zil/grapeDRF_doppler_model**

Please start there. Installation (PyLap/PHaRLAP, Python environment, ClickHouse), concepts, configuration and the meaning of every parameter are documented in the upstream README, and this page does not repeat any of it. Questions about the method belong with the upstream project.

The files here are small conveniences I added for running the pipeline day to day with my own GRAPE station data. If you find them useful, take them. They build on, and do not replace, the upstream tools.

---

## What I added

### Running the pipeline

| File | What it does |
|---|---|
| `drf_data_loader_apf107_check.py` | Replaces upstream's `drf_data_loader.py`. Lets you pick a GRAPE `OBS*.zip` (or an already-extracted folder) from `data/library/`, extracts it, writes the dataset's UT timestamp into your `config/<CALLSIGN>_config.ini`, and copies the data into `data/psws_grapeDRF/ch0_<CALLSIGN>/`. It also checks that your `apf107.dat` covers the dataset date and offers to download a current copy, since a stale file makes IRI use fill values and can crash pathfinder. |
| `run_pipeline.py` | Interactive wrapper that runs the steps after the loader in order: pathfinder, modefinder, synthspec, spectrogram. It lists your configs, asks you to confirm the UT timestamp, checks that pathfinder produced its output, and reports the time each step took. |
| `grape_gui.py` | A Tkinter window that does what the two scripts above do, without the prompts: choose a data zip or folder, check and refresh `apf107.dat`, choose a config, pick which steps to run, and watch a live log with per-step timing and a Cancel button. Needs Tkinter (`sudo apt install python3-tk`) and can run the steps in your venv. Start it with `python3 grape_gui.py` from the project folder. |
| `modefinder_quiet.py` | `modefinder.py` without the on-screen plot windows, so it runs unattended. Plots are still saved to `output/plots/`. |
| `synthspec_ch.py`, `synthspec_ch_quiet.py` | ClickHouse-database versions of `synthspec.py`, with a quiet variant for batch runs. |
| `grape_fft_spectrogram_ch.py`, `grape_fft_spectrogram_ch_quiet.py` | ClickHouse-database versions of `grape_fft_spectrogram.py`, with a quiet variant for batch runs. |

### Plotting and configuration

| File | What it does |
|---|---|
| `plot_n6rfm_grapeDRF_2024eclipse.py` | The 2024 eclipse plotting script set up for station N6RFM (10 MHz by default), handling DRF files that contain only a single frequency. |
| `third_party/DRF_processing/plotspectrum_V4a.py` | A quick-look spectrum plotter for a single GRAPE DRF day, by W. Engelke, AB4EJ (University of Alabama). Copied from https://github.com/HamSCI/DRF_processing with one small change (`np.complex` replaced by `complex` for newer NumPy) and used under its GPL-3.0 license (included alongside the file). |
| `config/N6RFM_config.ini` | An example station config. Copy it, rename it `<YOURCALL>_config.ini`, and edit it for your own station. |
| `data/apf107.dat`, `data/Kp_ap_Ap_SN_F107.txt` | Solar and geomagnetic index files, for convenience. Refresh them for newer dates. |

### Typical run

```bash
python3 drf_data_loader_apf107_check.py          # pick the day's data, sets UT in your config
python3 run_pipeline.py                          # pathfinder, modefinder, synthspec, spectrogram
```

or use the window instead: `python3 grape_gui.py`

or step by step, as `run_pipeline.py` does it:

```bash
./pathfinder.sh N6RFM_config.ini 1400
python3 modefinder_quiet.py N6RFM 202603230000
python3 synthspec_ch_quiet.py N6RFM 202603230000 DB
python3 grape_fft_spectrogram_ch_quiet.py ch0_N6RFM 0 0 24 DB
```

The meaning of these arguments is explained in the upstream README.

---

## Before you use these

- **Edit the paths.** `run_pipeline.py` and `drf_data_loader_apf107_check.py` have path settings near the top (`CONFIG_DIR`, `BASE_DIR`, `APF107_PATH`) that point at my machine. Change them to match where you installed the project and PHaRLAP.
- **ClickHouse password.** The `_ch` scripts read the database password from an environment variable rather than from the code:
  ```bash
  export CLICKHOUSE_PASSWORD='<your actual password>'
  ```
  Set up ClickHouse itself by following Appendix A of the upstream README.
- **No data is included.** GRAPE `OBS*.zip` files and extracted DRF folders are not in this repo. Put your zips in `data/library/`. Upstream's sample data zips are also not in this repo's current files, so get them from the upstream project if you want to follow its tutorial.
- **Other upstream files are untouched**, including `pathfinder`, `synthspec.py`, `grape_fft_spectrogram.py` and the heuristics file.

## Troubleshooting

Problems I ran into while setting this up, with the fix for each. For anything about the model itself, see the upstream README.

### The window will not start: `No module named tkinter`

Tkinter is a separate package on Debian/Ubuntu/Mint:

```bash
sudo apt install python3-tk
```

### ClickHouse is not running

`grape_gui.py` shows ClickHouse as running (green) or stopped (red). **Start** and **Stop** control it, and with **Auto-start if needed** ticked a run starts it for you and stops it again afterwards (only if the window started it). Starting and stopping asks for your password through the desktop's password prompt (`pkexec`). From a terminal the equivalent is:

```bash
sudo systemctl start clickhouse-server
```

### `Authentication failed: password is incorrect, or there is no user with such name`

The scripts log in as the user named in `get_client(...)` (look for `username=` in `synthspec_ch_quiet.py`), with the password taken from the `CLICKHOUSE_PASSWORD` environment variable. The usual causes:

- The variable holds an example value instead of your real password (for instance a placeholder copied from instructions). Put the real password in `~/.bashrc`.
- A terminal opened before you edited `~/.bashrc` still has the old value. Run `source ~/.bashrc`, or open a new terminal, and start `grape_gui.py` from there.

Check a login without printing the password (it should print your user name):

```bash
curl -s -H "X-ClickHouse-User: YOUR_USER" -H "X-ClickHouse-Key: $CLICKHOUSE_PASSWORD" 'http://localhost:8123/' --data 'SELECT currentUser()'; echo
```

The **Test** button next to ClickHouse in the window does a fuller check: it logs in the same way the scripts do and lists your databases and tables. The same check runs automatically before any run that uses the database, so a problem shows up before the long ray-tracing step.

### `Table psws.synth_spec does not exist` (`UNKNOWN_TABLE`)

The database `psws` can exist while the table is missing, for example on a new ClickHouse install or after the data folder was replaced. Synthspec then prints `Unable to connect or insert!`. The window marks that step as failed, and the **Test** check reports the missing table.

To see what the server has (a user with limited rights may not see every table, so an empty list is not proof):

```bash
clickhouse-client --user YOUR_USER --password "$CLICKHOUSE_PASSWORD" -q "SELECT database, name, total_rows FROM system.tables WHERE database NOT IN ('system','INFORMATION_SCHEMA','information_schema')" --format PrettyCompact
```

To create it, use the table definition in Appendix A of the upstream README. It is not repeated here so that there is only one copy to keep correct. If your clone has the upstream remote, you can print it directly:

```bash
git fetch upstream
git show upstream/main:README.md | sed -n '/CREATE DATABASE IF NOT EXISTS psws/,/ORDER BY/p'
```

Save the `CREATE DATABASE` and `CREATE TABLE` statements (leave out the stray heading line) in a file such as `/tmp/create_synth_spec.sql`, add `GRANT ALL ON psws.* TO YOUR_USER;` at the end, and run it as an administrator:

```bash
clickhouse-client --user default --multiquery < /tmp/create_synth_spec.sql
```

(Add `--password` if the `default` user has one.) Then confirm as your own user with `DESCRIBE TABLE psws.synth_spec`. The table only holds the synthetic spectra the pipeline generates, so after recreating it, rerun synthspec to refill it.

### The log says "Connected Not executed" or a step "Failed: database insert error"

`synthspec_ch_quiet.py` exits normally even when the database insert fails. The window watches its output for `Unable to connect or insert` and marks the step failed. Read the ClickHouse message just above it in the Output box; it is one of the problems in this section (login, missing table, or server not running).

### `clickhouse_connect` is not installed

The **Test** button reports this when the Python in the **Python (venv)** field has no ClickHouse client. Install it into that same Python:

```bash
/path/to/that/python -m pip install clickhouse-connect
```

If you use a virtual environment, point the **Python (venv)** field at its `bin/python`; the window uses it for modefinder, synthspec and the spectrogram, and puts it first on the path for `pathfinder.sh`. Start `grape_gui.py` itself with a Python that has Tkinter.

### `apf107.dat` is out of date, or the download fails (HTTP 404)

A stale `apf107.dat` makes IRI use fill values and can crash pathfinder. The window shows the last date the file covers and compares it with the data you selected. **Update from ECHAIM** downloads a fresh copy. The file lives on the E-CHAIM "Supplementary Support Software" page of the CHAIN site, and its address has moved before. If the download fails, open that page in a browser, copy the current `apf107.dat` link, and either start the window with it:

```bash
export APF107_URL='https://the-current-address/apf107.dat'
python3 grape_gui.py
```

or download the file yourself and use **Browse...** to point the window at it (PHaRLAP's `dat/iri2016/apf107.dat`).

### "No 'ut = [...]' line in this config"

The loader writes the dataset's UT into `config/<CALLSIGN>_config.ini`. A config for a station you have not loaded data for yet has no `ut` line. Select the data and press **Load selected data** first.

### Where are my results?

Each step lists the files it wrote in the Output box, and when a run finishes a results window opens. Close it and you can bring it back with **Show last results** (it is kept until you start the next analysis, even after closing the window). **Open results folder (output/)** opens the output folder. The synthetic spectra are in the ClickHouse table `psws.synth_spec`.

### Copying or saving the log

Select text in the Output box and press Ctrl+C (or use **Copy**, which copies everything when nothing is selected). **Save to file...** writes the log to a text file, and **Clear** empties it. Right-click gives the same options.

## Staying in step with upstream

```bash
git remote add upstream https://github.com/g3zil/grapeDRF_doppler_model.git
git fetch upstream
git merge upstream/main     # if README.md conflicts, keep this page's version
```

## Credits

- **Gwyn Griffiths, G3ZIL**: the grapeDRF Doppler model itself, and everything upstream of this page.
- **W. Engelke, AB4EJ**: `plotspectrum_V4a.py`.
- **Bob, N6RFM**: the convenience scripts on this page.
- **Claude (Anthropic)**: co-wrote `grape_gui.py` with N6RFM, and helped with the repository clean-up, the ClickHouse password handling and this README.

## Contact

Bob, N6RFM. Suggestions and corrections to my additions are welcome via GitHub issues.
