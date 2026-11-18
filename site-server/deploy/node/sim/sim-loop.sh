#!/bin/bash
# START.bat's :loop on Linux: run the agent, then `update.py --agent-exited` (the same call START.bat makes), wait, again.
# usage: sim-loop.sh <code folder> <logfile>      env: NM_SITE NM_TOKEN NM_NODE NM_DATA SIM_KINDS
CODE=$1; LOG=$2
while true; do
  SIM_CODE=$CODE python3 /root/stage/r4ready-sim/sim_run.py >> $LOG 2>&1
  (cd $CODE && python3 update.py --agent-exited >> $LOG 2>&1)
  echo "--- loop: agent stopped, restarting in 5 s ($(date +%T))" >> $LOG
  sleep 5
done
