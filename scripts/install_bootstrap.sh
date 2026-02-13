#!/usr/bin/env bash

set -Eeuo pipefail

DEFAULT_REPO_URL="https://github.com/DasLukas/Clawgotchi.git"
DEFAULT_BRANCH="main"

REPO_URL="${CLAW_REPO_URL:-${DEFAULT_REPO_URL}}"
REPO_URL_EXPLICIT=0
if [[ -n "${CLAW_REPO_URL:-}" ]]; then
  REPO_URL_EXPLICIT=1
fi
BRANCH="${CLAW_BRANCH:-${DEFAULT_BRANCH}}"
PYTHON_CMD="${CLAW_BOOTSTRAP_PYTHON:-}"
SOURCE_ROOT=""
DRY_RUN=0
SYSTEMD_REQUESTED=0

log() {
  printf "[clawgotchi-install] %s\n" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

usage() {
  cat <<'EOF'
Usage: install_bootstrap.sh [options]

Options:
  --repo-url <url>      Override repository URL.
  --branch <name>       Override git branch to install (default: main).
  --source-root <path>  Override source checkout location.
  --systemd             Request optional Raspberry Pi systemd/SPI guidance.
  --dry-run             Print actions without changing the system.
  -h, --help            Show this help message.

Environment:
  CLAW_BOOTSTRAP_PYTHON  Explicit Python interpreter for installer actions.
EOF
}

run() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "DRY-RUN $*"
    return 0
  fi
  "$@"
}

