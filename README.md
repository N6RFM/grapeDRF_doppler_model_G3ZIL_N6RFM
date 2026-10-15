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
  export CLICKHOUSE_PASSWORD='your-password'
  ```
  Set up ClickHouse itself by following Appendix A of the upstream README.
- **No data is included.** GRAPE `OBS*.zip` files and extracted DRF folders are not in this repo. Put your zips in `data/library/`. Upstream's sample data zips are also not in this repo's current files, so get them from the upstream project if you want to follow its tutorial.
- **Other upstream files are untouched**, including `pathfinder`, `synthspec.py`, `grape_fft_spectrogram.py` and the heuristics file.

## Staying in step with upstream

```bash
git remote add upstream https://github.com/g3zil/grapeDRF_doppler_model.git
git fetch upstream
git merge upstream/main     # if README.md conflicts, keep this page's version
```

## Contact

Bob, N6RFM. Suggestions and corrections to my additions are welcome via GitHub issues.
