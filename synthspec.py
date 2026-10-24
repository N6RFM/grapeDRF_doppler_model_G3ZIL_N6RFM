#!/usr/bin/env python3
#  Name synthspec_ch.py
#
# Purpose : To take the output csv file from modefinder.py of assigned-to-mode rays landing at the receiver, 
#           derive the Doppler shifts from rate of change of phase path and output a csv file of time series.
#           Also applies simople division by c, velocity of light, to obtain delay by mode.
#           Three command line arguments, the callsign subdirectory designator and the *modefinder.csv file to process
#           and the flag DB if the output is also to be uploaded to a clickhouse database on the localhost.
#           See comments in the final section on the database 
#    For use with HamSCI PSWS analysis.
#    Use in auto ident of propagation modes in spectrogram is next stage - the real challenge!
#    Gwyn Griffiths G3ZIL March 2026 based on earlier postgresql version

import  numpy as np
import csv
import sys
import os
import configparser
from datetime import datetime, timezone   # 24 Oct. 2026: timezone handling added
import statistics
import pylab as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import matplotlib.units as munits

# Get the command line arguments, first the two mandatory ones
callsign = sys.argv[1]                     # callsign for subdirectory name
csv_in_file = sys.argv[2]                  # *modefinder.csv file   

# Now the optional third, 'DB' if output to database
try:                                             # use 'try' as it may not be there
  db_flag=sys.argv[3]
  print ("Data output to database selected")
except:
  db_flag='False'
  print ("Data output to csv file only")

# set up base directory, and paths for csv in/out config and heuristics files 
base_directory='./'
csv_dir=os.path.join(base_directory,'output','csv',callsign)
plot_dir=os.path.join(base_directory,'output','plots',callsign)   # plots go into a subdirectory by callsign
config_dir=os.path.join(base_directory,'config')
if not os.path.exists(plot_dir):
  os.makedirs(plot_dir)

csv_in_name=csv_dir+'/'+csv_in_file+'_modefinder.csv'
csv_out_name=csv_dir+'/'+csv_in_file+'_synthspec.csv'

config_file=config_dir + '/' + callsign + '_config.ini'

# Read two parameters from the specific config.ini file, then the tx and rx from the metadata section as strings
config = configparser.ConfigParser()
config.read(config_file)
freq=config['settings'].getfloat('freq')
distance=config['settings'].getfloat('distance')
tx=config['metadata'].get('tx')
rx=config['metadata'].get('rx')

# Get plot legend location and y axis Doppler shift limits
legend_loc=config['plots'].get('legend')
u_dopp_lim=config['plots'].getfloat('u_dopp_lim')
l_dopp_lim=config['plots'].getfloat('l_dopp_lim')

# derive scale factor for rate of change of phase path (km) to Doppler in Hz
dphase_to_dopp=-1000*freq*1000000/2.9979e8  # 1000 gives m from km, freq MHz to Hz and c vellight m/s, note negative sign
#print(dphase_to_dopp)

c= 2.9979e5                       # Velocity of light in vaccuo in km/s as phase path in km

# Read the data using the csv.reader - this ponderous approach seemed needed for rows with mixed types, float and strings
# Reads a row at a time and tries to convert to float, if fails, leaves as string. Store each row in a list 'data'
data = []
with open(csv_in_name) as csvfile:
  reader = csv.reader(csvfile)
  header = next(reader)            # Skip header row that has the labels
  for row in reader:
    # Convert values to their proper types
    converted_row = []
    for i, item in enumerate(row):
        if i == 0:
            # First column is time - convert string to datetime object
            converted_row.append(datetime.strptime(item, '%Y-%m-%d %H:%M:%S'))
        elif item == '':
            # Empty string becomes None (NULL in ClickHouse)
            converted_row.append(None)
        else:
            try:
                # try converting to float
                converted_row.append(float(item))
            except ValueError:
                # If error, keep as a string
                converted_row.append(item)
    data.append(converted_row)

# Print the header and the data
print("Header with data field names:")
print(header)

##############################################
# Convert the list 'data' into a numpy array
# the sort the data array by p_mode then time
# sort by p_mode is needed as to calculate doppler we take the difference at successive time intervals for the same mode.

temp_data=np.array(data)

indices=np.lexsort((temp_data[:,0], temp_data[:,2]))    # lexsort gives indicies in sorted order not sorted array, the first sort variable is second here
sorted_data=temp_data[indices]                          # this is the sorted array

