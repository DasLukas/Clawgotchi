param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$localCommonInstall = Join-Path $scriptDir "scripts\common_install.py"

if (Test-Path $localCommonInstall) {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $localCommonInstall --repo-root $scriptDir @Args
    exit $LASTEXITCODE
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $localCommonInstall --repo-root $scriptDir @Args
    exit $LASTEXITCODE
  }
  Write-Error "Python 3.11+ was not found in PATH."
  exit 1
}

$BootstrapUrl = if ($env:CLAW_INSTALL_BOOTSTRAP_URL) {
  $env:CLAW_INSTALL_BOOTSTRAP_URL
} else {
  "https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/scripts/install_bootstrap.ps1"
}

$scriptContent = Invoke-RestMethod -Uri $BootstrapUrl
$tempFile = Join-Path $env:TEMP "clawgotchi-install-bootstrap.ps1"
Set-Content -Path $tempFile -Value $scriptContent -Encoding UTF8
& $tempFile @Args
