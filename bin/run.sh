#!/bin/bash
echo "=== PULSE RUN.SH STARTING $(date) ===" >> /tmp/pulse-debug.log
set -a
source ~/.pulse/.env
set +a
cd /Users/iris/.openclaw/workspace
echo "ENV: PULSE_HOOK_TOKEN=${PULSE_HOOK_TOKEN:0:5}..." >> /tmp/pulse-debug.log
echo "PWD: $(pwd)" >> /tmp/pulse-debug.log
exec /opt/homebrew/bin/python3 -m pulse.src
