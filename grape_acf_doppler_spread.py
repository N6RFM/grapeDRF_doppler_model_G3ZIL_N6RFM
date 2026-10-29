# Program to read in the metadata and IQ data from a Grape receiver in digital_rf format
# Simple initial analysis using complex autocorrelation at one lag as single Doppler peak algorithm. 
# Also estimates S+N level and frequency spread. Sends frequency, spread and signal level to csv file
# See https://github.com/MITHaystack/digital_rf/blob/master/docs/DigitalRF2.0.pdf for digital_rf stuff
# hamsci.org/sites/default/files/Grape/2023-09-22%20Getting%20Started%20with%20Data%20Reporting%20Using%20A%20PSWS_V7.1.pdf
# also has details.
#
# Data for the examples in this folder are in channels ch0_Callsign in this directory:
# ch0_G4HZX is G4HZX    29 March 2025 partial eclipse use 15 MHz
# ch1_W2NAF is W2NAF     8 April 2024 use 25 MHz
# ch2_N8GA is N8GA      26 July 2024 use 10 MHz

# Script needs four command line arguments:
# 1. Directory to process 2. Index of array of frequency to plot
# 3. Start time in hour   4. Stop time in hour
#     e.g. python3 grape_digital_RF_metadata.py ch0_G4HZX 6 8 13

# Last modified 7 July 2025 for QEX article, to handle Grape 1 DRF with less metadata, and by callsign output directories
# Gwyn Griffiths G3ZIL with thanks for Nathaniel Frissell W2NAF for metadata data_dict code

import digital_rf as drf
import numpy as np
import pylab as plt
import csv                         # to write csv file for plotting and comparison in Excel
from datetime import datetime
import pytz
import sys
import os
import maidenhead as mh           # lat lon to locator, used if locator not present, eg Grape 1 DRF metadata

import load_metadata              # this is a module in this directory to read digital RF metadata

base_directory='./'
data_dir=os.path.join(base_directory,'data','psws_grapeDRF')
output_dir=os.path.join(base_directory,'output')

do = drf.DigitalRFReader(data_dir)

# check for four command line arguments
n = len(sys.argv)
if n<=4:
   print ("Rerun with channel name, frequency index and start and stop hours as four command line arguments")
   exit()
if n>5:
   print ("Rerun with channel name, frequency index and start and stop hours as four command line arguments")
   exit()

# assign first three command line arguments to variables, check time span and that end time > start time + one hour
channel=sys.argv[1]
freq_index=int(sys.argv[2])    # Get index from metadata frequency list e.g. use grape_digital_RF_metadata.py or inspect PSWS spectrogram
hours_offset=int(sys.argv[3])  # Start time for data input and plot

if hours_offset < 0 or hours_offset > 23:
   print ("Start time (hours) must be between 0 and 23")
   exit()

if (float(sys.argv[4])-float(sys.argv[3])) <1:
   print ("Stop time must be at least one hour greater than start time")
   exit()

#

################################################
# Get metadata then set up constants and arrays
################################################
# Call module function to read in metadata, draws on data_dict code from Nathaniel Frissell 

(date,freqList,s1,s0,fs,theCallsign,grid,lat,lon) = load_metadata.load_grape_drf_metadata(data_dir,channel)

# Check sensible and available command line start and stop times
if int(sys.argv[4]) >= ((s1-s0)/10)/3600:
   print ("End time specified beyond end of data set: Reading to last sample in data set")
   length=int(np.floor(((((s1-s0)/10)/3600)-hours_offset)*60))    # calculate length of data in minutes
else:
   length=int(np.floor((int(sys.argv[4])-hours_offset)*60))    # calculate length of data in minutes to be sure in data set

print("Length of selected period ",length, " minutes")

frequency=freqList[freq_index]        # This comes from command line argument and metadata frequency list

########################################
# Set up constants and arrays
########################################
csv_dir=os.path.join(output_dir,'csv',theCallsign)
if not os.path.exists(csv_dir):
  os.makedirs(csv_dir)
csv_filename=csv_dir+'/ACF_FWL_data_' + "_" + str(frequency) + "MHz_" + date + ".csv"    # 

time_window=60                               # 60 seconds is default for each processed data ensemble, but could be changed for special uses
length=int(np.floor(length*(60/time_window))) # in case time window changed, then alter length accordingly

m_samples=int(fs*time_window)
n_samples=int(length*m_samples+1)            # total length of input data in samples
s=s0+hours_offset*3600*fs                    # calculate start time given command line start time offset

freq=np.empty(n_samples)
spread= np.empty(n_samples)
level=np.empty(n_samples)
time=np.empty(n_samples)
real=np.empty(m_samples)
dB_level=np.empty(length)
data=np.zeros(m_samples)

########################################
# digital_rf read in code
########################################

do.get_channels()

s_int = int(s)                  # s may be numpy longdouble, digital_rf wants plain ints
n_int = int(n_samples)
data = np.full(n_int, np.nan, dtype=np.complex64)

