#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="${CLWG_REMOTE:-origin}"
BRANCH="${CLWG_BRANCH:-main}"
VENV_PIP="${PROJECT_ROOT}/.venv/bin/pip"
SERVICE_NAME="${CLWG_SERVICE_NAME:-clawgotchi.service}"

log() {
  printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

run_git() {
  git -C "${PROJECT_ROOT}" "$@"
}

if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
  die "Kein Git-Repository in ${PROJECT_ROOT} gefunden."
fi

if ! run_git diff --quiet || ! run_git diff --cached --quiet; then
  die "Lokale Aenderungen gefunden. Bitte erst committen/stashen und erneut ausfuehren."
fi

log "Hole Updates von ${REMOTE}/${BRANCH}."
run_git fetch "${REMOTE}"
run_git checkout "${BRANCH}"
run_git pull --ff-only "${REMOTE}" "${BRANCH}"

if [[ -x "${VENV_PIP}" ]]; then
  log "Installiere/aktualisiere Python-Abhaengigkeiten."
  "${VENV_PIP}" install -e "${PROJECT_ROOT}"
else
  die "pip im Virtualenv nicht gefunden: ${VENV_PIP}"
fi

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
