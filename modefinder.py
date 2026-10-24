#!/usr/bin/env python3
#  Name modefinder.py
#
# Purpose : To take the output csv file from pathfinder.py of rays landing within a specified proximity to a receiver, 
#           identify the propagation modes using huristics applied to the ray trace data
#           and output a csv file of time series with mode designator column, and a color for each mode in ./output/csv/receivercallsign/
#           Plots of the initial elevation angle and apogee of the first hop for each ray arriving at the receiver with time are plotted and saved
#           in ./output/plots/receivercallsign/*
#           Two command line arguments, the callsign subdirectory designator and the *pathfinder.csv file to process
#    For use with HamSCI PSWS analysis.
#    Derivation of Doppler and plotting are next stages.
#    Gwyn Griffiths G3ZIL September 2025

import  numpy as np
from numpy import genfromtxt
import csv
import sys
import os
import configparser
from datetime import datetime
import statistics
import pylab as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import matplotlib.units as munits

callsign = sys.argv[1]                     # callsign for subdirectory name
csv_in_file = sys.argv[2]                  # *pathfinder.csv file   

# Set up arrays etc

# set up base directory, and paths for csv in/out, config and heuristics files 
base_directory='./'
csv_dir=os.path.join(base_directory,'output','csv',callsign)
plot_dir=os.path.join(base_directory,'output','plots',callsign)   # plots go into a subdirectory by callsign
heuristics_dir=os.path.join(base_directory,'config')

csv_in_name=csv_dir + '/' + csv_in_file + '_pathfinder.csv'
csv_out_name=csv_dir + '/' + csv_in_file + '_modefinder.csv'
heuristics_file=heuristics_dir + '/heuristics.ini'
config_file=heuristics_dir + '/' + callsign + '_config.ini'
if not os.path.exists(plot_dir):
  os.makedirs(plot_dir)

# Read in heuristics file, which is general not path or frequency specific
config = configparser.ConfigParser()
config.read(heuristics_file)                # use a text editor to modify and add to the heuristics file 

min_apogee_E=config['propagation'].getint('min_apogee_E')
max_apogee_E=config['propagation'].getint('max_apogee_E')
min_apogee_F=config['propagation'].getint('min_apogee_F')
min_diff_h=config['propagation'].getint('min_hdashF-hF')
max_diff_h=config['propagation'].getint('max_hdashF-hF')
elev_diff_lo_hi=config['propagation'].getfloat('elev_diff_lo_hi')
sep_EloEhi=config['propagation'].getfloat('sep_EloEhi')

# Read frequency in MHz, tx callsign and plot parameters from the specific config.ini file
config.read(config_file)
freq=config['settings'].getfloat('freq')
tx=config['metadata'].get('tx')
legend_loc=config['plots'].get('legend')

# read in the *pathfinder.csv file, first the header, then the actual data, NOT reading the time column
header = genfromtxt(csv_in_name, delimiter=',', dtype=str, max_rows=1)
path_data = genfromtxt(csv_in_name, delimiter=',', skip_header=1)[:,1:]
print("Data, config and heuristics read in")

# check if the E/F 'boundary' in the heuristics is sensible for this particular dataset
# if not suggest the user alter the setting to that listed manually and rerun
(count,l_edge)=np.histogram(path_data[:,3],42,range=(80,500))   # bin the apogee between 80 and 500 km in 10 km bins
zeros=np.asarray(np.where(count == 0))       # find indicies where there are no apogees, looking for E F gap.
e_f_boundary=(np.min(zeros[zeros>3]))*10+80  # finds index for lowest empty height above bin 3, i.e.> 120 km then scale to height
print("The heuristics E max and F min are: ", max_apogee_E,min_apogee_F, " the data suggests:", e_f_boundary, e_f_boundary+1)
if abs(max_apogee_E-e_f_boundary) > 5:
   print("This suggests you should manually alter the values in the heuristics file and rerun modefinder")

###################################
# Time column read as a string, then convert to a python datetime object in new array 'date'
time_str=genfromtxt(csv_in_name, delimiter=',', skip_header=1, usecols=0, dtype=str)
date=np.empty(len(time_str), dtype=object)
for i in range(0,len(time_str)):
  date[i] = datetime.strptime(time_str[i], '%Y-%m-%d %H:%M:%S')

##############################################
# Classify to a propagation mode codified as:
# 1E 2E 1F 2F 1Ehi 2Ehi 1Fhi 2Fhi for starters
##############################################

