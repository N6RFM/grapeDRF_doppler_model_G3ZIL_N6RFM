#!/bin/env python

import os
import datetime
import logging
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
import matplotlib as mpl
from matplotlib import pyplot as plt
import grapeDRF  # Custom module for GrapeDRF data

# Letters for subplot labeling
letters = 'abcdefghijklmnopqrztuvwxyz'

# --- Matplotlib global configuration ---
mpl.rcParams['font.size'] = 12
mpl.rcParams['font.weight'] = 'bold'
mpl.rcParams['axes.grid'] = True
mpl.rcParams['axes.titlesize'] = 30
mpl.rcParams['grid.linestyle'] = ':'
mpl.rcParams['figure.figsize'] = np.array([15, 8])
mpl.rcParams['axes.xmargin'] = 0
mpl.rcParams['legend.fontsize'] = 'xx-large'

# --- Station metadata dictionary ---
station_dct = {}
sdct = station_dct['n6rfm'] = {}
sdct['QTH'] = 'Keller,TX'  # Human-readable location

if __name__ == '__main__':
    # --- Output directory setup ---
    output_dir = os.path.join('output', 'n6rfm_2024eclipse')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # --- Event dates and station info ---
    sDate = datetime.datetime(2024, 4, 8)
    eDate = datetime.datetime(2024, 4, 9)
    station = 'n6rfm'
    lat = 32.9343  # N6RFM latitude
    lon = -97.2514  # N6RFM longitude

    # --- Figure display options ---
    figd = {}
    figd['solar_lat'] = lat  # Solar overlay latitude
    figd['solar_lon'] = lon  # Solar overlay longitude
    figd['overlaySolarElevation'] = True
    figd['overlayEclipse'] = True
    figd['xlim'] = (sDate, eDate)

    # --- Frequencies to plot ---
    cfreqs = [10]  # Only 10 MHz for N6RFM
    # cfreqs = [3.33, 7.85, 14.67]  # Optional multi-frequency plotting

    # --- Which plots to generate ---
    plot_list = []
    plot_list.append('WDgrape')  # Standard GrapeDRF waterfall

    # --- Build PNG filename based on date, station, plot type, and frequencies ---
    str_sDate = sDate.strftime('%Y%m%d.%H%M')
    str_eDate = eDate.strftime('%Y%m%d.%H%M')
    png_ = [str_sDate, str_eDate, station]
    for pll in plot_list:
        png_.append(pll)
        if pll == 'WDgrape':
            png_ += ['{!s}'.format(x) for x in cfreqs]  # Append frequencies to filename

    png_fname = '_'.join(png_) + '.png'
    png_fpath = os.path.join(output_dir, png_fname)

    # --- Figure layout: determine rows and columns ---
    nrows = len(plot_list)
    if 'WDgrape' in plot_list:
        nrows += len(cfreqs) - 1  # Extra row for each frequency
    ncols = 1
    ax_inx = 0
    axs = []

    fig = plt.figure(figsize=(22, nrows * 5))
    letter_fdict = {'size': 32}  # Subplot label font size

    # --- Generate GrapeDRF plots ---
    if 'WDgrape' in plot_list:
        gDRF = grapeDRF.GrapeDRF(sDate, eDate, station)  # Load DRF data
        g_figd = figd.copy()  # Pass overlay settings
        for cfreq in cfreqs:
            print(f'   {cfreq} MHz...')
            ax_inx += 1
            ax = fig.add_subplot(nrows, ncols, ax_inx)
            axs.append(ax)

            # --- Plot spectrogram for this frequency ---
            # NOTE: The plot_ax method in grapeDRF now safely handles both single- and multi-frequency DRF arrays.
            # This prevents "too many indices for array" errors for single-frequency data.
            gDRF.plot_ax(cfreq, ax, **g_figd)
            ax.set_title(f'({letters[ax_inx-1]})', loc='left', fontdict=letter_fdict)
            ax.set_title(f'{cfreq} MHz Receiver')

            # --- Optional overlay: Doppler shift from CSV ---
            rt_dop_csv = os.path.join('data', 'shibaji', f'LoS_doppler_{cfreq}.csv')
            if os.path.exists(rt_dop_csv):
                print(f'FOUND: {rt_dop_csv}')
                rt_dop = pd.read_csv(rt_dop_csv)
                rt_dop['time'] = pd.to_datetime(rt_dop['time'])
                ax.plot(rt_dop['time'], rt_dop['fd'], color='r', lw=5, zorder=1000)
            else:
                print(f'NOT FOUND: {rt_dop_csv}')

    # --- Finalize figure: x-axis formatting ---
    for ax_inx, ax in enumerate(axs):
        ax.set_xlim(sDate, eDate)
        xticks = ax.get_xticks()
        ax.set_xticks(xticks)
        if ax_inx != len(axs) - 1:
            ax.set_xlabel('')  # Hide intermediate x-axis labels
            xtkls = [''] * len(xticks)
        else:
            ax.set_xlabel('UTC')  # Bottom plot gets UTC label
            xtkls = [mpl.dates.num2date(xtk).strftime('%H:%M') for xtk in xticks]
        ax.set_xticklabels(xtkls)

    # --- Add station and date text ---
    sdct = station_dct.get(station, {})
    stxt = f'{station.upper()} ({sdct["QTH"]})' if 'QTH' in sdct else station.upper()
    txt = [stxt, sDate.strftime('%d %b %Y')]
    fontdict = {'size': 42, 'weight': 'bold'}
    fig.text(0.5, 1., '\n'.join(txt), fontdict=fontdict, ha='center', va='bottom')

    # --- Save the figure ---
    fig.tight_layout()
    fig.savefig(png_fpath, bbox_inches='tight')
    print(png_fpath)
