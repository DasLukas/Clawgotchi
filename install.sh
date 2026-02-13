#!/usr/bin/env bash

if [ -z "${BASH_VERSION:-}" ]; then
  echo "ERROR: Please run with bash (example: sudo bash ./install.sh)." >&2
  exit 1
fi

set -Eeuo pipefail

# Clawgotchi installer for Raspberry Pi OS Lite/Minimal.
# Supports interactive and non-interactive execution.
# Dry-run mode: CLWG_DRYRUN=1 ./install.sh

INSTALLER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/opt/clawgotchi"
VENV_PATH="${PROJECT_ROOT}/.venv"
SERVICE_FILE="/etc/systemd/system/clawgotchi.service"
UPDATE_SERVICE_FILE="/etc/systemd/system/clawgotchi-update.service"
UPDATE_TIMER_FILE="/etc/systemd/system/clawgotchi-update.timer"
UPDATE_SCRIPT="/usr/local/bin/clawgotchi-update.sh"
AUTO_UPGRADES_FILE="/etc/apt/apt.conf.d/20auto-upgrades"

DEFAULT_USER="clawgotchi"
DEFAULT_UPDATE_TIME="03:30"

DRYRUN="${CLWG_DRYRUN:-0}"
CLWG_USER_VALUE="${CLWG_USER:-}"
CLWG_GIT_SSH_URL="${CLWG_GIT_SSH_URL:-}"
CLWG_GIT_HOST="${CLWG_GIT_HOST:-}"
CLWG_UPDATE_TIME="${CLWG_UPDATE_TIME:-}"
CLWG_SKIP_SSH_TEST="${CLWG_SKIP_SSH_TEST:-0}"

SELECTED_USER=""
SELECTED_GROUP=""
SELECTED_HOME=""
HARDWARE_SUPPLEMENTARY_GROUPS=""
INPUT_FD=0

if [[ "${1:-}" == "--bootstrap" ]]; then
  shift
  exec "${INSTALLER_ROOT}/scripts/install_bootstrap.sh" "$@"
fi

log() {
  printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$*"
}

warn() {
  log "WARNING: $*"
}

die() {
  log "ERROR: $*"
  exit 1
}

on_error() {
  local exit_code=$?
  local line_no="$1"
  log "ERROR: Command failed at line ${line_no}: ${BASH_COMMAND} (exit=${exit_code})"
  exit "${exit_code}"
}
trap 'on_error "$LINENO"' ERR

run() {
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: $*"
    return 0
  fi
  "$@"
}

run_shell() {
  local cmd="$1"
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: ${cmd}"
    return 0
  fi
  bash -lc "${cmd}"
}

run_as_user() {
  local cmd="$1"
  if [[ -z "${SELECTED_USER}" ]]; then
    die "Internal error: SELECTED_USER is empty."
  fi
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: su - ${SELECTED_USER} -c \"${cmd}\""
    return 0
  fi
  su - "${SELECTED_USER}" -c "${cmd}"
}

prompt_with_default() {
  local question="$1"
  local default_value="$2"
  local answer=""
  read -r -u "${INPUT_FD}" -p "${question} [${default_value}]: " answer || true
  if [[ -z "${answer}" ]]; then
    printf "%s" "${default_value}"
  else
    printf "%s" "${answer}"
  fi
}

is_noninteractive_requested() {
  [[ -n "${CLWG_USER_VALUE}" && -n "${CLWG_GIT_SSH_URL}" && -n "${CLWG_GIT_HOST}" && -n "${CLWG_UPDATE_TIME}" ]]
}

init_prompt_input() {
  if [[ -t 0 ]]; then
    INPUT_FD=0
    return 0
  fi

  if [[ -r "/dev/tty" ]]; then
    exec 3<>/dev/tty
    INPUT_FD=3
    return 0
  fi

  if is_noninteractive_requested; then
    INPUT_FD=0
    return 0
  fi

  die "No interactive TTY available. Provide CLWG_USER, CLWG_GIT_SSH_URL, CLWG_GIT_HOST and CLWG_UPDATE_TIME for non-interactive mode."
}

validate_update_time() {
  local value="$1"
  [[ "${value}" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]]
}

