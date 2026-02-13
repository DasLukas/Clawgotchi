#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="${CLWG_REMOTE:-origin}"
REMOTE_URL="${CLWG_REMOTE_URL:-}"
BRANCH="${CLWG_BRANCH:-main}"
SYNC_GIT="${CLWG_SYNC_GIT:-1}"
UPGRADE_PIP="${CLWG_UPGRADE_PIP:-0}"
FORCE_LOCAL_REPO="${CLWG_FORCE_LOCAL_REPO:-0}"
BOOTSTRAP_PYTHON="${CLAW_BOOTSTRAP_PYTHON:-}"

resolve_default_runtime_home() {
  if [[ -n "${CLAW_RUNTIME_HOME:-}" ]]; then
    printf "%s" "${CLAW_RUNTIME_HOME}"
    return 0
  fi
  case "${OSTYPE:-}" in
    darwin*)
      printf "%s" "${HOME}/Library/Application Support/Clawgotchi"
      ;;
    *)
      printf "%s" "${XDG_DATA_HOME:-${HOME}/.local/share}/clawgotchi"
      ;;
  esac
}

RUNTIME_HOME="$(resolve_default_runtime_home)"

is_true() {
  local value="${1:-}"
  local lowered
  lowered="$(printf "%s" "${value}" | tr '[:upper:]' '[:lower:]')"
  case "${lowered}" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_path() {
  local path_value="$1"
  python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "${path_value}"
}

maybe_delegate_to_managed_source() {
  local current_root managed_root managed_update_script

  if is_true "${FORCE_LOCAL_REPO}"; then
    log "Local repository mode enabled. Updating current checkout: ${PROJECT_ROOT}"
    return 0
  fi

  current_root="$(normalize_path "${PROJECT_ROOT}")"
  managed_root="$(normalize_path "${RUNTIME_HOME}/src")"
  managed_update_script="${managed_root}/update.sh"

  if [[ "${current_root}" == "${managed_root}" ]]; then
    return 0
  fi

  if [[ -x "${managed_update_script}" ]]; then
    log "Delegating update to managed workspace checkout: ${managed_root}"
    exec bash "${managed_update_script}" "$@"
  fi

  log "Managed workspace checkout not found at ${managed_root}; updating current checkout instead."
}

print_usage() {
  cat <<'EOF'
Usage: ./update.sh [--sync-git|--no-sync-git] [--upgrade-pip|--no-upgrade-pip] [--local-repo|--managed-repo]

Modes:
  --sync-git (default):    Update source checkout and refresh virtualenv/dependencies.
  --no-sync-git:           Skip git sync and only refresh virtualenv/dependencies.
  --no-upgrade-pip (default): Keep current pip version.
  --upgrade-pip:             Upgrade pip before reinstall.
  --managed-repo (default): Delegate updates to managed workspace checkout (<runtime_home>/src) when available.
  --local-repo:             Force update in current checkout (development mode).

Environment:
  CLWG_SYNC_GIT=1 enables git sync mode (default).
  CLWG_SYNC_GIT=0 disables git sync mode.
  CLWG_UPGRADE_PIP=1 enables pip self-upgrade.
  CLWG_FORCE_LOCAL_REPO=1 disables managed workspace delegation.
  CLAW_BOOTSTRAP_PYTHON=/path/to/python3.11 overrides the interpreter used for venv creation/recovery.
  CLAW_GIT_SSH_COMMAND can provide a custom SSH command for private repository access.
  CLAW_GIT_SSH_KEY=/path/to/key is converted to an SSH command automatically.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sync-git)
        SYNC_GIT="1"
        shift
        ;;
      --no-sync-git|--local-only)
        SYNC_GIT="0"
        shift
        ;;
      --upgrade-pip)
        UPGRADE_PIP="1"
        shift
        ;;
      --no-upgrade-pip)
        UPGRADE_PIP="0"
        shift
        ;;
      --local-repo)
        FORCE_LOCAL_REPO="1"
        shift
        ;;
      --managed-repo)
        FORCE_LOCAL_REPO="0"
        shift
        ;;
      -h|--help)
        print_usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

