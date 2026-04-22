#!/usr/bin/env bash
# Trail Simulator base-station uninstaller. Removes the tunneld LaunchDaemon
# and the app LaunchAgent installed by scripts/install.sh. Idempotent — safe
# to re-run.
set -euo pipefail

DAEMON_LABEL="com.trail-simulator.tunneld"
AGENT_LABEL="com.trail-simulator.app"
DAEMON_PLIST="/Library/LaunchDaemons/${DAEMON_LABEL}.plist"

if [[ $EUID -ne 0 ]]; then
  echo "This uninstaller needs sudo to remove /Library/LaunchDaemons entries."
  echo "Re-run: sudo ./scripts/uninstall.sh"
  exit 1
fi

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_HOME="$(/usr/bin/dscl . -read "/Users/${TARGET_USER}" NFSHomeDirectory | awk '{print $2}')"
TARGET_UID="$(/usr/bin/id -u "${TARGET_USER}")"
AGENT_PLIST="${TARGET_HOME}/Library/LaunchAgents/${AGENT_LABEL}.plist"

echo "Trail Simulator base-station uninstall"
echo "======================================"
echo "Target user:   ${TARGET_USER} (uid=${TARGET_UID})"
echo "Daemon plist:  ${DAEMON_PLIST}"
echo "Agent plist:   ${AGENT_PLIST}"
echo

# ---- LaunchAgent (app) -----------------------------------------------------
echo "[1/2] Removing ${AGENT_LABEL}..."
if launchctl asuser "${TARGET_UID}" launchctl print "gui/${TARGET_UID}/${AGENT_LABEL}" >/dev/null 2>&1; then
  launchctl asuser "${TARGET_UID}" launchctl bootout "gui/${TARGET_UID}/${AGENT_LABEL}" 2>/dev/null || true
  echo "  bootout OK"
else
  echo "  not loaded (skip)"
fi
if [[ -f "${AGENT_PLIST}" ]]; then
  rm -f "${AGENT_PLIST}"
  echo "  plist removed"
else
  echo "  plist already absent"
fi

# ---- LaunchDaemon (tunneld) ------------------------------------------------
echo "[2/2] Removing ${DAEMON_LABEL}..."
if launchctl print "system/${DAEMON_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "system/${DAEMON_LABEL}" 2>/dev/null || true
  echo "  bootout OK"
else
  echo "  not loaded (skip)"
fi
if [[ -f "${DAEMON_PLIST}" ]]; then
  rm -f "${DAEMON_PLIST}"
  echo "  plist removed"
else
  echo "  plist already absent"
fi

echo
echo "======================================"
echo "Uninstall complete."
echo "Logs left in place (not removed):"
echo "  /var/log/trail-simulator/tunneld.log"
echo "  <project-root>/.trail-simulator-app.log"
echo "SQLite DB left in place: <project-root>/trail-simulator.db"