# Setup arrays
n_traces=len(time_str)                 # number of rows, time intervals, to process

p_mode=np.empty(n_traces, dtype='U5')  #  character array to hold mode designator
color=np.empty(n_traces,dtype='U10')   # character array to hold a color name for each and every elevaltion spot
E_median=np.empty(n_traces)                  # we'll calcuate 1E median initial elevation to help with 1E assignment

# Could be streamlined by using elif, but keep at its simplest for now
# Helps my clarity (!) of thought for each of the propagation modes 
# First pass look for 1E
for i in range (0,n_traces):
  if path_data[i,0] == 1:
    if path_data[i,3] > min_apogee_E and path_data[i,3] < max_apogee_E:
      p_mode[i] = '1E'

# Second pass look for 2E
for i in range (0,n_traces):
  if path_data[i,0] == 2:
    if path_data[i,3] > min_apogee_E and path_data[i,3] < max_apogee_E:
      p_mode[i] = '2E'

# Third pass look for 1F
for i in range (0,n_traces):
  if path_data[i,0] == 1:
    if path_data[i,3] > min_apogee_F:
      p_mode[i] = '1F'

# Fourth pass look for 2F
for i in range (0,n_traces):
  if path_data[i,0] == 2:
    if path_data[i,3] > min_apogee_F and path_data[i,4] > min_apogee_F:
      p_mode[i] = '2F'

# Mixed 2-hop modes: first hop F, second hop E ('2FE'), and the reverse ('2EF')
for i in range (0,n_traces):
  if path_data[i,0] == 2 and p_mode[i] == '':
    if path_data[i,3] > min_apogee_F and min_apogee_E < path_data[i,4] < max_apogee_E:
      p_mode[i] = '2FE'
    elif min_apogee_E < path_data[i,3] < max_apogee_E and path_data[i,4] > min_apogee_F:
      p_mode[i] = '2EF'

# Fifth pass look for 1F that are high rays
for i in range (0,n_traces):
  if path_data[i,0] == 1:
    if time_str[i] == time_str[i-1]:
      if p_mode[i] == '1F' and p_mode[i-1] == '1F':
        if (path_data[i,1]-path_data[i-1,1]) > elev_diff_lo_hi:
          p_mode[i]='1Fhi'

# sixth pass look for 2F that are high rays
for i in range (0,n_traces):
  if path_data[i,0] == 2:
    if time_str[i] == time_str[i-1]:
      if p_mode[i] == '2F' and p_mode[i-1] == '2F':
        if (path_data[i,1]-path_data[i-1,1]) > elev_diff_lo_hi:
          p_mode[i]='2Fhi'

# seventh pass look for 1E that are high rays
for i in range (0,n_traces):
  if path_data[i,0] == 1:
    if time_str[i] == time_str[i-1]:
      if p_mode[i] == '1E' and p_mode[i-1] == '1E':
        if (path_data[i,1]-path_data[i-1,1]) > elev_diff_lo_hi:
          p_mode[i]='1Ehi'

# eighth pass look for 2E that are high rays
for i in range (0,n_traces):
  if path_data[i,0] == 2:
    if time_str[i] == time_str[i-1]:
      if p_mode[i] == '2E' and p_mode[i-1] == '2E':
        if (path_data[i,1]-path_data[i-1,1]) > elev_diff_lo_hi:
          p_mode[i]='2Ehi'

# ninth pass reassess 1E rays for being high high rays, where sep_EloEhi is from the heuristics file and can be set there
# Some 1Ehi misclassified as 1E because there was no normal (low) 1E at that time
# Form the median initial elevation for those classified as 1E (inc those actually 1Ehi)
# and check if elevation > median+x, if so, reclassify as 1Ehi
index=0                         # calculate median only for mode = 1E
for i in range (0,n_traces):
  if path_data[i,0] == 1:
    if p_mode[i] == '1E':
     E_median[index]=path_data[i,1]
     index=index+1
if np.min(E_median) > min_apogee_E:
  e_median=statistics.median(E_median[0:index-1])
  for i in range (0,n_traces):
    if path_data[i,0] == 1:
      if p_mode[i] == '1E' and path_data[i,1] > (e_median+sep_EloEhi):
        p_mode[i]='1Ehi'
        #print("corrected 1E to 1Ehi at ", time_str[i])
# Debug code
unassigned = np.where(p_mode == '')[0]
print(len(unassigned), "unassigned rays")
for i in unassigned:
  print(time_str[i], path_data[i,0:5])   # hops, elev, virt ht, apogee, 2nd hop apogee
  