setup_git_ssh_environment() {
  if [[ -n "${CLAW_GIT_SSH_COMMAND:-}" ]]; then
    export GIT_SSH_COMMAND="${CLAW_GIT_SSH_COMMAND}"
    return 0
  fi

  if [[ -n "${CLAW_GIT_SSH_KEY:-}" ]]; then
    if [[ ! -f "${CLAW_GIT_SSH_KEY}" ]]; then
      die "CLAW_GIT_SSH_KEY is set but file does not exist: ${CLAW_GIT_SSH_KEY}"
    fi
    export GIT_SSH_COMMAND="ssh -i ${CLAW_GIT_SSH_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
  fi
}

run_desktop_update() {
  local source_root bootstrap_script common_install_script bootstrap_python
  local -a bootstrap_args

  source_root="${RUNTIME_HOME}/src"
  if is_true "${FORCE_LOCAL_REPO}"; then
    source_root="${PROJECT_ROOT}"
  fi

  setup_git_ssh_environment

  if [[ "${SYNC_GIT_ENABLED}" == "true" ]]; then
    if is_true "${FORCE_LOCAL_REPO}" && [[ -d "${source_root}/.git" ]]; then
      if ! git -C "${source_root}" diff --quiet || ! git -C "${source_root}" diff --cached --quiet; then
        die "Local checkout has uncommitted changes. Commit/stash first, or run with --no-sync-git."
      fi
    fi

    bootstrap_script="${source_root}/scripts/install_bootstrap.sh"
    if [[ ! -x "${bootstrap_script}" ]]; then
      bootstrap_script="${PROJECT_ROOT}/scripts/install_bootstrap.sh"
    fi
    [[ -x "${bootstrap_script}" ]] || die "Bootstrap installer not found: ${bootstrap_script}"

    bootstrap_args=(--source-root "${source_root}")
    if [[ -n "${CLAW_REPO_URL:-}" ]]; then
      bootstrap_args+=(--repo-url "${CLAW_REPO_URL}")
    fi
    if [[ -n "${CLAW_BRANCH:-}" ]]; then
      bootstrap_args+=(--branch "${CLAW_BRANCH}")
    fi

    log "Desktop update via bootstrap: ${source_root}"
    bash "${bootstrap_script}" "${bootstrap_args[@]}"
    return 0
  fi

  common_install_script="${source_root}/scripts/common_install.py"
  [[ -f "${common_install_script}" ]] || die "Installer helper not found: ${common_install_script}"

  bootstrap_python="${BOOTSTRAP_PYTHON:-python3}"
  log "Desktop update without git sync: ${source_root}"
  "${bootstrap_python}" "${common_install_script}" --repo-root "${source_root}" --skip-smoke
}

