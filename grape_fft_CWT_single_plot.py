# Program to read in the metadata and IQ data from a Grape receiver in digital_rf format
# This is FFT variant experimenting with Continuous Wavelet Transform (CWT) plotting single one-minute time interval
# See https://github.com/MITHaystack/digital_rf/blob/master/docs/DigitalRF2.0.pdf for digital_rf stuff
# hamsci.org/sites/default/files/Grape/2023-09-22%20Getting%20Started%20with%20Data%20Reporting%20Using%20A%20PSWS_V7.1.pdf
# also has details.
# Data for the examples in this folder are in channels ch0_Callsign in this directory:
# ch0_G4HZX is G4HZX    29 March 2025 partial eclipse use 15 MHz
# ch1_W2NAF is W2NAF     8 April 2024 use 25 MHz
# ch2_N8GA is N8GA      26 July 2024 use 10 MHz

# Script needs four command line arguments:
# 1. Directory to process                     2. Index of array of frequency to plot
# 3. Observation time in decimal hours UTC    4. Number of peaks to find
#     e.g. python3 grape_fft_CWT_single_plot_QEX.py ch0_W2NAF 8 14.5 2

# Last modified 26 June 2025 for use with QEX article submission
# Gwyn Griffiths G3ZIL with thanks for Nathaniel Frissell W2NAF for metadata data_dict code

import digital_rf as drf
import numpy as np
import pylab as plt
from mpl_toolkits.axisartist.parasite_axes import HostAxes
from datetime import datetime
import pytz
import scipy
from scipy.fft import fft, fftfreq, fftshift
from scipy import signal
from scipy.signal import peak_widths, butter, filtfilt
import sys
import csv                         # to write csv file for plotting and comparison in Excel
import os

import load_metadata              # this is a module in this directory to read digital RF metadata

# set base directory for subsequent read operations and set up digital RF reader appropriate directory
base_directory='./'
data_dir=os.path.join(base_directory,'data','psws_grapeDRF')
output_dir=os.path.join(base_directory,'output')

do = drf.DigitalRFReader(data_dir)

# check for four command line arguments
n = len(sys.argv)
if n<=4:
   print ("Rerun with channel name, frequency index and spectrum time and number of peaks as four command line arguments")
   exit()
if n>5:
   print ("Rerun with channel name, frequency index and spectrum time and number of peaks as four command line arguments")
   exit()

# assign first three command line arguments to variables, check time span and that end time > start time + one hour
channel=sys.argv[1]
freq_index=int(sys.argv[2])    # Get index from metadata frequency list e.g. use grape_digital_RF_metadata.py or inspect PSWS spectrogram
hours_offset=float(sys.argv[3])  # Start time for data input and plot

if hours_offset < 0 or hours_offset > 23.9:
   print ("Time (hours) must be between 0 and 23.9")
   exit()

n_peaks=int(sys.argv[4])       # how many peaks to identify
length=1                       # we'll get just one minute of data at hours_offset

##########################################################
# Data processing functions
##########################################################
# local peak search: takes array index of CWF identified peak, does local search n bins either side for a true peak, returns index
def findLocalPeak (index, radius,level):
  # This method finds if the true local peak is to one side or other of CWF peak, and if so returns its index
  if index < 5 or index >594:
     return index                     # This is special case at either end near -5 and +5 Hz where we cannot search. Should not happen
  cwf_peak=level[index]
  for i in range (index-radius,index+radius+1):
     if level[i] > cwf_peak:
       index=i
       cwf_peak=level[i]
  return index

# Interpolate between frequency bins based on the weighted linear signal level at peak and either side
def freqInterpolate (index, radius, x, level):
  # This method interpolates in frequency space around true local peak returning an amplitude-weighted frequency
  if index < 5 or index >594:
     return x[index]                      # This is special case at either end near -5 and +5 Hz where we cannot search. Should not happen
  sum=0
  sum_weights=0
  for i in range (index-radius,index+radius+1):
      sum=sum+x[i]*10**(level[i]/20)      # Convert dB level to linear
      sum_weights=sum_weights+10**(level[i]/20)
  freq_interp=sum/sum_weights           # Interpolated peak frequency
  return freq_interp

def remove_adjacent(L):      # This function removes instances where a single peak has adjacent frequencies
  return [elem for i, elem in enumerate(L) if i == 0 or L[i-1]+1 != elem]

################################################
# Get metadata then set up constants and arrays
################################################

# Call module function to read in metadata, draws on data_dict code from Nathaniel Frissell 

(date,freqList,s1,s0,fs,theCallsign,grid,lat,lon) = load_metadata.load_grape_drf_metadata(data_dir,channel)

Hann_factor=1.63     # This is the energy correction factor # https://community.sw.siemens.com/s/article/window-correction-factors
time_window=60                       # 60 seconds
m_samples=int(fs*time_window)
n_samples=int(length*m_samples+1)    # how many samples at fs to read in
s=s0+hours_offset*3600*fs            # calculate start time given command line start time offset
frequency=freqList[freq_index]        # This comes from command line argument and metadata frequency list

freq_peaks=np.empty(n_peaks)   # to hold candidate peaks
level_peaks=np.empty(n_peaks)  # their signal level
spec_widths=np.empty(n_peaks)  # and width estimate between half peak amplitude

