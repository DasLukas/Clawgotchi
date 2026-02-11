#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="${CLWG_REMOTE:-origin}"
REMOTE_URL="${CLWG_REMOTE_URL:-}"
BRANCH="${CLWG_BRANCH:-main}"
VENV_DIR="${PROJECT_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
SERVICE_NAME="${CLWG_SERVICE_NAME:-clawgotchi.service}"
APP_USER="${CLWG_USER:-clawgotchi}"
STATUS_FILE="${CLWG_UPDATE_STATUS_FILE:-/tmp/clawgotchi-update-status.env}"

RUN_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
REBOOT_REQUIRED="false"
REBOOT_SCHEDULED="false"

log() {
  printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*"
}

sanitize_status_value() {
  local value="${1:-}"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  value="${value//=/: }"
  printf "%s" "${value}"
}

write_status() {
  local state="$1"
  local message="$2"
  local exit_code="$3"
  local now
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  {
    umask 022
    cat >"${STATUS_FILE}" <<EOSTATUS
state=$(sanitize_status_value "${state}")
message=$(sanitize_status_value "${message}")
started_at=${RUN_STARTED_AT}
updated_at=${now}
reboot_required=${REBOOT_REQUIRED}
reboot_scheduled=${REBOOT_SCHEDULED}
exit_code=${exit_code}
EOSTATUS
  } || true
}

die() {
  local message="$1"
  log "ERROR: ${message}"
  write_status "failed" "${message}" "1"
  exit 1
}

on_error() {
  local exit_code=$?
  local line_no="$1"
  local message="Update failed at line ${line_no}."
  log "ERROR: command failed at line ${line_no}: ${BASH_COMMAND} (exit=${exit_code})"
  write_status "failed" "${message}" "${exit_code}"
  exit "${exit_code}"
}

trap 'on_error "$LINENO"' ERR

run_git() {
  run_as_app "git -C '${PROJECT_ROOT}' $*"
}

run_as_app() {
  local cmd="$1"
  if [[ "${EUID}" -eq 0 ]]; then
    su - "${APP_USER}" -c "${cmd}"
  else
    bash -lc "${cmd}"
  fi
}

ensure_venv() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    log "Virtualenv missing. Creating ${VENV_DIR}."
    run_as_app "python3 -m venv '${VENV_DIR}'"
  fi

  if ! run_as_app "'${VENV_PYTHON}' -m pip --version" >/dev/null 2>&1; then
    log "Virtualenv tooling is broken. Recreating ${VENV_DIR}."
    run_as_app "rm -rf '${VENV_DIR}'"
    run_as_app "python3 -m venv '${VENV_DIR}'"
  fi
}

is_reboot_marker_present() {
  [[ -f "/run/reboot-required" || -f "/var/run/reboot-required" ]]
}

service_exists() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 1
  fi
  systemctl show --property=Id --value "${SERVICE_NAME}" >/dev/null 2>&1
}

if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
  die "No Git repository found at ${PROJECT_ROOT}."
fi

if [[ "${EUID}" -eq 0 ]]; then
  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    die "App user '${APP_USER}' does not exist. Override via CLWG_USER if needed."
  fi
fi

write_status "running" "Update started." "0"

had_reboot_marker_before="false"
if is_reboot_marker_present; then
  had_reboot_marker_before="true"
fi

if ! run_git diff --quiet || ! run_git diff --cached --quiet; then
  die "Local changes detected. Commit/stash before running update."
fi

if [[ -n "${REMOTE_URL}" ]]; then
  log "Ensuring git remote '${REMOTE}' points to configured URL."
  run_git remote set-url "${REMOTE}" "${REMOTE_URL}"
fi

log "Fetching updates from ${REMOTE}/${BRANCH}."
run_git fetch "${REMOTE}"
run_git checkout "${BRANCH}"
run_git pull --ff-only "${REMOTE}" "${BRANCH}"

ensure_venv
log "Installing/updating Python dependencies."
run_as_app "'${VENV_PYTHON}' -m pip install --upgrade pip"
run_as_app "'${VENV_PYTHON}' -m pip install -e '${PROJECT_ROOT}'"

if service_exists; then
  if [[ "${EUID}" -eq 0 ]]; then
    log "Restarting service ${SERVICE_NAME}."
    systemctl restart "${SERVICE_NAME}"
  else
    log "Skipped service restart (no root privileges)."
    log "To restart manually: sudo systemctl restart ${SERVICE_NAME}"
  fi
else
  log "No systemd service '${SERVICE_NAME}' found or systemctl unavailable, skipping restart."
fi

if [[ "${had_reboot_marker_before}" == "false" ]] && is_reboot_marker_present; then
  REBOOT_REQUIRED="true"
fi

if [[ "${REBOOT_REQUIRED}" == "true" ]]; then
  if [[ "${EUID}" -eq 0 ]] && command -v systemctl >/dev/null 2>&1; then
    REBOOT_SCHEDULED="true"
    write_status "rebooting" "Update finished. Reboot required, rebooting now." "0"
    log "Update finished. Reboot required, scheduling reboot now."
    systemctl --no-block reboot
  else
    write_status "succeeded" "Update finished. Reboot required but not scheduled (root/systemctl required)." "0"
    log "Update finished. Reboot required but not scheduled (root/systemctl required)."
  fi
else
  write_status "succeeded" "Update finished successfully." "0"
  log "Update finished successfully."
fi