resolve_venv_paths() {
  local requested_path="${CLAW_VENV_PATH:-}"

  if [[ -n "${requested_path}" ]]; then
    if [[ -f "${requested_path}" && -x "${requested_path}" ]]; then
      VENV_PYTHON="${requested_path}"
      VENV_DIR="$(cd "$(dirname "${requested_path}")/.." && pwd -P)"
      return 0
    fi
    VENV_DIR="${requested_path}"
  else
    if [[ -x "${RUNTIME_HOME}/venv/bin/python" ]]; then
      VENV_DIR="${RUNTIME_HOME}/venv"
    else
      VENV_DIR="${PROJECT_ROOT}/.venv"
    fi
  fi

  if [[ ! -x "${VENV_DIR}/bin/python" && -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    VENV_DIR="${PROJECT_ROOT}/.venv"
  fi

  VENV_PYTHON="${VENV_DIR}/bin/python"
}

VENV_DIR=""
VENV_PYTHON=""

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
    bash -c "${cmd}"
  fi
}

python_is_supported() {
  local python_cmd="$1"
  run_as_app "'${python_cmd}' -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'" >/dev/null 2>&1
}

resolve_python_command_path() {
  local command_name="$1"
  local resolved
  if ! run_as_app "command -v '${command_name}' >/dev/null 2>&1"; then
    return 1
  fi
  resolved="$(run_as_app "command -v '${command_name}'" 2>/dev/null | tail -n 1)"
  [[ -n "${resolved}" ]] || return 1
  printf "%s" "${resolved}"
}

select_bootstrap_python() {
  local raw_candidates=()
  local command_candidates=(
    python3.13
    python3.12
    python3.11
    python3
  )
  local explicit_candidates=(
    /opt/homebrew/bin/python3.13
    /opt/homebrew/bin/python3.12
    /opt/homebrew/bin/python3.11
    /usr/local/bin/python3.13
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
  )
  local candidate resolved base_from_venv dedupe_guard

  if [[ -n "${BOOTSTRAP_PYTHON}" ]]; then
    raw_candidates+=("${BOOTSTRAP_PYTHON}")
  fi

  if [[ -x "${VENV_PYTHON}" ]]; then
    base_from_venv="$(
      run_as_app "'${VENV_PYTHON}' -c \"import os,sys; print(os.path.realpath(getattr(sys, '_base_executable', sys.executable)))\"" \
        2>/dev/null | tail -n 1
    )"
    if [[ -n "${base_from_venv}" ]]; then
      raw_candidates+=("${base_from_venv}")
    fi
  fi

  for candidate in "${explicit_candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      raw_candidates+=("${candidate}")
    fi
  done

  for candidate in "${command_candidates[@]}"; do
    resolved="$(resolve_python_command_path "${candidate}" || true)"
    if [[ -n "${resolved}" ]]; then
      raw_candidates+=("${resolved}")
    fi
  done

  dedupe_guard="|"
  for candidate in "${raw_candidates[@]}"; do
    if [[ ! -x "${candidate}" ]]; then
      continue
    fi
    if [[ "${dedupe_guard}" == *"|${candidate}|"* ]]; then
      continue
    fi
    dedupe_guard="${dedupe_guard}${candidate}|"
    if python_is_supported "${candidate}"; then
      BOOTSTRAP_PYTHON="${candidate}"
      return 0
    fi
  done

  die "Python 3.11+ is required for updates. Current detected python3 is '$(
    run_as_app "python3 -V 2>/dev/null || true" | tail -n 1
  )'. Install Python 3.11+ and rerun, or set CLAW_BOOTSTRAP_PYTHON to a Python 3.11+ executable."
}

ensure_venv() {
  select_bootstrap_python

  if [[ ! -x "${VENV_PYTHON}" ]]; then
    log "Virtualenv missing. Creating ${VENV_DIR} with ${BOOTSTRAP_PYTHON}."
    run_as_app "'${BOOTSTRAP_PYTHON}' -m venv '${VENV_DIR}'"
  fi

  if ! python_is_supported "${VENV_PYTHON}"; then
    log "Virtualenv Python is below 3.11. Recreating ${VENV_DIR} with ${BOOTSTRAP_PYTHON}."
    run_as_app "rm -rf '${VENV_DIR}'"
    run_as_app "'${BOOTSTRAP_PYTHON}' -m venv '${VENV_DIR}'"
  fi

  if ! run_as_app "'${VENV_PYTHON}' -m pip --version" >/dev/null 2>&1; then
    log "Virtualenv tooling is broken. Recreating ${VENV_DIR} with ${BOOTSTRAP_PYTHON}."
    run_as_app "rm -rf '${VENV_DIR}'"
    run_as_app "'${BOOTSTRAP_PYTHON}' -m venv '${VENV_DIR}'"
  fi

  if ! python_is_supported "${VENV_PYTHON}"; then
    die "Virtualenv Python must be >=3.11, but '${VENV_PYTHON}' is not compatible. Set CLAW_BOOTSTRAP_PYTHON to a Python 3.11+ interpreter and retry."
  fi
}

