<#
nssm_uninstall.ps1 — Remove Video Ad Classifier Windows service installed via NSSM.

Run as Administrator:
  Set-ExecutionPolicy RemoteSigned -Scope Process -Force
  cd <repo>\scripts\windows
  .\nssm_uninstall.ps1
#>

param(
  [string]$ServiceName = "AdClassifierAPI",
  [int]$Port = 8000,
  [switch]$RemoveFirewall = $true
)

$ErrorActionPreference = "Stop"
$script:InstallerScriptDir = Split-Path -Parent $PSCommandPath

function Test-IsAdmin {
  try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch {
    return $false
  }
}

function Resolve-NssmPath {
  $nssmCmd = Get-Command "nssm.exe" -ErrorAction SilentlyContinue
  if ($nssmCmd) {
    return $nssmCmd.Source
  }

  $local = Join-Path $script:InstallerScriptDir "nssm.exe"
  if (Test-Path $local) {
    return $local
  }

  $programData = Join-Path $env:ProgramData "AdClassifier\nssm\nssm.exe"
  if (Test-Path $programData) {
    return $programData
  }

  throw "nssm.exe not found. Install NSSM or run uninstall from scripts/windows where nssm.exe exists."
}

if (-not (Test-IsAdmin)) {
  Write-Error "Run this script as Administrator."
  exit 1
}

$nssm = Resolve-NssmPath

try {
  & $nssm stop $ServiceName 2>$null | Out-Null
} catch {}

& $nssm remove $ServiceName confirm

if ($RemoveFirewall) {
  $ruleName = "$ServiceName $Port"
  $rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  if ($rule) {
    Remove-NetFirewallRule -DisplayName $ruleName | Out-Null
  }
}

Write-Host "Service '$ServiceName' removed."
