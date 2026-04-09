#!/usr/bin/env bash
# =============================================================================
# List All Bots — Shows status of every bot running on this server.
#
# Usage:
#   sudo ./deploy/list_all_bots.sh
# =============================================================================

set -euo pipefail

echo "============================================"
echo "  All Trading Bots on This Server"
echo "============================================"
echo ""

printf "%-20s %-10s %-10s %-30s\n" "BOT" "STATUS" "MEMORY" "DIRECTORY"
printf "%-20s %-10s %-10s %-30s\n" "---" "------" "------" "---------"

# Find all bot services by scanning /opt for directories with a systemd service
for dir in /opt/*/; do
    [ -d "$dir" ] || continue
    name=$(basename "$dir")

    # Check if there's a matching systemd service
    SERVICE=""
    for candidate in "${name}" "alpha-bot-${name}" "${name}-bot"; do
        if systemctl list-unit-files "${candidate}.service" &>/dev/null 2>&1; then
            if systemctl cat "${candidate}.service" &>/dev/null 2>&1; then
                SERVICE="${candidate}"
                break
            fi
        fi
    done

    # Also check the simple service name
    if [ -z "${SERVICE}" ] && systemctl cat "${name}.service" &>/dev/null 2>&1; then
        SERVICE="${name}"
    fi

    if [ -z "${SERVICE}" ]; then
        # No service found — might be a non-bot directory
        continue
    fi

    STATUS=$(systemctl is-active "${SERVICE}.service" 2>/dev/null || echo "inactive")

    # Get memory usage
    PID=$(systemctl show "${SERVICE}.service" --property=MainPID 2>/dev/null | cut -d= -f2)
    if [ "${PID}" != "0" ] && [ -n "${PID}" ]; then
        MEM_KB=$(ps -o rss= -p "${PID}" 2>/dev/null || echo "0")
        MEM_MB=$(( MEM_KB / 1024 ))
        MEM="${MEM_MB}MB"
    else
        MEM="--"
    fi

    printf "%-20s %-10s %-10s %-30s\n" "${name}" "${STATUS}" "${MEM}" "${dir}"
done

echo ""

# System totals
TOTAL_MEM=$(free -m | awk '/^Mem:/ {print $3}')
TOTAL_AVAIL=$(free -m | awk '/^Mem:/ {print $7}')
DISK_USED=$(df -h / | awk 'NR==2 {print $3}')
DISK_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
LOAD=$(uptime | awk -F'load average:' '{print $2}' | xargs)

echo "System Resources:"
echo "  Memory:   ${TOTAL_MEM}MB used / ${TOTAL_AVAIL}MB available"
echo "  Disk:     ${DISK_USED} used / ${DISK_AVAIL} available"
echo "  Load:     ${LOAD}"
echo ""