install_editable_package() {
  local editable_install_cmd="'${VENV_PYTHON}' -m pip install --no-build-isolation -e '${PROJECT_ROOT}'"

  if run_as_app "${editable_install_cmd}"; then
    return 0
  fi

  log "Editable install failed. Trying pip self-upgrade for editable compatibility."
  if run_as_app "'${VENV_PYTHON}' -m pip install --upgrade pip"; then
    if run_as_app "${editable_install_cmd}"; then
      return 0
    fi
  else
    log "Pip self-upgrade fallback failed. Continuing with virtualenv recreation."
  fi

  log "Editable install failed. Recreating virtualenv once for self-heal."
  run_as_app "rm -rf '${VENV_DIR}'"
  run_as_app "'${BOOTSTRAP_PYTHON}' -m venv '${VENV_DIR}'"
  if ! run_as_app "'${VENV_PYTHON}' -m pip install --upgrade wheel setuptools"; then
    log "wheel/setuptools upgrade failed after venv recreation; retrying editable install anyway."
  fi
  if [[ "${UPGRADE_PIP_ENABLED}" == "true" ]]; then
    run_as_app "'${VENV_PYTHON}' -m pip install --upgrade pip"
  fi
  run_as_app "${editable_install_cmd}"
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

parse_args "$@"
SYNC_GIT_ENABLED="false"
if is_true "${SYNC_GIT}"; then
  SYNC_GIT_ENABLED="true"
fi
UPGRADE_PIP_ENABLED="false"
if is_true "${UPGRADE_PIP}"; then
  UPGRADE_PIP_ENABLED="true"
fi

if [[ "${EUID}" -ne 0 ]]; then
  run_desktop_update
  exit 0
fi

maybe_delegate_to_managed_source "$@"
resolve_venv_paths

if [[ "${EUID}" -eq 0 ]]; then
  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    die "App user '${APP_USER}' does not exist. Override via CLWG_USER if needed."
  fi
fi

write_status "running" "Update started." "0"
log "Using virtual environment: ${VENV_DIR}"
log "Using Python executable: ${VENV_PYTHON}"

had_reboot_marker_before="false"
if is_reboot_marker_present; then
  had_reboot_marker_before="true"
fi

if [[ "${SYNC_GIT_ENABLED}" == "true" ]]; then
  if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
    die "Git sync requested, but no Git repository exists at ${PROJECT_ROOT}."
  fi

  if ! run_git diff --quiet || ! run_git diff --cached --quiet; then
    die "Git sync mode requires a clean working tree. Commit/stash changes first, or run without --sync-git."
  fi

  if [[ -n "${REMOTE_URL}" ]]; then
    log "Ensuring git remote '${REMOTE}' points to configured URL."
    run_git remote set-url "${REMOTE}" "${REMOTE_URL}"
  fi

  log "Fetching updates from ${REMOTE}/${BRANCH}."
  if ! run_git fetch "${REMOTE}"; then
    die "Git fetch failed. Check repository access/credentials, or run with --no-sync-git."
  fi
  run_git checkout "${BRANCH}"
  run_git pull --ff-only "${REMOTE}" "${BRANCH}"
else
  log "Git sync disabled. Updating environment from selected checkout: ${PROJECT_ROOT}"
fi

ensure_venv
log "Using bootstrap Python: ${BOOTSTRAP_PYTHON}"
log "Installing/updating Python dependencies."
if [[ "${UPGRADE_PIP_ENABLED}" == "true" ]]; then
  run_as_app "'${VENV_PYTHON}' -m pip install --upgrade pip"
else
  log "Skipping pip self-upgrade (default). Use --upgrade-pip to enable."
fi
install_editable_package

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
