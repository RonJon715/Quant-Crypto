#!/usr/bin/env bash
# =============================================================================
# Alpha Bot — Manage All Instances
#
# Usage:
#   sudo ./deploy/manage_instances.sh status      # Show all instances
#   sudo ./deploy/manage_instances.sh start-all   # Start every instance
#   sudo ./deploy/manage_instances.sh stop-all    # Stop every instance
#   sudo ./deploy/manage_instances.sh restart-all # Restart every instance
#   sudo ./deploy/manage_instances.sh logs <name> # Follow logs for one instance
#   sudo ./deploy/manage_instances.sh list        # List instance names
#   sudo ./deploy/manage_instances.sh remove <name> # Remove an instance
# =============================================================================

set -euo pipefail

APP_DIR="/opt/alpha-bot"
INSTANCES_DIR="${APP_DIR}/instances"

get_instances() {
    if [ -d "${INSTANCES_DIR}" ]; then
        ls -1 "${INSTANCES_DIR}" 2>/dev/null || true
    fi
}

cmd_status() {
    echo "============================================"
    echo "  Alpha Bot — Instance Status"
    echo "============================================"
    echo ""

    # Check the default instance
    if systemctl is-enabled alpha-bot.service &>/dev/null; then
        STATUS=$(systemctl is-active alpha-bot.service 2>/dev/null || echo "inactive")
        printf "  %-25s %s\n" "alpha-bot (default)" "${STATUS}"
    fi

    # Check named instances
    for name in $(get_instances); do
        SERVICE="alpha-bot-${name}"
        if systemctl is-enabled "${SERVICE}.service" &>/dev/null; then
            STATUS=$(systemctl is-active "${SERVICE}.service" 2>/dev/null || echo "inactive")
            MEMORY=$(systemctl show "${SERVICE}.service" --property=MemoryCurrent 2>/dev/null | cut -d= -f2)
            if [ "${MEMORY}" = "[not set]" ] || [ -z "${MEMORY}" ]; then
                MEMORY="N/A"
            else
                MEMORY=$(numfmt --to=iec "${MEMORY}" 2>/dev/null || echo "${MEMORY}")
            fi
            printf "  %-25s %-10s (mem: %s)\n" "${name}" "${STATUS}" "${MEMORY}"
        fi
    done

    echo ""

    # Show total resource usage
    TOTAL_MEM=$(ps aux | grep "[p]ython main.py" | awk '{sum += $6} END {print sum/1024}')
    echo "Total bot memory: ${TOTAL_MEM:-0} MB"
    echo ""
}

cmd_start_all() {
    echo "Starting all instances..."
    if systemctl is-enabled alpha-bot.service &>/dev/null; then
        systemctl start alpha-bot.service && echo "  Started: alpha-bot (default)"
    fi
    for name in $(get_instances); do
        SERVICE="alpha-bot-${name}"
        systemctl start "${SERVICE}.service" && echo "  Started: ${name}"
    done
    echo "Done."
}

cmd_stop_all() {
    echo "Stopping all instances..."
    for name in $(get_instances); do
        SERVICE="alpha-bot-${name}"
        systemctl stop "${SERVICE}.service" 2>/dev/null && echo "  Stopped: ${name}"
    done
    if systemctl is-enabled alpha-bot.service &>/dev/null; then
        systemctl stop alpha-bot.service 2>/dev/null && echo "  Stopped: alpha-bot (default)"
    fi
    echo "Done."
}

cmd_restart_all() {
    echo "Restarting all instances..."
    if systemctl is-enabled alpha-bot.service &>/dev/null; then
        systemctl restart alpha-bot.service && echo "  Restarted: alpha-bot (default)"
    fi
    for name in $(get_instances); do
        SERVICE="alpha-bot-${name}"
        systemctl restart "${SERVICE}.service" && echo "  Restarted: ${name}"
    done
    echo "Done."
}

cmd_logs() {
    local name="${1:-}"
    if [ -z "${name}" ]; then
        echo "Usage: $0 logs <instance-name>"
        exit 1
    fi
    SERVICE="alpha-bot-${name}"
    echo "Following logs for ${name} (Ctrl+C to stop)..."
    journalctl -u "${SERVICE}.service" -f
}

cmd_list() {
    echo "Instances:"
    if systemctl is-enabled alpha-bot.service &>/dev/null; then
        echo "  default  (config: ${APP_DIR}/config/settings.yaml)"
    fi
    for name in $(get_instances); do
        echo "  ${name}  (config: ${INSTANCES_DIR}/${name}/settings.yaml)"
    done
}

cmd_remove() {
    local name="${1:-}"
    if [ -z "${name}" ]; then
        echo "Usage: $0 remove <instance-name>"
        exit 1
    fi

    SERVICE="alpha-bot-${name}"
    INSTANCE="${INSTANCES_DIR}/${name}"

    if [ ! -d "${INSTANCE}" ]; then
        echo "ERROR: Instance '${name}' not found."
        exit 1
    fi

    echo "Removing instance '${name}'..."
    systemctl stop "${SERVICE}.service" 2>/dev/null || true
    systemctl disable "${SERVICE}.service" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE}.service"
    systemctl daemon-reload
    rm -rf "${INSTANCE}"
    echo "  Removed service and config for '${name}'."
    echo "Done."
}

# ------------------------------------------------------------------
# Main dispatch
# ------------------------------------------------------------------
ACTION="${1:-status}"
shift || true

case "${ACTION}" in
    status)      cmd_status ;;
    start-all)   cmd_start_all ;;
    stop-all)    cmd_stop_all ;;
    restart-all) cmd_restart_all ;;
    logs)        cmd_logs "$@" ;;
    list)        cmd_list ;;
    remove)      cmd_remove "$@" ;;
    *)
        echo "Usage: $0 {status|start-all|stop-all|restart-all|logs <name>|list|remove <name>}"
        exit 1
        ;;
esac