blocks = do.get_continuous_blocks(s_int, s_int + n_int, channel)
if len(blocks) == 0:
    print("No data at all in the requested period for channel ", channel)
    sys.exit()

for b_start, b_len in blocks.items():
    lo = max(int(b_start), s_int)
    hi = min(int(b_start) + int(b_len), s_int + n_int)
    if hi <= lo:
        continue
    chunk = do.read_vector(lo, hi - lo, channel)
    if len(freqList) > 1:
        chunk = chunk[:, freq_index]
    data[lo - s_int : hi - s_int] = chunk

missing = 100.0 * np.isnan(data).sum() / n_int
print("Percentage of requested period with no data: %.1f%%" % missing)

print ("First data sample is ", data[0])

with open(csv_filename, 'w', encoding='UTF8',) as out_file:     # open a csv file for write, write metadata, headers then data rows
 writer=csv.writer(out_file)
 writer.writerow(["Date","Callsign","Grid","Freq (MHz)","Lat","Lon"])
 writer.writerow([date,theCallsign,grid,str(frequency),lat,lon])
 writer.writerow(["Hour (UTC)","Doppler (Hz)","Spread (mHz)","Level (dB)"])

# Analysis outer and inner loops
 for j in range (0,length):
    k=int(j*m_samples)
    time[j]=round(((j)/(60*(60/time_window)))+hours_offset,5) # time in hours, rounded for csv file

    # the lag-1 term reads one sample beyond the minute, hence m_samples+1
    if np.isnan(data[k:k+m_samples+1]).any():
        freq[j]=np.nan
        spread[j]=np.nan
        dB_level[j]=np.nan
        writer.writerow([time[j],'','',''])   # blank cells show as gaps in Excel charts
        continue

    R_T0=0
    R_Ts=0
    for i in range (0, m_samples):
        R_T0=R_T0+data[i+k]*np.conjugate(data[i+k])
        R_Ts=R_Ts+data[i+k]*np.conjugate(data[i+1+k])
        real[i]=np.real(data[i+k])
    freq[j]=round(-(1/(2*np.pi*0.1))*np.angle(R_Ts),5)
    level=np.std(real)+np.average(real)
    dB_level[j]=round(20*np.log10(level),2)
    spread[j]=(1.414/(2*np.pi*0.1))*np.sqrt(np.abs(np.log((R_T0/np.abs(R_Ts)))))*1000
    spread[j]=round(spread[j],0)
    writer.writerow([time[j],freq[j],spread[j],dB_level[j]])

###########################################
# Plots of Doppler, Spread and Level
###########################################
plot_dir=os.path.join(output_dir,'plots',theCallsign)   # plots go into a subdirectory by callsign
if not os.path.exists(plot_dir):
  os.makedirs(plot_dir)

xaxis_title="Time on " + date + " (hours UTC)"

end_hours=hours_offset+length/60  # for plot time axis limits

fig, ax= plt.subplots()   #

plt.plot(time[0:length],freq[0:length],'.',color="black", label='Doppler frequency (Hz)')  
plt.suptitle("ACF Doppler " + theCallsign + " at " + str(frequency) + " MHz", fontsize=12)
plt.xlabel(xaxis_title)
#plt.xlim(hours_offset,end_hours)
plt.ylabel("Doppler shift (Hz)")
plt.gcf().set_size_inches(8, 3, forward=True)
plt.tight_layout()
plt.savefig(plot_dir +"/ACF_Doppler" + "_" + str(frequency) + "MHz_" + date + ".png", dpi=600)

fig, ax= plt.subplots()

plt.plot(time[0:length],spread[0:length],'.',color="black", label='Frequency spread (mHz)')
plt.suptitle("ACF Spread " + theCallsign + " at " + str(frequency) + " MHz", fontsize=12)
plt.xlabel(xaxis_title)
#plt.xlim(hours_offset,end_hours)
plt.ylim(0,3000)
plt.ylabel("Frequency spread (mHz)")
plt.gcf().set_size_inches(8, 3, forward=True)
plt.tight_layout()
plt.savefig(plot_dir +"/ACF_Spread" + "_" + str(frequency) + "MHz_" + date + ".png", dpi=600)

fig, ax= plt.subplots()

plt.plot(time[0:length],dB_level[0:length],'.',color="black", label='Signal level (dB)')  
plt.suptitle("ACF S+N Level " + theCallsign + " at " + str(frequency) + " MHz", fontsize=12)
plt.xlabel(xaxis_title)
#plt.xlim(hours_offset,end_hours)
plt.ylabel("Signal+Noise level (dB)")
plt.gcf().set_size_inches(8, 3, forward=True)
plt.tight_layout()
plt.savefig(plot_dir +"/ACF_Level" + "_" + str(frequency) + "MHz_" + date + ".png", dpi=600)

plt.show()
