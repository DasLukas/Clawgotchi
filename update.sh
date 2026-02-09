#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="${CLWG_REMOTE:-origin}"
BRANCH="${CLWG_BRANCH:-main}"
VENV_DIR="${PROJECT_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
SERVICE_NAME="${CLWG_SERVICE_NAME:-clawgotchi.service}"
APP_USER="${CLWG_USER:-clawgotchi}"

log() {
  printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

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

if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
  die "Kein Git-Repository in ${PROJECT_ROOT} gefunden."
fi

if [[ "${EUID}" -eq 0 ]]; then
  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    die "App-User '${APP_USER}' existiert nicht. Optional: CLWG_USER setzen."
  fi
fi

if ! run_git diff --quiet || ! run_git diff --cached --quiet; then
  die "Lokale Aenderungen gefunden. Bitte erst committen/stashen und erneut ausfuehren."
fi

log "Hole Updates von ${REMOTE}/${BRANCH}."
run_git fetch "${REMOTE}"
run_git checkout "${BRANCH}"
run_git pull --ff-only "${REMOTE}" "${BRANCH}"

ensure_venv
log "Installing/updating Python dependencies."
run_as_app "'${VENV_PYTHON}' -m pip install --upgrade pip"
run_as_app "'${VENV_PYTHON}' -m pip install -e '${PROJECT_ROOT}'"

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q "^${SERVICE_NAME}"; then
  if [[ "${EUID}" -eq 0 ]]; then
    log "Starte Service ${SERVICE_NAME} neu."
    systemctl restart "${SERVICE_NAME}"
  else
    log "Service-Neustart uebersprungen (kein root)."
    log "Zum Neustart: sudo systemctl restart ${SERVICE_NAME}"
  fi
else
  log "Kein systemd-Service ${SERVICE_NAME} gefunden, Neustart uebersprungen."
fi

log "Update erfolgreich abgeschlossen."