require_command() {
  local command_name="$1"
  local install_hint="$2"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    die "${command_name} is required. ${install_hint}"
  fi
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

python_meets_requirement() {
  local candidate="$1"
  "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

resolve_python_command() {
  local candidates=()
  local candidate resolved

  if [[ -n "${PYTHON_CMD}" ]]; then
    candidates+=("${PYTHON_CMD}")
  fi

  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    darwin)
      candidates+=(
        "/opt/homebrew/bin/python3.13"
        "/opt/homebrew/bin/python3.12"
        "/opt/homebrew/bin/python3.11"
        "/usr/local/bin/python3.13"
        "/usr/local/bin/python3.12"
        "/usr/local/bin/python3.11"
      )
      ;;
  esac

  candidates+=("python3.13" "python3.12" "python3.11" "python3")

  for candidate in "${candidates[@]}"; do
    if [[ "${candidate}" == /* ]]; then
      if [[ -x "${candidate}" ]] && python_meets_requirement "${candidate}"; then
        PYTHON_CMD="${candidate}"
        return 0
      fi
      continue
    fi

    if ! command -v "${candidate}" >/dev/null 2>&1; then
      continue
    fi

    resolved="$(command -v "${candidate}")"
    if [[ -x "${resolved}" ]] && python_meets_requirement "${resolved}"; then
      PYTHON_CMD="${resolved}"
      return 0
    fi
  done

  die "Python 3.11+ is required. On macOS install with 'brew install python@3.12', then rerun. You can also set CLAW_BOOTSTRAP_PYTHON=/opt/homebrew/bin/python3.12."
}

is_raspberry_pi() {
  [[ -f "/proc/device-tree/model" ]] && grep -qi "Raspberry Pi" /proc/device-tree/model
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo-url)
        [[ $# -ge 2 ]] || die "--repo-url requires a value."
        REPO_URL="$2"
        REPO_URL_EXPLICIT=1
        shift 2
        ;;
      --branch)
        [[ $# -ge 2 ]] || die "--branch requires a value."
        BRANCH="$2"
        shift 2
        ;;
      --source-root)
        [[ $# -ge 2 ]] || die "--source-root requires a value."
        SOURCE_ROOT="$2"
        shift 2
        ;;
      --systemd)
        SYSTEMD_REQUESTED=1
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

resolve_source_root() {
  local runtime_home=""
  if [[ -n "${SOURCE_ROOT}" ]]; then
    printf "%s" "${SOURCE_ROOT}"
    return 0
  fi

  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    darwin)
      runtime_home="${HOME}/Library/Application Support/Clawgotchi"
      ;;
    *)
      runtime_home="${XDG_DATA_HOME:-${HOME}/.local/share}/clawgotchi"
      ;;
  esac
  printf "%s" "${runtime_home}/src"
}

sync_repository() {
  local source_root="$1"

  backup_source_root() {
    local target_root="$1"
    local reason="$2"
    local timestamp backup_root
    timestamp="$(date +"%Y%m%d%H%M%S")"
    backup_root="${target_root}.backup.${timestamp}"
    log "Repository sync warning (${reason}). Moving current checkout to ${backup_root}"
    run mv "${target_root}" "${backup_root}"
  }

  clone_checkout() {
    local target_root="$1"
    local parent_dir
    parent_dir="$(dirname "${target_root}")"
    run mkdir -p "${parent_dir}"
    log "Cloning repository into ${target_root}"
    run git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${target_root}"
  }

  update_checkout() {
    local target_root="$1"
    if [[ "${REPO_URL_EXPLICIT}" == "1" ]]; then
      run git -C "${target_root}" remote set-url origin "${REPO_URL}"
    fi
    if run git -C "${target_root}" fetch --prune origin \
      && run git -C "${target_root}" checkout "${BRANCH}" \
      && run git -C "${target_root}" pull --ff-only origin "${BRANCH}"; then
      return 0
    fi
    return 1
  }

  if [[ -d "${source_root}/.git" ]]; then
    log "Updating existing source checkout in ${source_root}"
    if update_checkout "${source_root}"; then
      return 0
    fi
    backup_source_root "${source_root}" "git update failed"
    clone_checkout "${source_root}"
    return 0
  fi

  if [[ -e "${source_root}" && ! -d "${source_root}" ]]; then
    die "Source root exists and is not a directory: ${source_root}"
  fi

  if [[ -d "${source_root}" && -n "$(ls -A "${source_root}" 2>/dev/null || true)" ]]; then
    backup_source_root "${source_root}" "non-git directory found"
  fi

  clone_checkout "${source_root}"
}

offer_pi_systemd_path() {
  local source_root="$1"
  if ! is_raspberry_pi; then
    return 0
  fi

  if [[ "${SYSTEMD_REQUESTED}" == "1" ]]; then
    log "Raspberry Pi systemd/SPI setup requested."
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "DRY-RUN sudo bash '${source_root}/install.sh'"
      return 0
    fi
    log "Running legacy Raspberry Pi installer for systemd/SPI provisioning."
    sudo bash "${source_root}/install.sh"
    return 0
  fi

  log "Raspberry Pi detected. Desktop bootstrap is complete."
  if [[ -t 0 ]]; then
    local answer=""
    read -r -p "Run optional legacy Pi systemd/SPI installer now? [y/N]: " answer || true
    if [[ "${answer}" =~ ^[Yy]$ ]]; then
      if [[ "${DRY_RUN}" == "1" ]]; then
        log "DRY-RUN sudo bash '${source_root}/install.sh'"
      else
        sudo bash "${source_root}/install.sh"
      fi
    else
      log "Skipped optional Pi systemd/SPI provisioning."
    fi
  else
    log "To configure Pi SPI/systemd later, run: sudo bash '${source_root}/install.sh'"
  fi
}

main() {
  parse_args "$@"

  local uname_s
  uname_s="$(uname -s | tr '[:upper:]' '[:lower:]')"
  if [[ "${uname_s}" == "darwin" ]]; then
    require_command "git" "Install with: brew install git"
  else
    require_command "git" "Install using your package manager (for example: sudo apt install git)."
  fi
  resolve_python_command
  setup_git_ssh_environment

  local source_root
  source_root="$(resolve_source_root)"
  source_root="${source_root/#\~/${HOME}}"

  sync_repository "${source_root}"

  local common_install_script="${source_root}/scripts/common_install.py"
  if [[ ! -f "${common_install_script}" ]]; then
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "DRY-RUN skipping installer helper existence check: ${common_install_script}"
    else
      die "Missing installer helper: ${common_install_script}"
    fi
  fi

  local install_args=(
    "${common_install_script}"
    "--repo-root" "${source_root}"
    "--repo-url" "${REPO_URL}"
  )
  if [[ "${DRY_RUN}" == "1" ]]; then
    install_args+=("--dry-run")
  fi
  if [[ "${SYSTEMD_REQUESTED}" == "1" ]]; then
    install_args+=("--systemd")
  fi

  run "${PYTHON_CMD}" "${install_args[@]}"
  offer_pi_systemd_path "${source_root}"
}

main "$@"
