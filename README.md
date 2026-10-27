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
| `drf_data_loader_apf107_check.py` | Replaces upstream's `drf_data_loader.py`. Lets you pick a GRAPE `OBS*.zip` (or an already-extracted folder) from `data/library/`, extracts it, writes the dataset's UT timestamp into your `config/<CALLSIGN>_config.ini`, and copies the data into `data/psws_grapeDRF/ch0_<CALLSIGN>/`. It also checks that your `apf107.dat` covers the dataset date and offers to download a current copy (if the file is exactly one day short, it simply uses the previous day's values), since a stale file makes IRI use fill values and can crash pathfinder. |
| `run_pipeline.py` | Interactive wrapper that runs the steps after the loader in order: pathfinder, modefinder, synthspec, spectrogram. It lists your configs, asks you to confirm the UT timestamp, checks that pathfinder produced its output, and reports the time each step took. |
| `grape_gui.py` | A Tkinter window that does what the two scripts above do, without the prompts: choose a data zip or folder, check and refresh `apf107.dat`, choose a config, choose which of the station's frequencies to run (some or all), pick which steps to run, and watch a live log with per-step timing and a Cancel button. Needs Tkinter (`sudo apt install python3-tk`) and can run the steps in your venv. It shows the station's details from the data's metadata, and when `apf107.dat` is exactly one day short it uses the previous day's values automatically. A **Two-hop sidescatter...** button opens the window below. Start it with `python3 grape_gui.py` from the project folder. |
| `sidescatter_gui.py` | A Tkinter window for G3ZIL's two-hop sidescatter tools (`SS_sidescatter.sh`, `SS_sidescatter_plot.py`, `SS_animate.sh`). It reads and writes the same `config/<CALLSIGN>_config.ini` files as `grape_gui.py`, runs one time or an animation, and lists the pictures and data it produced. See [Two-hop sidescatter window](#two-hop-sidescatter-window). Start it with `python3 sidescatter_gui.py`, or from the button in `grape_gui.py`. |
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

and for the two-hop sidescatter tools: `python3 sidescatter_gui.py`

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

- **Tell it where `apf107.dat` is.** The scripts and the window find the project folder from where they sit, so there are no paths to edit. The one setting that depends on your install is PHaRLAP's `apf107.dat`, which defaults to `~/PyLap_Project/PHARLAP/pharlap_4.5.0/dat/iri2016/apf107.dat`. If yours is elsewhere, set `export APF107_PATH=/your/path/apf107.dat` before starting, or use **Browse...** in `grape_gui.py`.
- **ClickHouse password.** The `_ch` scripts read the database password from an environment variable rather than from the code:
  ```bash
  export CLICKHOUSE_PASSWORD='<your actual password>'
  ```
  Set up ClickHouse itself by following Appendix A of the upstream README.
- **No data is included.** GRAPE `OBS*.zip` files and extracted DRF folders are not in this repo. Put your zips in `data/library/`. Upstream's sample data zips are also not in this repo's current files, so get them from the upstream project if you want to follow its tutorial.
- **Other upstream files are untouched**, including `pathfinder`, `synthspec.py`, `grape_fft_spectrogram.py` and the heuristics file.

## Two-hop sidescatter window

`sidescatter_gui.py` is a window for G3ZIL's two-hop sidescatter tools (`SS_sidescatter.sh`, `SS_sidescatter_plot.py`, `SS_animate.sh`). It reads and writes the same `config/<CALL>_config.ini` files as `grape_gui.py`, so a station set up for the Doppler work is ready here too. Open it with the **Two-hop sidescatter...** button in `grape_gui.py`, or on its own:

```bash
python3 sidescatter_gui.py
```

- Choose the config, check or change the inputs (UT, frequency, R12, hops, elevation range, the two grid squares, azimuth step, contour maximum), then **Run sidescatter** for one time, or choose **Animation over time** (total minutes and interval; needs `ffmpeg`).
- Changed inputs are written back to the config, and the previous copy is kept as `<CALL>_config.ini.bak`. The scripts themselves write the path length, bearing and peak position back into the config; the window shows them.
- Results are listed in the window (double-click to open): pictures in `output/plots/SS/<CALL>/`, data in `output/csv/SS/<CALL>/`.
- The scripts need PyLap: start the window from a terminal where `PYTHONPATH` is set the way it is for `pathfinder.sh`. **Check setup** reports a missing `PYTHONPATH`, missing Python modules, or missing `ffmpeg`.
- Upstream limits apply: Northern Hemisphere only, and the northernmost station must be below 58 N. The window checks this before it starts.

## Troubleshooting

Problems I ran into while setting this up, with the fix for each. For anything about the model itself, see the upstream README.

### The window will not start: `No module named tkinter`

Tkinter is a separate package on Debian/Ubuntu/Mint:

```bash
sudo apt install python3-tk
```

### ClickHouse is not running

`grape_gui.py` shows ClickHouse as running (green) or stopped (red). **Start** and **Stop** control it, **Test** checks the login, **Clear table** empties the synthetic-spectra table `psws.synth_spec` (after asking; it starts and stops ClickHouse for you if needed), and with **Auto-start if needed** ticked a run starts it for you and stops it again afterwards (only if the window started it). Starting and stopping asks for your password through the desktop's password prompt (`pkexec`). From a terminal the equivalent is:

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

### Synthspec stops with `TypeError: '<' not supported between instances of 'NoneType' and 'str'`

The modefinder results contain rays it could not give a mode to (a blank `p_mode`; in October data these were two-hop rays around midday whose first hop peaks near 130 km, between the E and F layers). They cannot be sorted or coloured. `synthspec_ch*.py` now leaves them out of the synthetic spectrum and prints how many it skipped; they stay in the modefinder csv.

### The synthetic traces are drawn hours late on the spectrogram

Seen on computers whose clock is not on UTC (for example US Central time, where the traces came out 5 hours late in summer and 6 in winter). The database driver reads a time with no time zone as this computer's local time, so the UTC times written by `synthspec_ch*.py` were stored shifted and the spectrogram overlay drew them shifted. The model-only plot (`*_synth_doppler.png`) was always right. `synthspec_ch*.py` and `grape_fft_spectrogram_ch*.py` now mark the times as UTC. Rows written before the fix are still shifted, so press **Clear table**, then run Synthspec and Spectrogram again for the days you want.

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

**A second source, SERENE.** If the ECHAIM server is down or slow, `grape_gui.py` can download the file from the University of Birmingham's SERENE service instead. Register at the SERENE "Indices" page (serene.bham.ac.uk/resources/Indices/), which gives you a download link or curl command containing your own token. In the window press **SERENE link...** and paste it; the token is kept only in `grape_gui_settings.json` (readable by you only, and not committed to git) and is never written to the log. Then pick **ECHAIM** or **SERENE** next to **Update**. If the chosen source fails, the other is tried automatically, and the window shows which one supplied the file. The previous file is kept as `apf107.dat.bak`, and a download that looks truncated or is not an `apf107.dat` (for example an expired token) is refused and leaves your file untouched.

**One day short is handled for you.** If `apf107.dat` ends exactly one day before the date of your data (common, because the daily file lags), `grape_gui.py` and `drf_data_loader_apf107_check.py` add a row for the missing day using the previous day's values, keep the old file as `apf107.dat.bak`, and carry on. The window shows this in orange. Two or more days short still asks whether to download a fresh copy.

### `ig_rz.dat` is out of date

IRI also reads `ig_rz.dat` (monthly sunspot and ionospheric indices) from the same `dat/iri2016` folder as `apf107.dat`. It changes slowly and runs well into the future, so it rarely needs replacing, but when the month of your data is past the end of its range IRI may stop or give poor results. `grape_gui.py` shows the range under the `apf107.dat` line (green when covered, orange for the last month in the file, red when not covered) and asks before a run that would need it. **Where to get ig_rz.dat...** lists places to download a current copy (SERENE, ECHAIM, IRI); save it over the old one after copying that to `ig_rz.dat.bak`, then press **Re-check**.

### "No 'ut = [...]' line in this config"

The loader writes the dataset's UT into `config/<CALLSIGN>_config.ini`. A config for a station you have not loaded data for yet has no `ut` line. Select the data and press **Load selected data** first.

### Stations that record several frequencies

Some GRAPE stations record several frequencies in one Digital RF dataset (one `ch0` folder, one column per frequency), while others record a single frequency. `grape_gui.py` reads the station's metadata and shows the callsign, grid square and frequencies as soon as you select a zip or folder. The **Frequencies** row then lists the frequencies in the data that is loaded, and you can tick some or all of them.

The model works on one frequency at a time. The config's `freq = ...` line feeds pathfinder and synthspec, and the spectrogram step takes the position of the frequency in the data. For every frequency you tick, the window sets `freq` in the config, works out the position, runs the steps you chose, and puts the config's original `freq` line back afterwards. Two things follow from that:

- **It takes longer.** Each frequency runs its own pathfinder ray tracing, so six frequencies take about six times as long as one.
- **Files are overwritten between frequencies.** The pathfinder and modefinder CSVs and the synthspec plots have the same names for every frequency. When more than one frequency is run, the window saves a copy of each frequency's files in `output/by_frequency/<callsign>_<time>/<freq>MHz/`; the files directly in `output/` belong to the last frequency run. The synthetic spectra in ClickHouse keep a `frequency` column, so they are not mixed up. The spectrogram images include the frequency in their names.

If you skip Pathfinder, the window refuses to run modefinder or synthspec for a frequency other than the one the existing pathfinder output was computed for. Path settings in the config (`tx`, `tx_grid`, `distance`, `bearing`, ...) apply to every frequency you tick, so for frequencies that come from different transmitters, run them separately with the right config.

The spectrogram step reads `config/<callsign in the data>_config.ini`, so the callsign in the data must match a config file name. The window fills the callsign box from the data and warns you if that config does not exist.

The frequency list is read with `h5py` in the Python named in the **Python (venv)** field, which is the Python that already has the Digital RF packages. If the list shows "unknown", load the data first, or check that Python can `import h5py`.

### The station line says "Callsign not recorded in this data"

Older GRAPE data (for example 2024 recordings) has no callsign or grid square in its metadata, only the frequency and the position. The window then shows the position and leaves the **Callsign** box alone, so type the callsign yourself. Newer data records the callsign and grid, and the box fills in automatically.

### Sidescatter window: `KeyError: 'PYTHONPATH'` or "PYTHONPATH is not set"

`SS_sidescatter.py` uses `PYTHONPATH` to find PyLap. Start `sidescatter_gui.py` (or `grape_gui.py`, which can open it) from a terminal where `PYTHONPATH` is set the way it is for `pathfinder.sh`, then use **Check setup**.

### Sidescatter window: "northernmost station must be below 58 N" or "Northern Hemisphere"

Upstream's sidescatter tools handle only the Northern Hemisphere and stations below 58 N. The window checks both grid squares before it starts. Check `tx_grid` and `rx_grid` in the config.

### Sidescatter window: my config lost its comments

The upstream scripts rewrite the whole config file when they save the path length, bearing and peak position, which drops comments. The window keeps the copy from before the run as `config/<CALL>_config.ini.bak`.

### Sidescatter window: "No landing coordinates" or a missing picture

The ray tracing step wrote nothing, so there is nothing to plot. Read the PyLap messages just above in the Output box. A missing `pylap` or an `apf107.dat` problem is the usual cause (see the apf107 entry above).

### The spectrogram stops with `OSError: Data gaps found`

Older versions stopped at the first gap in the Digital RF data (a few missing minutes are common). `grape_fft_spectrogram_ch*.py` now reads the continuous pieces and leaves the missing samples empty, so the gaps show as blank stripes in the spectrogram. The log says "Data gaps found - reading the continuous blocks only" and "Samples present: ... (96.x %)". The synthetic traces are drawn through the gaps because the model does not know about them. The original `grape_fft_spectrogram.py` still stops at a gap.

### Modefinder says "the data suggests: 370 371"

`modefinder` compares the E/F height in `config/heuristics.ini` (`max_apogee_E`, `min_apogee_F`) with the first empty 10 km bin it finds in the apogee heights. When the heights run on without a gap (mostly F-layer rays) that bin is far above the E layer, so there is nothing to change. `modefinder_quiet.py` now says "no clear E/F gap" in that case and only asks you to edit the heuristics when it finds a real gap more than 5 km from your setting.

### Where are my results?

Each step lists the files it wrote in the Output box, and when a run finishes a results window opens. Close it and you can bring it back with **Show last results** (it is kept until you start the next analysis, even after closing the window). **Open results folder (output/)** opens the output folder. The synthetic spectra are in the ClickHouse table `psws.synth_spec`.

### Copying or saving the log

Select text in the Output box and press Ctrl+C (or use **Copy**, which copies everything when nothing is selected). **Save to file...** writes the log to a text file, and **Clear** empties it. Right-click gives the same options. Every pipeline run is also written automatically to `output/logs/run_<config>_<UTC>_<time>.log` (the last log line gives the path), so nothing is lost when the window closes.

## Staying in step with upstream

```bash
git remote add upstream https://github.com/g3zil/grapeDRF_doppler_model.git
git fetch upstream
git merge upstream/main     # if README.md conflicts, keep this page's version
```

## Credits

- **Gwyn Griffiths, G3ZIL**: the grapeDRF Doppler model itself, and everything upstream of this page.
- **Gwyn's Oct 2026 updates**, merged here on 24 Oct 2026: UTC handling of the ClickHouse timestamps (`synthspec.py`, `grape_fft_spectrogram.py`) and the mixed two-hop modes 2FE and 2EF with their legend patches (`modefinder.py`). The `_ch` / `_quiet` copies carry the same changes.
- **W. Engelke, AB4EJ**: `plotspectrum_V4a.py`.
- **Bob, N6RFM**: the convenience scripts on this page.
- **Claude (Anthropic)**: co-wrote `grape_gui.py` and `sidescatter_gui.py` with N6RFM, and helped with the repository clean-up, the ClickHouse password handling and this README.

## Contact

Bob, N6RFM. Suggestions and corrections to my additions are welcome via GitHub issues.
