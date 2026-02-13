param(
  [switch]$DryRun,
  [switch]$Systemd,
  [string]$RepoUrl = $(if ($env:CLAW_REPO_URL) { $env:CLAW_REPO_URL } else { "https://github.com/DasLukas/Clawgotchi.git" }),
  [string]$Branch = $(if ($env:CLAW_BRANCH) { $env:CLAW_BRANCH } else { "main" }),
  [string]$SourceRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Log {
  param([string]$Message)
  Write-Host "[clawgotchi-install] $Message"
}

function Fail {
  param([string]$Message)
  throw "[clawgotchi-install] ERROR: $Message"
}

function Invoke-ExternalCommand {
  param(
    [string[]]$Command,
    [string]$Description
  )

  if ($DryRun) {
    Write-Log "DRY-RUN $Description"
    return
  }

  if ($Command.Count -eq 1) {
    & $Command[0]
  } else {
    & $Command[0] $Command[1..($Command.Count - 1)]
  }
  if ($LASTEXITCODE -ne 0) {
    Fail "Command failed: $Description (exit=$LASTEXITCODE)"
  }
}

$script:PythonCommand = @()

function Resolve-PythonCommand {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $script:PythonCommand = @("py", "-3")
    return
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    $script:PythonCommand = @("python")
    return
  }
  Fail "Python is required. Install Python 3.11+ and ensure 'py' or 'python' is in PATH."
}

function Invoke-Python {
  param(
    [string[]]$Arguments,
    [string]$Description
  )

  $fullCommand = @()
  $fullCommand += $script:PythonCommand
  $fullCommand += $Arguments
  Invoke-ExternalCommand -Command $fullCommand -Description $Description
}

function Assert-RequiredTools {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git is required. Install Git for Windows and rerun."
  }
  Resolve-PythonCommand
  Invoke-Python -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)") -Description "Check Python >= 3.11"
}

function Resolve-SourceRoot {
  if ($SourceRoot) {
    return [System.IO.Path]::GetFullPath($SourceRoot)
  }

  $runtimeHome = ""
  if ($env:CLAW_RUNTIME_HOME) {
    $runtimeHome = $env:CLAW_RUNTIME_HOME
  } elseif ($env:LOCALAPPDATA) {
    $runtimeHome = Join-Path $env:LOCALAPPDATA "Clawgotchi"
  } else {
    $runtimeHome = Join-Path $HOME "AppData\Local\Clawgotchi"
  }

  return [System.IO.Path]::GetFullPath((Join-Path $runtimeHome "src"))
}

function Sync-Repository {
  param([string]$RepoRoot)

  $gitDir = Join-Path $RepoRoot ".git"
  if (Test-Path $gitDir) {
    Write-Log "Updating existing source checkout in $RepoRoot"
    Invoke-ExternalCommand -Command @("git", "-C", $RepoRoot, "remote", "set-url", "origin", $RepoUrl) -Description "Set origin URL"
    Invoke-ExternalCommand -Command @("git", "-C", $RepoRoot, "fetch", "--prune", "origin") -Description "Fetch repository"
    Invoke-ExternalCommand -Command @("git", "-C", $RepoRoot, "checkout", $Branch) -Description "Checkout branch"
    Invoke-ExternalCommand -Command @("git", "-C", $RepoRoot, "pull", "--ff-only", "origin", $Branch) -Description "Pull latest branch"
    return
  }

  if ((Test-Path $RepoRoot) -and ((Get-ChildItem -Path $RepoRoot -Force | Measure-Object).Count -gt 0)) {
    Fail "Source root exists and is not an empty git checkout: $RepoRoot"
  }

  $parentDir = Split-Path -Path $RepoRoot -Parent
  if ($DryRun) {
    Write-Log "DRY-RUN New-Item -ItemType Directory -Force -Path `"$parentDir`""
  } else {
    New-Item -ItemType Directory -Force -Path $parentDir | Out-Null
  }
  Write-Log "Cloning repository into $RepoRoot"
  Invoke-ExternalCommand -Command @("git", "clone", "--branch", $Branch, "--single-branch", $RepoUrl, $RepoRoot) -Description "Clone repository"
}

function Run-CommonInstall {
  param([string]$RepoRoot)

  $commonInstall = Join-Path $RepoRoot "scripts\common_install.py"
  if (-not (Test-Path $commonInstall)) {
    Fail "Missing installer helper: $commonInstall"
  }

  $argsList = @($commonInstall, "--repo-root", $RepoRoot, "--repo-url", $RepoUrl)
  if ($DryRun) {
    $argsList += "--dry-run"
  }
  if ($Systemd) {
    $argsList += "--systemd"
  }

  Invoke-Python -Arguments $argsList -Description "Run common installer"
}

function Print-FinalInstructions {
  $runtimeHome = if ($env:CLAW_RUNTIME_HOME) {
    [System.IO.Path]::GetFullPath($env:CLAW_RUNTIME_HOME)
  } elseif ($env:LOCALAPPDATA) {
    [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Clawgotchi"))
  } else {
    [System.IO.Path]::GetFullPath((Join-Path $HOME "AppData\Local\Clawgotchi"))
  }

  $launcher = Join-Path $runtimeHome "bin\clawgotchi.ps1"
  Write-Log "Run now: & `"$launcher`""
  Write-Log "Optional: add `%LOCALAPPDATA%\Clawgotchi\bin` to PATH for easier launcher access."
}

try {
  Assert-RequiredTools
  $resolvedSourceRoot = Resolve-SourceRoot
  Sync-Repository -RepoRoot $resolvedSourceRoot
  Run-CommonInstall -RepoRoot $resolvedSourceRoot

  if ($Systemd) {
    Write-Log "Systemd provisioning is not available on Windows and was ignored."
  }

  Print-FinalInstructions
} catch {
  Write-Error $_
  exit 1
}