validate_git_url() {
  local value="$1"
  [[ "${value}" =~ ^git@[^:]+:[^[:space:]]+\.git$ || "${value}" =~ ^ssh://([^@/]+@)?[^/]+/.+\.git$ ]]
}

derive_git_host() {
  local git_url="$1"
  if [[ "${git_url}" =~ ^git@([^:/]+)[:/].+$ ]]; then
    printf "%s" "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "${git_url}" =~ ^ssh://([^@/]+@)?([^/:]+)(:[0-9]+)?/.+$ ]]; then
    printf "%s" "${BASH_REMATCH[2]}"
    return 0
  fi
  printf ""
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Please run as root (example: curl ... | sudo bash)."
  fi
}

check_platform() {
  if ! command -v apt-get >/dev/null 2>&1; then
    die "This installer expects a Debian/Raspberry Pi OS system with apt-get."
  fi

  if [[ -f "/proc/device-tree/model" ]] && grep -qi "Raspberry Pi" /proc/device-tree/model; then
    log "Detected Raspberry Pi platform."
  else
    warn "This does not look like a Raspberry Pi device. Installation continues, but hardware setup may be incomplete."
  fi
}

collect_user() {
  local candidate=""

  if [[ -n "${CLWG_USER_VALUE}" ]]; then
    candidate="${CLWG_USER_VALUE}"
  elif id -u "${DEFAULT_USER}" >/dev/null 2>&1; then
    candidate="${DEFAULT_USER}"
    log "Reusing existing user '${candidate}'."
  else
    candidate="$(prompt_with_default "Enter the Linux user that should run Clawgotchi" "${DEFAULT_USER}")"
  fi

  if [[ -z "${candidate}" ]]; then
    die "User name cannot be empty."
  fi

  if id -u "${candidate}" >/dev/null 2>&1; then
    log "Using existing user '${candidate}'."
  else
    log "Creating user '${candidate}'."
    run useradd --create-home --shell /bin/bash "${candidate}"
  fi

  SELECTED_USER="${candidate}"
  SELECTED_GROUP="$(id -gn "${SELECTED_USER}")"
  SELECTED_HOME="$(getent passwd "${SELECTED_USER}" | cut -d: -f6)"
  if [[ -z "${SELECTED_HOME}" ]]; then
    die "Could not determine home directory for user '${SELECTED_USER}'."
  fi
}

ensure_user_hardware_groups() {
  local required_groups=("gpio" "spi")
  local configured_groups=()

  for group_name in "${required_groups[@]}"; do
    if ! getent group "${group_name}" >/dev/null 2>&1; then
      warn "Linux group '${group_name}' does not exist. Skipping group assignment."
      continue
    fi

    configured_groups+=("${group_name}")
    if id -nG "${SELECTED_USER}" | tr ' ' '\n' | grep -Fxq "${group_name}"; then
      log "User '${SELECTED_USER}' is already in group '${group_name}'."
    else
      log "Adding user '${SELECTED_USER}' to group '${group_name}'."
      run usermod -aG "${group_name}" "${SELECTED_USER}"
    fi
  done

  HARDWARE_SUPPLEMENTARY_GROUPS="${configured_groups[*]}"
}

collect_git_values() {
  if [[ -z "${CLWG_GIT_SSH_URL}" ]]; then
    while true; do
      read -r -u "${INPUT_FD}" -p "Git SSH URL (required, example git@github.com:ORG/REPO.git): " CLWG_GIT_SSH_URL || true
      if [[ -n "${CLWG_GIT_SSH_URL}" ]] && validate_git_url "${CLWG_GIT_SSH_URL}"; then
        break
      fi
      warn "Please enter a valid SSH Git URL."
    done
  fi

  if ! validate_git_url "${CLWG_GIT_SSH_URL}"; then
    die "CLWG_GIT_SSH_URL must be an SSH URL like git@github.com:ORG/REPO.git or ssh://git@host/ORG/REPO.git"
  fi

  if [[ -z "${CLWG_GIT_HOST}" ]]; then
    CLWG_GIT_HOST="$(derive_git_host "${CLWG_GIT_SSH_URL}")"
    if [[ -n "${CLWG_GIT_HOST}" ]]; then
      log "Derived Git host: ${CLWG_GIT_HOST}"
    fi
  fi

  if [[ -z "${CLWG_GIT_HOST}" && ! is_noninteractive_requested ]]; then
    read -r -u "${INPUT_FD}" -p "Git host domain (optional, example github.com): " CLWG_GIT_HOST || true
  fi

  if [[ -z "${CLWG_UPDATE_TIME}" ]]; then
    if is_noninteractive_requested; then
      CLWG_UPDATE_TIME="${DEFAULT_UPDATE_TIME}"
    else
      CLWG_UPDATE_TIME="$(prompt_with_default "Nightly update time (HH:MM, Europe/Berlin)" "${DEFAULT_UPDATE_TIME}")"
    fi
  fi

  if ! validate_update_time "${CLWG_UPDATE_TIME}"; then
    die "Invalid CLWG_UPDATE_TIME '${CLWG_UPDATE_TIME}'. Expected HH:MM (24h)."
  fi

  log "Configured nightly update time: ${CLWG_UPDATE_TIME} Europe/Berlin"
}

collect_deploy_key_guidance_choice() {
  if is_noninteractive_requested; then
    log "Non-interactive mode detected. Deploy key write access recommendation: keep it read-only."
    return 0
  fi

  local answer=""
  read -r -u "${INPUT_FD}" -p "Enable write access for the deploy key? Recommended: no (read-only) [y/N]: " answer || true
  if [[ "${answer}" =~ ^[Yy]$ ]]; then
    warn "Write-enabled deploy keys are not recommended. Use read-only unless you have a strict requirement."
  else
    log "Read-only deploy key selected (recommended)."
  fi
}

install_packages() {
  log "Installing apt packages."
  run apt-get update
  run apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    openssh-client \
    python3 \
    python3-pip \
    python3-venv \
    unattended-upgrades \
    apt-listchanges

  if apt-cache show python3-lgpio >/dev/null 2>&1; then
    run apt-get install -y --no-install-recommends python3-lgpio
  else
    warn "Optional package python3-lgpio is not available in apt repositories."
  fi
}

setup_unattended_upgrades() {
  log "Configuring unattended upgrades."
  run dpkg-reconfigure -f noninteractive unattended-upgrades

  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: write ${AUTO_UPGRADES_FILE}"
  else
    cat >"${AUTO_UPGRADES_FILE}" <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
  fi

  run systemctl enable --now unattended-upgrades
}

ensure_spi_line_in_file() {
  local config_file="$1"

  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: ensure 'dtparam=spi=on' in ${config_file}"
    return 0
  fi

  if [[ ! -e "${config_file}" ]]; then
    run touch "${config_file}"
  fi

  if grep -Eq '^[[:space:]]*dtparam=spi=on([[:space:]]*#.*)?$' "${config_file}"; then
    log "SPI already set in ${config_file}."
    return 0
  fi

  if grep -Eq '^[[:space:]]*dtparam=spi=' "${config_file}"; then
    sed -i -E 's/^[[:space:]]*dtparam=spi=.*/dtparam=spi=on/' "${config_file}"
  else
    printf "\n# Added by Clawgotchi installer\ndtparam=spi=on\n" >>"${config_file}"
  fi

  log "Set dtparam=spi=on in ${config_file}."
}

ensure_spi_enabled_in_config() {
  if [[ ! -d "/boot" ]]; then
    warn "/boot directory not found. Please ensure dtparam=spi=on manually."
    return 0
  fi

  ensure_spi_line_in_file "/boot/config.txt"

  if [[ -e "/boot/firmware/config.txt" ]]; then
    ensure_spi_line_in_file "/boot/firmware/config.txt"
  fi
}

enable_spi_noninteractive() {
  log "Configuring SPI."
  if command -v raspi-config >/dev/null 2>&1; then
    if run raspi-config nonint do_spi 0; then
      log "SPI enabled via raspi-config."
    else
      warn "raspi-config failed to enable SPI automatically. Continue with manual fallback."
      warn "Manual command: sudo raspi-config nonint do_spi 0"
    fi
  else
    warn "raspi-config is not available. If this is a Raspberry Pi, enable SPI manually:"
    warn "  sudo raspi-config nonint do_spi 0"
  fi
  ensure_spi_enabled_in_config
}

write_hardware_sudoers_policy() {
  local sudoers_file="/etc/sudoers.d/clawgotchi-hw"
  local sudoers_line="${SELECTED_USER} ALL=(root) NOPASSWD: /usr/bin/raspi-config nonint do_spi 0, /usr/bin/tee /boot/config.txt, /usr/bin/tee /boot/firmware/config.txt, /usr/bin/systemctl start clawgotchi-update.service"

  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: write hardware sudoers policy to ${sudoers_file}"
    return 0
  fi

  printf "%s\n" "${sudoers_line}" >"${sudoers_file}"
  chmod 0440 "${sudoers_file}"
  log "Wrote hardware helper sudoers policy: ${sudoers_file}"
}

print_ssh_guidance() {
  log "SSH is optional and was not changed automatically."
  log "To enable SSH manually:"
  log "  sudo systemctl enable --now ssh"
  log "or:"
  log "  sudo raspi-config nonint do_ssh 0"
}

setup_ssh_for_git_user() {
  local ssh_dir="${SELECTED_HOME}/.ssh"
  local private_key="${ssh_dir}/id_ed25519"
  local public_key="${private_key}.pub"
  local known_hosts="${ssh_dir}/known_hosts"

  log "Preparing SSH directory for user '${SELECTED_USER}'."
  run mkdir -p "${ssh_dir}"
  run chmod 700 "${ssh_dir}"
  run touch "${known_hosts}"
  run chmod 600 "${known_hosts}"
  run chown -R "${SELECTED_USER}:${SELECTED_GROUP}" "${ssh_dir}"

  if [[ ! -f "${private_key}" ]]; then
    log "Generating SSH deploy key for '${SELECTED_USER}'."
    run_as_user "ssh-keygen -t ed25519 -N '' -f '${private_key}' -C 'clawgotchi-deploy@$(hostname -s)'"
  else
    log "Reusing existing SSH key: ${private_key}"
  fi

  if [[ -n "${CLWG_GIT_HOST}" ]]; then
    if [[ "${DRYRUN}" == "1" ]]; then
      log "DRYRUN: ssh-keyscan -H ${CLWG_GIT_HOST} >> ${known_hosts}"
    else
      if ssh-keygen -F "${CLWG_GIT_HOST}" -f "${known_hosts}" >/dev/null 2>&1; then
        log "known_hosts already contains ${CLWG_GIT_HOST}."
      else
        local scan_output
        scan_output="$(ssh-keyscan -H "${CLWG_GIT_HOST}" 2>/dev/null || true)"
        if [[ -n "${scan_output}" ]]; then
          printf "%s\n" "${scan_output}" >>"${known_hosts}"
          chown "${SELECTED_USER}:${SELECTED_GROUP}" "${known_hosts}"
          log "Added ${CLWG_GIT_HOST} host key to ${known_hosts}."
        else
          warn "ssh-keyscan failed for ${CLWG_GIT_HOST}. You may need to trust the host key manually."
        fi
      fi
    fi
  else
    warn "Git host is empty. Skipping ssh-keyscan and SSH auth pre-test."
  fi

  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: display public deploy key from ${public_key}"
  else
    log "Public deploy key (add this as Deploy Key in your Git hosting platform):"
    log "GitHub: Repository -> Settings -> Deploy keys -> Add deploy key (read-only recommended)."
    log "GitLab: Project -> Settings -> Repository -> Deploy keys -> Add new key (read-only recommended)."
    printf -- "\n----- BEGIN DEPLOY KEY -----\n"
    cat "${public_key}"
    printf -- "----- END DEPLOY KEY -----\n\n"
  fi
}

test_ssh_auth() {
  if [[ -z "${CLWG_GIT_HOST}" ]]; then
    warn "Cannot test SSH auth without CLWG_GIT_HOST."
    return 1
  fi

  local ssh_cmd="ssh -o BatchMode=yes -o ConnectTimeout=10 -T git@${CLWG_GIT_HOST}"
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: su - ${SELECTED_USER} -c \"${ssh_cmd}\""
    return 0
  fi

  local output=""
  local rc=0
  set +e
  output="$(su - "${SELECTED_USER}" -c "${ssh_cmd}" 2>&1)"
  rc=$?
  set -e

  printf "%s\n" "${output}"
  if [[ "${rc}" -eq 0 ]]; then
    return 0
  fi

  if grep -Eqi "successfully authenticated|welcome|shell access is not provided|authenticated" <<<"${output}"; then
    return 0
  fi

  return 1
}

confirm_deploy_key_and_test() {
  if is_noninteractive_requested; then
    if [[ "${CLWG_SKIP_SSH_TEST}" == "1" ]]; then
      warn "Skipping SSH auth test because CLWG_SKIP_SSH_TEST=1."
      return 0
    fi

    if [[ -z "${CLWG_GIT_HOST}" ]]; then
      warn "CLWG_GIT_HOST not set in non-interactive mode. Skipping SSH auth test."
      return 0
    fi

    log "Running SSH auth test in non-interactive mode."
    if test_ssh_auth; then
      log "SSH auth test passed."
      return 0
    fi
    die "SSH auth test failed. Add deploy key and rerun, or set CLWG_SKIP_SSH_TEST=1 to bypass the test."
  fi

  while true; do
    local answer=""
    read -r -u "${INPUT_FD}" -p "Type 'continue' after adding the deploy key, 'skip' to skip SSH test, or 'abort': " answer || true
    case "${answer}" in
      continue|CONTINUE)
        if [[ -z "${CLWG_GIT_HOST}" ]]; then
          warn "Git host is empty; cannot run SSH auth test. Continuing."
          return 0
        fi
        log "Testing SSH auth against git@${CLWG_GIT_HOST}."
        if test_ssh_auth; then
          log "SSH auth test passed."
          return 0
        fi
        warn "SSH auth test failed. Verify deploy key and repository access."
        ;;
      skip|SKIP)
        warn "SSH auth test skipped by user request."
        return 0
        ;;
      abort|ABORT)
        die "Installer aborted by user."
        ;;
      *)
        warn "Please type 'continue', 'skip', or 'abort'."
        ;;
    esac
  done
}