csv_dir=os.path.join(output_dir,'csv',theCallsign)
if not os.path.exists(csv_dir):
  os.makedirs(csv_dir)
csv_filename=csv_dir+'/one_FFT_data_' + "_" + str(frequency) + "MHz_" + date + ".csv"    #

########################################
# digital_rf read in code
########################################
do.get_channels()

unix_time=np.int64(s/10)
plot_time = datetime.fromtimestamp(unix_time,pytz.utc).strftime('%Y-%m-%dT%H%M%S')
plot_hour = datetime.fromtimestamp(unix_time,pytz.utc).strftime('%H:%M:%S')
print ("Analysis at ",plot_time)

# a single read; digital_rf raises OSError if the minute is not fully covered
try:
    data = do.read_vector(int(s), n_samples, channel)
except (OSError, ValueError) as e:
    print("Cannot read a complete minute of data starting at", plot_time, "UTC for channel", channel)
    print("Probably a gap in the digital_rf data, or a time outside the recorded range.")
    print("digital_rf says:", e)
    sys.exit(1)

if len(freqList) > 1:
    data=data[:,freq_index]          # select the sub-channel once, data is now 1D

######################
# Calculations
######################

# generate the x axis, which is frequency here 
x=fftshift(fftfreq(m_samples,1/fs))
# generate a Hann window of length m_samples (i.e. 600 samples)
window = signal.windows.hann(m_samples)
yf=fftshift(fft(data[0:m_samples]*window,norm="forward",overwrite_x=False)*Hann_factor)
yf=10*np.log10(np.abs(yf))  

with open(csv_filename, 'w', encoding='UTF8',) as out_file:     # open the csv file to write to
 writer=csv.writer(out_file)
 writer.writerow(["Frequency (Hz)","Spectrum Level (dB)"])
 for m in range(0,m_samples):
  writer.writerow([x[m],yf[m]])

######################################################################################
# Scipy find_peaks_cwt approach using continuous wavelet transform 
# https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks_cwt.html
#######################################################################################

peaks = signal.find_peaks_cwt(yf, widths=np.arange(2,4))  # 2,4 is empirical selection for one-hop widths
#print ("CWF", peaks)

peakind=remove_adjacent(peaks)                              # in case single peak shown as two adj freqs

# find the index at four successively reducing maxima: algorithm finds first max, finds freq and level at that index, then sets max that index to zero
# and iterates
n_found=n_peaks
for i in range(0,n_peaks):
    if len(peakind)==0:
        print("Only ", i, " peak(s) found, fewer than the ", n_peaks, " requested")
        n_found=i
        break
    max=np.argmax(yf[peakind])
    index_max=peakind[max]
    index_max_original=index_max
    freq_peaks[i]=x[index_max]
    level_peaks[i]=yf[index_max]
    print("\nCWF peak ",i," freq=", f"{freq_peaks[i]:.3f}", " Hz  at level=",f"{level_peaks[i]:.2f}"," dB at index ",index_max)

# Now call function to look either side to find true peak, revise and print output
    index_max=findLocalPeak(index_max,3,yf)
    freq_peaks[i]=float(x[index_max])
    level_peaks[i]=yf[index_max]
    print("Revised CWF peak ",i," freq=", f"{freq_peaks[i]:.3f}", " Hz  at level=",f"{level_peaks[i]:.2f}", " dB at index_max ",index_max)

# Now estimate spectrum widths between half max amplitudes for each peak
    tops=np.ones((1,), dtype=int)*int(index_max)
    (width,width_heights,left_ips,right_ips)=peak_widths(10**(yf/20),tops,rel_height=0.5, wlen=10)
    spec_widths[i]=width[0]/time_window
    print("Spec width w50 ",i," = ", f"{spec_widths[i]:.3f}", " Hz" )

# Now interpolate the true peak frequency based on correlation level either side
    freq_peaks[i]=freqInterpolate(index_max,2,x,yf)
    print("Interpolated CWF peak ",i," freq= ", f"{freq_peaks[i]:.3f}", " Hz" )

# Need to remove the peak just found from the array list of peaks
    to_remove=np.array([index_max_original])
    peakind=np.setdiff1d(peakind,to_remove)

###########################################
# Plots of Spectrum and peaks
###########################################
plot_dir=os.path.join(output_dir,'plots',theCallsign)   # plots go into a subdirectory by callsign
if not os.path.exists(plot_dir):
  os.makedirs(plot_dir)

# plot the spectrum with the identified peaks
fig, ax= plt.subplots()   #
plt.suptitle("FFT Doppler Spectrum " + theCallsign + " at " + str(frequency) + " MHz at " + plot_time, fontsize=12)
xaxis_title="Frequency (Hz)"

plt.plot(x, yf, color='black')
plt.xlabel(xaxis_title)
plt.ylabel("PSD uncalibrated (dB)")

plt.scatter(freq_peaks[0:n_found], level_peaks[0:n_found], s= 40, c = 'red') # plots red dots at the peaks

for i in range (0,n_found):     # annotates the peak frequencies
   ax.annotate('Pk (%.3f)'% (freq_peaks[i]), (freq_peaks[i], (np.random.uniform()*1)+(level_peaks[i])))

plt.savefig(plot_dir +"/One_Spectrum" + "_" + str(frequency) + "MHz_" + plot_time + ".png", dpi=600)

####

plt.show()
