#!/usr/bin/env bash
# Trail Simulator base-station installer. Installs tunneld as a LaunchDaemon
# (root) and the Trail Simulator app as a LaunchAgent (user). Idempotent —
# safe to re-run.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
VENV_BIN="${PROJECT_ROOT}/.venv/bin"
TMPL_DIR="${PROJECT_ROOT}/scripts/launchd"

DAEMON_LABEL="com.trail-simulator.tunneld"
AGENT_LABEL="com.trail-simulator.app"
DAEMON_PLIST="/Library/LaunchDaemons/${DAEMON_LABEL}.plist"
AGENT_PLIST="${HOME}/Library/LaunchAgents/${AGENT_LABEL}.plist"
LOG_DIR="/var/log/trail-simulator"

echo "Trail Simulator base-station install"
echo "===================================="
echo "Project root:    ${PROJECT_ROOT}"
echo "venv python:     ${VENV_PYTHON}"
echo

# ---- preflight -------------------------------------------------------------
if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "ERROR: ${VENV_PYTHON} not found."
  echo "  Create it first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if ! "${VENV_PYTHON}" -c 'import pymobiledevice3' >/dev/null 2>&1; then
  echo "ERROR: pymobiledevice3 not importable from the venv."
  echo "  Install it: ${VENV_BIN}/pip install -r requirements.txt"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "This installer needs sudo to write /Library/LaunchDaemons."
  echo "Re-run: sudo ./scripts/install.sh"
  exit 1
fi

# SUDO_USER is the invoking user when running via sudo; fall back to $USER.
TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_HOME="$(/usr/bin/dscl . -read "/Users/${TARGET_USER}" NFSHomeDirectory | awk '{print $2}')"
TARGET_UID="$(/usr/bin/id -u "${TARGET_USER}")"
AGENT_PLIST="${TARGET_HOME}/Library/LaunchAgents/${AGENT_LABEL}.plist"

echo "Target user:     ${TARGET_USER} (uid=${TARGET_UID})"
echo "Agent plist:     ${AGENT_PLIST}"
echo "Daemon plist:    ${DAEMON_PLIST}"
echo

# ---- log directory ---------------------------------------------------------
mkdir -p "${LOG_DIR}"
chown root:wheel "${LOG_DIR}"
chmod 755 "${LOG_DIR}"

# ---- render + install LaunchDaemon (tunneld) -------------------------------
echo "[1/4] Installing ${DAEMON_LABEL}..."

# bootout if already loaded (idempotent re-install)
if launchctl print "system/${DAEMON_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "system/${DAEMON_LABEL}" 2>/dev/null || true
fi

sed \
  -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
  "${TMPL_DIR}/${DAEMON_LABEL}.plist.tmpl" \
  > "${DAEMON_PLIST}"

chown root:wheel "${DAEMON_PLIST}"
chmod 644 "${DAEMON_PLIST}"
launchctl bootstrap system "${DAEMON_PLIST}"

# ---- render + install LaunchAgent (app) ------------------------------------
echo "[2/4] Installing ${AGENT_LABEL}..."

mkdir -p "$(dirname "${AGENT_PLIST}")"
chown "${TARGET_USER}:staff" "$(dirname "${AGENT_PLIST}")"

# bootout if already loaded
if launchctl asuser "${TARGET_UID}" launchctl print "gui/${TARGET_UID}/${AGENT_LABEL}" >/dev/null 2>&1; then
  launchctl asuser "${TARGET_UID}" launchctl bootout "gui/${TARGET_UID}/${AGENT_LABEL}" 2>/dev/null || true
fi

sed \
  -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
  -e "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
  -e "s|__VENV_BIN__|${VENV_BIN}|g" \
  "${TMPL_DIR}/${AGENT_LABEL}.plist.tmpl" \
  > "${AGENT_PLIST}"

chown "${TARGET_USER}:staff" "${AGENT_PLIST}"
chmod 644 "${AGENT_PLIST}"
launchctl asuser "${TARGET_UID}" launchctl bootstrap "gui/${TARGET_UID}" "${AGENT_PLIST}"

# ---- smoke tests -----------------------------------------------------------
echo "[3/4] Waiting for services to settle..."
sleep 4

echo "[4/4] Smoke tests..."
TUNNELD_OK=0
APP_OK=0

if launchctl print "system/${DAEMON_LABEL}" 2>/dev/null | grep -q 'state = running'; then
  if /usr/bin/nc -z 127.0.0.1 49151 2>/dev/null; then
    echo "  tunneld: running + listening on 49151 ✓"
    TUNNELD_OK=1
  else
    echo "  tunneld: process up but not yet listening on 49151 (may still be starting)"
  fi
else
  echo "  tunneld: NOT running — check /var/log/trail-simulator/tunneld.log"
fi

if /usr/bin/curl -fsS --max-time 3 http://127.0.0.1:8787/api/status >/dev/null 2>&1; then
  echo "  app:     responding on 8787 ✓"
  APP_OK=1
else
  echo "  app:     not yet responding on 8787 — check ${PROJECT_ROOT}/.trail-simulator-app.log"
fi

echo
echo "===================================="
if [[ $TUNNELD_OK -eq 1 && $APP_OK -eq 1 ]]; then
  echo "Install complete. Reach the UI at:"
  LOCALHOSTNAME="$(/usr/sbin/scutil --get LocalHostName 2>/dev/null || echo "")"
  LAN_IP="$(/usr/sbin/ipconfig getifaddr en0 2>/dev/null || /usr/sbin/ipconfig getifaddr en1 2>/dev/null || echo "")"
  if [[ -n "${LOCALHOSTNAME}" ]]; then
    echo "  http://${LOCALHOSTNAME}.local:8787"
  fi
  if [[ -n "${LAN_IP}" ]]; then
    echo "  http://${LAN_IP}:8787"
  fi
  echo
  echo "Next: on the iPhone, open that URL in Safari and Add to Home Screen."
else
  echo "Install finished, but one or both services aren't responding yet."
  echo "Inspect the logs above and re-run smoke checks manually after a few seconds:"
  echo "  sudo launchctl print system/${DAEMON_LABEL}"
  echo "  launchctl print gui/\$(id -u)/${AGENT_LABEL}"
fi