prepare_project_directory() {
  log "Preparing project directory ${PROJECT_ROOT}."
  run mkdir -p "${PROJECT_ROOT}"
  run chown -R "${SELECTED_USER}:${SELECTED_GROUP}" "${PROJECT_ROOT}"
}

sync_repository() {
  log "Synchronizing repository in ${PROJECT_ROOT}."

  if [[ -d "${PROJECT_ROOT}/.git" ]]; then
    run_as_user "cd '${PROJECT_ROOT}' && git remote set-url origin '${CLWG_GIT_SSH_URL}' && git fetch origin && git checkout main && git pull --ff-only origin main"
    return 0
  fi

  if [[ -n "$(ls -A "${PROJECT_ROOT}" 2>/dev/null || true)" ]]; then
    die "${PROJECT_ROOT} exists and is not an empty Git repository. Please clean it first."
  fi

  run_as_user "git clone '${CLWG_GIT_SSH_URL}' '${PROJECT_ROOT}'"
  run_as_user "cd '${PROJECT_ROOT}' && git checkout main"
}

setup_venv_and_dependencies() {
  log "Setting up Python virtual environment at ${VENV_PATH}."
  if [[ ! -x "${VENV_PATH}/bin/python" ]]; then
    run_as_user "python3 -m venv '${VENV_PATH}'"
  else
    log "Reusing existing virtual environment."
  fi

  run_as_user "'${VENV_PATH}/bin/pip' install --upgrade pip setuptools wheel"
  run_as_user "cd '${PROJECT_ROOT}' && '${VENV_PATH}/bin/pip' install -e ."
}