print("Assignment to modes completed")
#for i in range (0,n_traces): 
#  print(time_str[i],p_mode[i])

##################################################
# Plot initiatl elevation angles arriving at rx classified by mode
##################################################

# set up colours depending on mode type, this is a great feature of the scatter plot 
# using like colors for low and hi trace pairs
# see https://matplotlib.org/stable/users/explain/colors/colors.html for names
for i in range (0,n_traces): 
  if p_mode[i] == '1F':
    color[i]='firebrick'
  elif p_mode[i] == '2F':
    color[i]='blue'
  elif p_mode[i] == '1E':
    color[i]='green'
  elif p_mode[i] == '2E':
    color[i]='purple'
  elif p_mode[i] == '1Fhi':
    color[i]='red'
  elif p_mode[i] == '2Fhi':
    color[i]='cyan'
  elif p_mode[i] == '1Ehi':
    color[i]='lime'
  elif p_mode[i] == '2Ehi':
    color[i]='orchid'
  elif p_mode[i] == '2FE':
    color[i]='orange'
  elif p_mode[i] == '2EF':
    color[i]='gold'
  else:
    color[i]='k'

fig, ax = plt.subplots()     
plt.suptitle("Initial elevation of " + str(freq) +" MHz rays leaving " + tx + " arriving at " + callsign, fontsize=12)

scatter=ax.scatter(date, path_data[:,1], c=color, s=5)  # path_data[:,1] is initial elevation, color is an array, each row has own color

plt.xlabel("Time (Month-Day Hour UTC)")
plt.ylabel("Initial elevation (˚)")
plt.ylim(0,60)
plt.gcf().set_size_inches(8, 4, forward=True)
plt.tight_layout()

# Create legend manually, this took a bit of finding
black_patch = mpatches.Patch(color='firebrick', label='1F')
blue_patch = mpatches.Patch(color='blue', label='2F')
green_patch = mpatches.Patch(color='green', label='1E')
purple_patch = mpatches.Patch(color='purple', label='2E')
grey_patch = mpatches.Patch(color='red', label='1Fhi')
cyan_patch = mpatches.Patch(color='cyan', label='2Fhi')
lime_patch = mpatches.Patch(color='lime', label='1Ehi')
orchid_patch = mpatches.Patch(color='orchid', label='2Ehi')
orange_patch = mpatches.Patch(color='orange', label='2FE')
gold_patch = mpatches.Patch(color='gold', label='2EF')

plt.legend(handles=[black_patch, blue_patch, green_patch, purple_patch, grey_patch, cyan_patch, lime_patch, orchid_patch, orange_patch, gold_patch],\
   ncol=3, loc=legend_loc)

# save the elevation figure
plt.savefig(plot_dir + "/" + csv_in_file + "_elev.png", dpi=600)

# now the apogee figure
fig, ax = plt.subplots()
plt.suptitle("Apogee heights of " + str(freq) +" MHz rays leaving " + tx + " arriving at " + callsign, fontsize=12)

scatter=ax.scatter(date, path_data[:,3], c=color, s=5)  # path_data[:,1] is initial elevation, color is an array, each row has own color

plt.xlabel("Time (Month-Day Hour UTC)")
plt.ylabel("Apogee (km)")
plt.ylim(50,400)
plt.gcf().set_size_inches(8, 4, forward=True)
plt.tight_layout()

plt.legend(handles=[black_patch, blue_patch, green_patch, purple_patch, grey_patch, cyan_patch, lime_patch, orchid_patch],\
   ncol=2, loc=legend_loc)
# save and show the elevation figure
plt.savefig(plot_dir + "/" + csv_in_file + "_apogee.png", dpi=600)

plt.show()
print("Plots generated and saved")

# output the original data plus classification and color into file *_modefinder.csv in ./output/csv/callsign dir
with open(csv_out_name, 'w', encoding='UTF8',) as out_file:     # open a csv file for write
  writer=csv.writer(out_file)
  writer.writerow(["Date,Hops,p_mode,color,Init_elev,one_hop_virt_ht,one_hop_apogee,2nd hop apogee,gnd_range,phase_path,geo_path,pylap_doppler"])

  for i in range (0,n_traces):
    writer.writerow([time_str[i], path_data[i,0], p_mode[i], color[i],path_data[i,1], path_data[i,2], path_data[i,3],\
       path_data[i,4], path_data[i,5], path_data[i,6], path_data[i,7], path_data[i,8]])

print("modefinder csv file  written")