# Set up arrays for string variables and new one for raw- and one for range-corrected Doppler, recall these are now sorted
n_traces=len(sorted_data)
delay=np.empty(n_traces, dtype=object)
date=np.empty(n_traces, dtype=object)
p_mode=np.empty(n_traces, dtype=object)
color=np.empty(n_traces, dtype=object)
raw_doppler=np.empty(n_traces, dtype=object)
raw_doppler[:]=np.nan                          # Doppler may not be calculated for all pairs, e.g. if time diff too large, so fill with nan
doppler=raw_doppler                            # This is for range-corrected 

# Get the string data into correct single dimension arrays
for i in range(n_traces):
  date[i] = sorted_data[i, 0] if isinstance(sorted_data[i, 0], datetime) \
    else datetime.strptime(sorted_data[i, 0], '%Y-%m-%d %H:%M:%S')   # date needed as a datetime object so we can subtract to get interval
  p_mode[i]=sorted_data[i,2]
  color[i]=sorted_data[i,3]
# And extract the float data
mode_data=np.r_[sorted_data[:,4:12]].astype(float)  # I have probably got mixed up somewhere with data types in arrays, but this curious function is a fix

# Doppler calculation notes:
# Calculate rate of change of phase path lengths i.e. of mode_data[:,5] but only if the time between successive data records
# is 900 s or less (i.e. del_time), that is, no more than three of our five  minute intervals.
# The frequency dependent scale factor from km/s to Hz is dphase_to_dopp, is calculated above.
# This calculation gives variable raw_doppler. Now, there is jitter in the ground range, as rays don't land at the precise,
# to one metre receiver distance but with a standard deviation of about 400 metres. This jitter in ground range gives a jitter in
# phase path length, hence a jitter in Doppler. The line that calculates variable doppler compenstates for this jitter by scaling
# the phase path as if the ground range was constant.
   
for i in range(1, n_traces):
  if p_mode[i] ==  p_mode[i-1]:
    del_time=(date[i]-date[i-1]).seconds
    if del_time > 0 and del_time <= 900:
      raw_doppler[i]=round(((mode_data[i,5]-mode_data[i-1,5])/del_time)*dphase_to_dopp,3)  #  
      doppler[i]=round((((distance/mode_data[i,4])*mode_data[i,5]-(distance/mode_data[i-1,4])*mode_data[i-1,5])\
        /del_time)*dphase_to_dopp,3)
print("Doppler calculation completed")

# Calcuate delay time for the total phase path assuming c is velocity of light in vaccuo
for i in range(1, n_traces):
  delay[i]=round((mode_data[i,5]/c)*1000,3)       # delay in milliseconds where phase path length is in km

##################################################
# Plot Doppler shifts
##################################################

fig, ax = plt.subplots()     
plt.suptitle("Doppler shift of " + str(freq) + " MHz propagation modes between  " + tx + " and " + callsign, fontsize=12)

scatter=ax.scatter(date, doppler, c=color, s=5)

plt.xlabel("Time (Month-Day Hour UTC)")
plt.ylabel("Doppler shift(Hz)")
plt.ylim(l_dopp_lim,u_dopp_lim)

## Set time format and the interval of ticks
xformatter = mdates.DateFormatter('%m-%d %H')
x_tick_interval=int(np.ceil((max(date) - min(date)).seconds / (3600*6)))
print ("tick interval hours: ", x_tick_interval)
xlocator = mdates.HourLocator(interval = x_tick_interval)
ax.xaxis.set_major_locator(xlocator)

plt.gcf().set_size_inches(8, 4, forward=True)
plt.tight_layout()

# Create legend manually
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

# save and show the figure
plt.savefig(plot_dir + "/" + csv_in_file + "_synth_doppler.png", dpi=600)
plt.show()
print("Doppler plot generated and saved")

##################################################
# Plot Delays 
##################################################
fig, ax = plt.subplots()     
plt.suptitle("Delay of " + str(freq) + " MHz propagation modes between  " + tx + " and " + callsign, fontsize=12)

scatter=ax.scatter(date, delay, c=color, s=5)

plt.xlabel("Time (Month-Day Hour UTC)")
plt.ylabel("Delay (ms)")
#plt.ylim(-1,1)
## Set time format and the interval of ticks
xformatter = mdates.DateFormatter('%m-%d %H')
x_tick_interval=int(np.ceil((max(date) - min(date)).seconds / (3600*6)))
print ("tick interval hours: ", x_tick_interval)
xlocator = mdates.HourLocator(interval = x_tick_interval)
ax.xaxis.set_major_locator(xlocator)