write_update_script() {
  log "Writing update helper script: ${UPDATE_SCRIPT}"
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: write ${UPDATE_SCRIPT}"
    return 0
  fi

  cat >"${UPDATE_SCRIPT}" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

export CLWG_USER="${SELECTED_USER}"
export CLWG_REMOTE="origin"
export CLWG_BRANCH="main"
export CLWG_REMOTE_URL="${CLWG_GIT_SSH_URL}"
export CLWG_SERVICE_NAME="clawgotchi.service"
export CLWG_UPDATE_STATUS_FILE="/tmp/clawgotchi-update-status.env"

exec "${PROJECT_ROOT}/update.sh"
EOF

  run chmod 0755 "${UPDATE_SCRIPT}"
  run chown root:root "${UPDATE_SCRIPT}"
}

write_main_service() {
  local supplementary_groups_line=""
  if [[ -n "${HARDWARE_SUPPLEMENTARY_GROUPS}" ]]; then
    supplementary_groups_line="SupplementaryGroups=${HARDWARE_SUPPLEMENTARY_GROUPS}"
  fi

  log "Writing systemd service: ${SERVICE_FILE}"
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: write ${SERVICE_FILE}"
    return 0
  fi

  cat >"${SERVICE_FILE}" <<EOF
[Unit]
Description=Clawgotchi Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SELECTED_USER}
Group=${SELECTED_GROUP}
${supplementary_groups_line}
WorkingDirectory=${PROJECT_ROOT}
ExecStart=${VENV_PATH}/bin/python ${PROJECT_ROOT}/main.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  run chmod 0644 "${SERVICE_FILE}"
  run chown root:root "${SERVICE_FILE}"
}

