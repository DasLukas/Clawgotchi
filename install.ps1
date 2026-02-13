param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$ErrorActionPreference = "Stop"
$BootstrapUrl = if ($env:CLAW_INSTALL_BOOTSTRAP_URL) {
  $env:CLAW_INSTALL_BOOTSTRAP_URL
} else {
  "https://raw.githubusercontent.com/DasLukas/Clawgotchi/main/scripts/install_bootstrap.ps1"
}

$scriptContent = Invoke-RestMethod -Uri $BootstrapUrl
$tempFile = Join-Path $env:TEMP "clawgotchi-install-bootstrap.ps1"
Set-Content -Path $tempFile -Value $scriptContent -Encoding UTF8
& $tempFile @Args
