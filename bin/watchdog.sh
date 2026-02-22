#!/bin/bash
# Pulse watchdog — restarts daemon if not running
# Run via cron every 30 minutes

LOG="/Users/iris/.pulse/logs/watchdog.log"
LABEL="ai.openclaw.pulse"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Check if pulse is running
if launchctl list | grep -q "$LABEL" && pgrep -f "pulse.src" > /dev/null 2>&1; then
    echo "$(timestamp) [watchdog] Pulse is running ✓" >> "$LOG"
    exit 0
fi

# It's dead — restart it
echo "$(timestamp) [watchdog] Pulse is DOWN — restarting..." >> "$LOG"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >> "$LOG" 2>&1
sleep 5

if pgrep -f "pulse.src" > /dev/null 2>&1; then
    echo "$(timestamp) [watchdog] Restart successful ✓" >> "$LOG"
else
    echo "$(timestamp) [watchdog] Restart FAILED ✗" >> "$LOG"
fi
