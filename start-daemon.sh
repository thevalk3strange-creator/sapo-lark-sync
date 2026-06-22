#!/bin/bash
# Start the SAPO-Lark sync daemon
# This polls the staging table every 5 seconds and upserts to DH/SX tables

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/sync-daemon.log"

echo "Starting sync daemon..."
nohup node /tmp/sync-daemon.js > "$LOG_FILE" 2>&1 &
echo $! > "$SCRIPT_DIR/sync-daemon.pid"
echo "Daemon started (PID: $(cat $SCRIPT_DIR/sync-daemon.pid))"
echo "Logs: $LOG_FILE"
echo ""
echo "To stop: kill $(cat $SCRIPT_DIR/sync-daemon.pid)"
echo "To view logs: tail -f $LOG_FILE"
