#!/bin/bash

ARIA2C=$1
SERVICE_CORES=${2:-}
CPU_LIMIT=${3:-20}
EXTERNAL_DOWNLOAD_CLIENTS=${4:-false}
SABNZBDPLUS=$5

if [ -n "$SERVICE_CORES" ]; then
    ARIA2_CMD="taskset -c $SERVICE_CORES $ARIA2C"
    SAB_CMD="taskset -c $SERVICE_CORES cpulimit -l $CPU_LIMIT -- $SABNZBDPLUS"
else
    ARIA2_CMD="$ARIA2C"
    SAB_CMD="cpulimit -l $CPU_LIMIT -- $SABNZBDPLUS"
fi

if [ "$EXTERNAL_DOWNLOAD_CLIENTS" != "true" ]; then
    tracker_list=$(curl -Ns https://cdn.jsdelivr.net/gh/ngosang/trackerslist@master/trackers_all.txt | awk '$0' | tr '\n\n' ',')
    $ARIA2_CMD --conf-path=configs/ac/ac.conf --daemon=true --rpc-listen-all=true --bt-tracker="[$tracker_list]"
fi
if [ -n "$SABNZBDPLUS" ]; then
    $SAB_CMD -f configs/sabnzbd/SABnzbd.ini -s :::8070 -b 0 -d -c -l 0 --console
fi