plt.gcf().set_size_inches(8, 4, forward=True)
plt.tight_layout()
plt.legend(handles=[black_patch, blue_patch, green_patch, purple_patch, grey_patch, cyan_patch, lime_patch, orchid_patch],\
   ncol=2, loc=legend_loc)

# save and show the figure
plt.savefig(plot_dir + "/" + csv_in_file + "_synth_delay.png", dpi=600)
plt.show()
print("Delay plot generated and saved")

# output the original data plus doppler  into file *_modefinder.csv in ./output/csv/callsign dir
with open(csv_out_name, 'w', encoding='UTF8',) as out_file:     # open a csv file for write
  writer=csv.writer(out_file)
  writer.writerow(["Date,Hops,p_mode,color,Init_elev,one_hop_virt_ht,one_hop_apogee,2nd_hop_apogee,gnd_range,phase_path,geo_path,pylap_doppler,doppler,time_of_flight"])

  for i in range (0,n_traces):
    writer.writerow([sorted_data[i,0],sorted_data[i,1],sorted_data[i,2],sorted_data[i,3],sorted_data[i,4],sorted_data[i,5],\
       sorted_data[i,6],sorted_data[i,7],sorted_data[i,8],sorted_data[i,9],sorted_data[i,10], sorted_data[i,11],doppler[i], delay[i]])

print("csv file * modefinder written")

if db_flag == 'DB':
    ############################################
    # Output to database. This code was produced for clickhouse by Claude AI based on my postgreql code.
    # Here are Claude's notes on the differences
    # clickhouse_connect replaces psycopg2 — install it first with pip install clickhouse-connect
    # No explicit cursor or commit needed — ClickHouse inserts are auto-committed
    # No ON CONFLICT DO NOTHING — that's handled automatically by ReplacingMergeTree in the background, so duplicates are silently absorbed
    # The insert passes the whole data list in one batch call rather than execute_batch, which is efficient for ClickHouse's columnar storage
    # Connects on port 8123 (HTTP) rather than PostgreSQL's 5432
    # This requires a ClickHouse database set up on the localhost computer
    # The database name is 'psws' and the table name is 'synth_spec'.
    # Contact Gwyn Griffiths G3ZIL if you want to set up your own database to use this option
    ############################################
    import clickhouse_connect        # This is the connection tool to the ClickHouse database

    ###########################################################
    # Connect to and write into the database from the csv file
    ###########################################################
    # initially set the connection flag to be None
    client = None
    connected = "Not connected"
    execute = "Not executed"

    # Store the parsed csv data in a list
    data = []
    try:
        with open(csv_out_name) as csv_file:
            reader = csv.reader(csv_file, delimiter=',')
            header = next(reader)  # Skip header row
            for row in reader:
                # Convert values to their proper types
                converted_row = []
                for item in row:
                    try:
                        # try converting to float
                        converted_row.append(float(item))
                    except ValueError:
                        # If error, keep as a string
                        converted_row.append(item)
                converted_row.append(str(round(freq, 2)))   # frequency as characters from *config.ini, and tx and rx
                converted_row.append(tx)
                converted_row.append(rx)
                data.append(converted_row)

        try:
            # Connect to the ClickHouse database
            client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                username='g3zil',
                password='hamsci_psws',
                database='psws'
            )
            connected = "Connected"

            # Column names matching the table definition
            columns = ['time', 'hops', 'p_mode', 'color', 'init_elev', 'one_hop_virt_ht',
                       'one_hop_apogee', 'sec_hop_apogee', 'gnd_range', 'phase_path',
                       'geo_path', 'pylap_doppler', 'doppler', 'time_of_flight', 'frequency', 'tx', 'rx']
           
            # Convert time column to datetime objects just before insert
            for row in data:
              if isinstance(row[0], str):
                row[0] = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            # Sanitise any remaining empty strings to None before insert
            data = [
             [None if (i > 0 and val == '') else val for i, val in enumerate(row)]
             for row in data
             ]
          
            # Batch insert - ClickHouse handles deduplication via ReplacingMergeTree
            # (equivalent to ON CONFLICT DO NOTHING in PostgreSQL)
            client.insert('synth_spec', data, column_names=columns)
            execute = "Executed"

            print(connected, execute)

        except Exception as e:
            print('Unable to connect or insert!\n{0}'.format(e))
            print("Database status:", connected, execute)

    finally:
        if client is not None:
            client.close()

print ("synthspec processing complete")
