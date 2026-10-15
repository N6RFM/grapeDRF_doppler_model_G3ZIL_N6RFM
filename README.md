# Installation 
This software has been tested on Ubuntu Linux and Mac OS systems.

### Download
You need to clone the package from github.com and run the software in the grapeDRF_doppler_model sub-directory. 
```
cd ~
git clone https://github.com/g3zil/grapeDRF_doppler_model.git
cd ~/grapeDRF_doppler_model
```
Execute all further commands in the ~/grapeDRF_doppler_model directory.
Updates can be downloaded with:
```
git pull
```

## Requirements
### Open environment
Install the dependencies in requirements.txt:
```
python -m pip install -r requirements.txt
```
This code has been tested with python 3.10.16 in clean conda virtual environments on Mac OS 15.3.1 and Ubuntu Linux 22.04.5 LTS. It has also been tested with python 3.10.14 on Mac OS 10.14.6.

### Externally managed environment
The code is the same but the modules installation requires extra steps. It has been tested with python 3.12.3 on Ubuntu Linux 24.04 LTS. A virtual environment is created and activated in the directory ~/grapeDRF_doppler_model/.venv, the latest version of pip is installed, and the required modules installed. Check your python3 version and use instead of 3.12 in the first line below if appropriate.
```
sudo apt install python3.12-venv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```
### Synthetic spectrogram scripts
The synthetic spectrogram scripts (see below) require the ray tracing package PyLap to be installed from [GitHub](https://github.com/HamSCI/PyLap). 
Note that as of September 2025 PyLap only assuredly works with PHaRLAP 4.5.0. There may be issues with its setup.sh in a protected environment.\
Optionally, the synthspec.py script can output its data into a postgresql database currently on the localhost. Contact the author for details if you are interested in this option.

# W2NAF Eclipse Plotting
To make a plot, run:
```
python plot_w2naf_grapeDRF_2024eclipse.py
```

This will automatically create an `output/` directory and the desired plot in `output/w2naf_2024eclipse/20240408.0000_20240409.0000_w2naf_WDgrape_20_15_10_5.png`.


![image](20240408.0000_20240409.0000_w2naf_WDgrape_20_15_10_5.png)

# G3ZIL digital RF Doppler plotting and analysis
One-day data files for the examples below are in directories ./data/psws_grapeDRF/ch0_* where * is a PSWS reporting station callsign.
Current examples include: ch0_G4HZX, ch0_N8GA, ch0_W2NAF.
Plots are output to ./output/plots/* where * is the callsign, and csv data files to ./output/csv/*

### Listing metadata
To list the available metadata for a station the data channel name is the single command line argument, run:
```
python3 grape_digital_RF_metadata.py ch0_G4HZX
```
### Plotting a simple spectrogram
The script requires four command line arguments, channel name, frequency index (from the metadata) start and end times in integer hours UTC. 
For example, with frequency index 6 for 15 MHz between 8 and 13 UTC, run
```
python3 grape_fft_spectrogram.py ch0_G4HZX 6 8 13
```
An optional fifth command line argument DB produces a second plot combining the as-received spectrogram with a synthetic spectrogram derived from ray tracing - see [Part 4](#part-4-overlaying-as-received-and-synthetic-spectrograms) in the Synthetic Spectrograms section below.

### Time domain Doppler analysis using complex autocorrelation
The script plots time series of signal+noise (S+N)level, Doppler shift and frequency spread.
The Doppler shift and spread estimates are only applicable where the spectrum is unimodal.
The same four command line arguments are required, run:
```
python3 grape_acf_doppler_spread.py ch0_G4HZX 6 8 14 
```
### Plot single interval spectrum, identifying N peaks
The script calculates a spectrum and fits Ricker wavelets with a Continuous Wavelet Transform (CWT) to identify peaks.
The four command line arguments are, channel name, frequency index, time of the spectrum in decimal hours and N the number of peaks to find, run:
```
python3 grape_fft_CWT_single_plot.py ch0_W2NAF 8 14.5 2
```
### Experimental multiple Doppler tracking
This script is under development and may fail with data-dependent errors. Two (July 2025) Dopppler spectrum peaks in each time interval are identified from CWF fits. A small training set where each peak is correctly assigned to one of the N propagation modes is used with a forecasting tool to predict the next value for set A. Whichever data value is closest to the prediction in the next interval is assigned to set A et seq. 
The script needs four command line arguments, channel name, frequency index, time of the spectrum in decimal hours and duration in minutes:
```
python3 grape_fft_CWT_tracking_prophet.py ch0_W2NAF 8 14.4 80
```
Here are the example plots, first the raw data and second the assigned to mode:

![Figure 9 traces raw and tracked](https://github.com/user-attachments/assets/ae258af9-0bc6-40ac-8c47-98eaaf18a03b)

# G3ZIL Synthetic spectrograms
This set of scripts comprises steps for deriving and plotting a synthetic Doppler spectrogram by running a series of ray trace simulations using PyLap while also identifying the propagation modes.\
Limitation: The pathfinder.sh script start time in its config.ini file and the command line duration in minutes must remain within one day UTC. That is, not span 00:00 UTC.

### Part 1 Finding all rays from the transmitter that land at a receiver via great circle paths using 2D ray tracing
* pathfinder.py   Code to run PyLap ray tracing at a single specified time over a sweep of elevations incrementing by 0.005˚ to find all ray elevations landing at a receiver from a given transmitter location. The code genrates a csv file in the output/csv/receivercallsign subdirectory. The PyLap configuration is specified in a config file with a naming convention receivercallsign_config.ini in the config subdirectory. An example is given below. The config file name and specified time in YYmmddHHMM format form the two command line parameters to pathfinder.py:
```
python3 pathfinder.py ./config/N8GA_config.ini 202407260000
```
* pathfinder.sh   Bash code that runs a sequence of pathfinder.py for an interval specified in minutes. Currently the code is set to run ray traces at five minute steps over the specified number of minutes. Hence the following command line will produce a csv file with data every five minutes for 30 minutes:
```
./pathfinder.sh N8GA_config.ini 30 
```
* config.ini   This example is for WWV Fort Collins, CO to N8GA Ohio:
  
[settings]\
ut = [2024,7,26,0,0]\
r12 = 120\
freq = 10\
tx_grid = DN70LQ\
rx_grid = EN80EE\
nhops = 2\
elev_start = 2\
elev_stop = 45\
[metadata]\
tx = WWV\
rx = N8GA

An example csv file output for one five minute interval is:

"Date, Hops, Init_elev, one_hop_virt_ht, one_hop_apogee, 2nd hop apogee, gnd_range, phase_path, geo_path, pylap_doppler"\
2024-07-26 00:00:00,1,2.55,102.292,96.046,nan,1813.148,1834.42,1835.975,-0.173\
2024-07-26 00:00:00,1,13.68,238.466,138.634,nan,1813.192,1826.658,1865.551,-4.324\
2024-07-26 00:00:00,2,33.07,nan,218.983,221.31,1813.605,1942.765,2077.204,-7.736

_Note that there is probably an issue (September 2025) with PyLap's own Doppler computation._

### Part 2 Assigning a propagation mode to each ray that landed at the receiver
* modefinder.py After reading in the csv file of ray parameters generated by pathfinder.py modefinder.py tests each ray against a set of heuristics (mental short cuts, rules of thumb) to asssign each ray a great circle propagation mode. Recall that these are outputs of 2D ray tracing. Currently the code tests each ray against eight possible modes:\
1E 1E high ray\
2E 2E high ray\
1F 1F high ray\
2F 2F high ray\
where the initial numeral is the number of hops and high rays are rays with steeper elevation angles that penetrate higher into the ionosphere and hence can also land at the same distance as a lower elevation ray. Some of these high rays will be ducted, or Pedersen rays. A test for those will be added to the heuristics.\
The current set of heuristics, in heuristics.ini in the config subdirectory is:\
[propagation]\
min_apogee_E=85\
max_apogee_E=150\
min_apogee_F=151\
min_hdashF-hF=45\
max_hdashF-hF=85\
elev_diff_lo_hi=0.5\
sep_EloEhi=5\
; September 2025 heights are in km, elevations in degrees

The script is called with two command line arguments, the subdirectory callsign and start datetime as in pathfinder.py:
```
python3 modefinder.py N8GA 202407260000
```
The output is a csv file in the ./output/csv/callsign subdirectory with mode designators and a color for each mode and a plot in the ./output/plots/callsign subdirectory. The plot is a scatterplot of initial ray elevation angles arriving at the receiver against time with the rays color coded as to propagation mode. An example plot is:
<img width="800" height="400" alt="Initial_Elevation" src="https://github.com/user-attachments/assets/f9822650-579f-4df8-8e3b-f0c060a73ec9" />

### Part 3 Synthesizing a Spectrum: Calculate Doppler shift for each propagation mode
* sythspec.py The script reads in the csv file generated by modefinder.py, calculates Doppler shift fom the difference in phase path between successive time intervals and outputs a csv file and optionally uploads to a database.\
The script is called with two mandatory command line arguments, the subdirectory callsign and start datetime as in modefinder.py. An optional third argument DB triggers data upload to a local Clickhouse database (See Appendix A below for installing Clickhouse). Note: If using the DB option you must be in the protected environment:
```
python3 synthspec.py N8GA 202407260000
```
The raw Doppler estimate, rate of change of phase path, is adjusted to account for the actual ground landing distance. This is because jitter, with an rms of about 400 metres in the ray landing distance with ray elevation increments of 0.005˚ add noise to the Doppler estimate. After this correction the assigned-to-mode Doppler shifts are (with a few outliers) smooth, as in this plot for the time interval of ray elevations above:

<img width="800" height="400" alt="WWV-N8GA_GG_doppler" src="https://github.com/user-attachments/assets/9979da4d-5730-480c-8eeb-cbaf968b8087" />

synthspec.py also calculates and plots the propagation delay separated by mode.

### Part 4 Overlaying as received and synthetic spectrograms
grape_fft_spectrogram.py can be used with an optional fifth command line argument DB to overlay as-received and synthetic spectrograms. The data for the synthetic spectrogram must already be in the local Clickhouse database. That is, script synthspec.py must have been run with the DB option and of course a local Clickhouse database configured as set out in Appendic A:
```
python3 grape_fft_spectrogram.py ch0_W2NAF 7 0 24 DB
```
produces the plot below. Of course there are several differences, but each likely tells us something about actual propagation compared with the climate of the International Reference Ionosphere.

<img width="800" height="300" alt="Spectrogram+Synth_10 0MHz_2024-04-08" src="https://github.com/user-attachments/assets/7e634813-69d2-46cc-8a6e-e9c58ae536b1" />

# G3ZIL Two-hop sidescatter computation and visualisation
This set of scripts that uses 3D PyLap ray tracing to model two-hop sidescatter using a simplified approach where a pseudo-transmitter is placed at the receiver and reciprocity is assumed. The product of transmitter and pseudo transmitter ray landing spots in 1˚ by 1˚ boxes is derived and plotted. \
The code automatically sets the bounding box for the ionosphere grid and the subsequent plotting suitable for the geometry of the transmitter and receiver locations.
Current limitations: Northern Hemisphere only.\
                     Northernmost of tx and rx must be below 58˚N else the grid would extend beyond the North Pole causing complications.\
                     Still working on automatic the metric amplitude scaling for the contour map for animations.

Plots are output to ./output/plots/SS/* where * is the callsign, and csv data files to ./output/csv/SS/*

### Part 1 Calculation of ray landing spots for transmitter and pseudo transmitter
If PyLap or any of its supporting modules are in a python protected environment then this script must be run in that protected environment.
A bash script SS_sidescatter.sh tests if a protected environment is present and if it is, it invokes it and runs the python script. Else the python script is run as is. SS_sidescatter.sh takes the same two command line arguments as SS_sidescatter.py.

python3 SS_sidescatter.py is used with two command line arguments, the config file name and specified time in YYmmddHHMM format. The conifig.ini file (example below) is an extended version of that used for 2D great circle paths (example below).
```
python3 SS_sidescatter.py ./config/W2NAF_config.ini 202409270000
```

* config.ini   This example is for CHU, Ottowa to W2NAF PA. Note that several parameters have 0 in the initial state.
  
Scripts write results for these parameters to be used by subsequent scripts. The elevation step interval is 1˚, azimuth scan is a full 360˚. Computer memory limits the azimuth resolution: here 3˚ is used for an 8 GB machine. 
  
[settings]\
ut = [2024,9,27,0,0]\
r12 = 114\
freq = 14.67\
tx_grid = FN25CH\
rx_grid = FN21EI\
nhops = 1\
elev_start = 3\
elev_stop = 45\
distance = 0\
bearing = 0\
[metadata]\
tx = CHU\
rx = W2NAF\
[plots]\
legend = upper right\
u_dopp_lim = 3\
l_dopp_lim = -3\
[3d_sidescatter]\
ray_inc = 3\
metric_max_lat = 0\
metric_max_lon = 0\
max_metric = 0

The output is file timestamp_ground_coords.csv in the ./output/csv/SS/callsign directory where timestamp is the second command line parameter and callsign is from the config file name. An example of a timestamp_ground_coords.csv is:


0,0.0,2,5.0,154.513,-4.461,70.004264,-75.479248\
0,0.0,3,6.0,158.077,-4.566,67.67416,-75.53916\
0,0.0,4,7.0,161.799,-4.697,65.972454,-75.570397

where the fields are: source (0=tx, 1=pseudo-tx at rx), ray bearing (˚), rayId, initial elevation (˚), apogee (km), PyLap Doppler, (Hz), landing spot lat (˚), Landing spot lon (˚).


### Part 2 Calculation and plotting of ray landing spots and sidescatter likelihood metric
python3 SS_sidescatter_plot.py takes three command line arguments, the config file name, specified time in YYmmddHHMM format and a frame number for when it is used with the bash script SS_animate.sh. In stand alone use the frame number is left to the user (max 999).
```
python3 SS_sidescatter_plot.py ./config/W2NAF_config.ini 202409270000 0
```
Two plot files are sent to the ./output/plots/SS/callsign directory: sidescatter.png is the plot of ray landing spots and 2F_sidescatter_metric_000.png is a contour map of the sidescatter likelihood metric. Here 000 in the file name is the frame number left padded to three digits.

Here is an example ray landing spot map for CHU to W2NAF on 14.67 MHz at 00:00 UTC on 27 September 2024:

<img width="560" height="480" alt="sidescatter" src="https://github.com/user-attachments/assets/d43d450e-58a0-46e0-9d3c-304c180825e2" />

And the plot of the sidescatter likelihood metric:

<img width="560" height="448" alt="2F_sidescatter_metric_000" src="https://github.com/user-attachments/assets/9a32c588-214e-4eae-9edf-42698a8203d4" />

### Part 3 Generate sidescatter metric image sequence and animation
SS_animate.sh is a shell script that runs SS_sidescatter.py and then SS_sidescatter_plot.py a user-defined number of times and at user-defined time intervals to generate multiple sidescatter likelihood metric plots and an mp4 animation of those frames. The files are stored in the ./output/plots/SS/callsign directory. Note that it can take minutes to generate each frame (e.g. 4 minutes on a 4-core i5 machine) The script takes three command line parameters, the config file name, the number of minutes total duration and the frame interval in minutes. Hence, this example gives simulations every 20 minutes for 360 minutes, that is should be 18 frames.
```
./SS_animate.sh W2NAF_config.ini 360 20
```
Note that ffmpeg (that geneates the mp4 file) can both insert and drop frames depending how many one has.
Here is an example animation:

https://github.com/user-attachments/assets/95268232-11b4-41ee-9da1-0c760e2c7cab

# Utilities
### drf_data_loader_apf107_check.py
Author: N6RFM + ChatGPT

**PURPOSE**

This script prepares GRAPE DRF datasets for use in the G3ZIL grapeDRF_doppler_model processing pipeline.

It supports TWO input types:
    1) Raw OBS*.zip files
    2) Already-extracted dataset folders (ch0_*)

The script ensures:
    - ZIPs are flattened correctly (no extra "ch0/" nesting)
    - Existing folders are reused without modification
    - Config file timestamp is updated
    - Working directory is refreshed cleanly

# Appendix A - Install Clickhouse database
Tested on Ubuntu 24.04 and Mint 22.3

Add Clickhouse repository
```
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg
curl -fsSL 'https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key' | sudo gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" | sudo tee /etc/apt/sources.list.d/clickhouse.list

sudo apt-get update
```
Install Clickhouse server and client
```
sudo apt-get install -y clickhouse-server clickhouse-client
```
Asks you to set up a password.

Start and enable services 
```
sudo systemctl enable clickhouse-server
sudo systemctl start clickhouse-server
```
Verify it's running
```
sudo systemctl status clickhouse-server
```
Log on to client
```
clickhouse-client --password='yourpassword'
```
Create database
```
CREATE DATABASE IF NOT EXISTS psws;
USE psws;

Create table
CREATE TABLE IF NOT EXISTS psws.synth_spec
(
    time            DateTime                COMMENT 'UTC timestamp',
    hops            Nullable(Float32)       COMMENT 'Number of hops',
    p_mode          String                  COMMENT 'Propagation mode',
    color           Nullable(String)        COMMENT 'Ray colour',
    init_elev       Nullable(Float32)       COMMENT 'Initial elevation degrees',
    one_hop_virt_ht Nullable(Float32)       COMMENT 'One hop virtual height km',
    one_hop_apogee  Nullable(Float32)       COMMENT 'One hop apogee km',
    sec_hop_apogee  Nullable(Float32)       COMMENT 'Second hop apogee km',
    gnd_range       Nullable(Float32)       COMMENT 'Ground range km',
    phase_path      Nullable(Float32)       COMMENT 'Phase path km',
    geo_path        Nullable(Float32)       COMMENT 'Geometric path km',
    pylap_doppler   Nullable(Float32)       COMMENT 'PyLap Doppler Hz',
    doppler         Nullable(Float32)       COMMENT 'Doppler shift Hz',
    time_of_flight  Nullable(Float32)       COMMENT 'Time of flight ms',
    frequency       String                  COMMENT 'Frequency MHz',
    tx              String                  COMMENT 'Transmitter station ID',
    rx              String                  COMMENT 'Receiver station ID'
)
ENGINE = ReplacingMergeTree()
ORDER BY (time, p_mode, frequency, tx, rx);
```
Verify the table
```
DESCRIBE TABLE psws.synth_spec;
```
Create an upload user, different to default user, chose a username instead of  placeholder 'username'  and a new password for  placeholder 'user_password' below
```
CREATE USER username IDENTIFIED WITH sha256_password BY 'user_password';
```
Grant access to just the psws database
```
GRANT ALL ON psws.* TO username;
```
Exit default user and then re-enter client using:
```
clickhouse-client --user=username --password='user_password'
```
Exit client for that user and re-enter as default user
```
clickhouse-client --password='default_user_password'
```
In another window, in the directory you use to run these scripts, enter the protected environment then install clickhouse-connect
```
pip install clickhouse-connect
```
Then, having run the pathfinder and modefinder scripts for N8GA run
```
git pull
synthspec.py N8GA 202407260000 DB
```
Test content of table in the clickhouse client window
```
select * from synth_spec; limit 10;
```

December 2025 - March 2026