write_update_service() {
  log "Writing systemd service: ${UPDATE_SERVICE_FILE}"
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: write ${UPDATE_SERVICE_FILE}"
    return 0
  fi

  cat >"${UPDATE_SERVICE_FILE}" <<EOF
[Unit]
Description=Clawgotchi Update Service
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${UPDATE_SCRIPT}
EOF

  run chmod 0644 "${UPDATE_SERVICE_FILE}"
  run chown root:root "${UPDATE_SERVICE_FILE}"
}

write_update_timer() {
  local on_calendar="*-*-* ${CLWG_UPDATE_TIME}:00"
  log "Writing systemd timer: ${UPDATE_TIMER_FILE} (${on_calendar} Europe/Berlin)"
  if [[ "${DRYRUN}" == "1" ]]; then
    log "DRYRUN: write ${UPDATE_TIMER_FILE}"
    return 0
  fi

  cat >"${UPDATE_TIMER_FILE}" <<EOF
[Unit]
Description=Clawgotchi Nightly Update Timer

[Timer]
OnCalendar=${on_calendar}
Persistent=true
Timezone=Europe/Berlin
Unit=clawgotchi-update.service

[Install]
WantedBy=timers.target
EOF

  run chmod 0644 "${UPDATE_TIMER_FILE}"
  run chown root:root "${UPDATE_TIMER_FILE}"
}

enable_services() {
  log "Reloading systemd units."
  run systemctl daemon-reload

  log "Enabling and starting clawgotchi.service."
  run systemctl enable --now clawgotchi.service

  log "Enabling and starting clawgotchi-update.timer."
  run systemctl enable --now clawgotchi-update.timer
}

print_final_summary() {
  local ip_addr="localhost"
  local service_state="unknown"
  local service_enabled="unknown"
  local next_run="unknown"

  if [[ "${DRYRUN}" != "1" ]]; then
    ip_addr="$(hostname -I | awk '{print $1}')"
    if [[ -z "${ip_addr}" ]]; then
      ip_addr="localhost"
    fi

    service_state="$(systemctl is-active clawgotchi.service 2>/dev/null || true)"
    service_enabled="$(systemctl is-enabled clawgotchi.service 2>/dev/null || true)"
    next_run="$(systemctl show clawgotchi-update.timer -p NextElapseUSecRealtime --value 2>/dev/null || true)"
    if [[ -z "${next_run}" ]]; then
      next_run="n/a"
    fi
  fi

  printf "\n"
  log "Installation summary"
  log "Service active state: ${service_state}"
  log "Service enabled state: ${service_enabled}"
  log "Timer next run: ${next_run}"
  log "REST UI: http://${ip_addr}:8000/"
  log "Service logs: journalctl -u clawgotchi -f"
  log "Update logs: journalctl -u clawgotchi-update.service -n 50"
  printf "\n"
}

main() {
  if [[ "${EUID}" -ne 0 ]]; then
    if [[ -x "${INSTALLER_ROOT}/scripts/install_bootstrap.sh" ]]; then
      warn "Root privileges were not provided. Delegating to cross-platform user installer."
      exec "${INSTALLER_ROOT}/scripts/install_bootstrap.sh" "$@"
    fi
    die "Please run as root (example: curl ... | sudo bash)."
  fi

  require_root
  check_platform
  init_prompt_input

  log "Starting Clawgotchi installer."
  if [[ "${DRYRUN}" == "1" ]]; then
    log "Dry-run mode enabled. No changes will be applied."
  fi

  collect_user
  ensure_user_hardware_groups
  collect_git_values
  collect_deploy_key_guidance_choice

  install_packages
  setup_unattended_upgrades
  enable_spi_noninteractive
  write_hardware_sudoers_policy
  print_ssh_guidance

  setup_ssh_for_git_user
  confirm_deploy_key_and_test

  prepare_project_directory
  sync_repository
  run chown -R "${SELECTED_USER}:${SELECTED_GROUP}" "${PROJECT_ROOT}"
  setup_venv_and_dependencies

  write_update_script
  write_main_service
  write_update_service
  write_update_timer
  enable_services

  print_final_summary
}

main "$@"
