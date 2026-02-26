<#
Install-AdClassifierDashboard.ps1 — Install Ad-classifier Dashboard as a Windows service (NSSM)

Run as Administrator:
  Set-ExecutionPolicy RemoteSigned -Scope Process -Force
  cd <repo>\scripts\windows
  .\Install-AdClassifierDashboard.ps1
#>

[CmdletBinding()]
param(
  [string]$ServiceName = "AdClassifierDashboard",
  [string]$DashboardDir = "",
  [int]$Port = 5173,
  [string]$ApiBaseUrl = "http://localhost:8000",
  [string]$LogDir = "",
  [string]$NssmPath = "",
  [switch]$OpenFirewall = $true,
  [string]$LogonUser = "",
  [string]$LogonPass = ""
)

$ErrorActionPreference = "Stop"
$script:InstallerScriptDir = Split-Path -Parent $PSCommandPath

function Write-Step {
  param([string]$Message)
  Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Fail {
  param([string]$Message)
  throw $Message
}

function Test-IsAdmin {
  try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch {
    return $false
  }
}

function Invoke-Download {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile
  )
  $hasBasic = (Get-Command Invoke-WebRequest).Parameters.ContainsKey("UseBasicParsing")
  if ($hasBasic) {
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
  } else {
    Invoke-WebRequest -Uri $Url -OutFile $OutFile
  }
}

function Refresh-PathFromRegistry {
  $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user"
}

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [string[]]$ArgumentList = @(),
    [string]$FailureMessage = ""
  )
  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) {
    if ([string]::IsNullOrWhiteSpace($FailureMessage)) {
      $FailureMessage = "Command failed ($FilePath) with exit code $LASTEXITCODE."
    }
    throw $FailureMessage
  }
}

function Ensure-PowerShellVersion {
  $major = $PSVersionTable.PSVersion.Major
  $minor = $PSVersionTable.PSVersion.Minor
  Write-Host ("Detected PowerShell version: {0}.{1}" -f $major, $minor)
  if ($major -ge 5) { return }

  Write-Warning "PowerShell < 5 detected. Installing PowerShell 7..."
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    Fail "PowerShell is too old and winget is unavailable. Install PowerShell 7 manually, then re-run."
  }

  Invoke-Checked -FilePath $winget.Source -ArgumentList @(
    "install",
    "--id", "Microsoft.PowerShell",
    "--exact",
    "--source", "winget",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity"
  ) -FailureMessage "Failed to install PowerShell 7."

  Refresh-PathFromRegistry
  if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) {
    Fail "PowerShell 7 installed. Re-run this installer using: pwsh -File `"$PSCommandPath`""
  }
  Fail "PowerShell 7 installation attempted but pwsh.exe is not available in PATH yet. Re-open terminal and re-run."
}

function Resolve-RepoRoot {
  return (Resolve-Path (Join-Path $script:InstallerScriptDir "..\..")).Path
}

function Ensure-Nssm {
  Write-Step "Checking NSSM"
  if ($NssmPath -and (Test-Path $NssmPath)) {
    Write-Host "Using provided NSSM path: $NssmPath" -ForegroundColor Green
    return $NssmPath
  }

  $existing = Get-Command nssm.exe -ErrorAction SilentlyContinue
  if ($existing) {
    Write-Host "NSSM found: $($existing.Source)" -ForegroundColor Green
    return $existing.Source
  }

  $localNssm = Join-Path $script:InstallerScriptDir "nssm.exe"
  if (Test-Path $localNssm) {
    Write-Host "Using local NSSM: $localNssm" -ForegroundColor Green
    return $localNssm
  }

  Write-Host "Downloading NSSM 2.24..." -ForegroundColor Yellow
  $zipPath = Join-Path $env:TEMP "nssm-2.24.zip"
  $extractDir = Join-Path $env:TEMP "nssm_extract_$([guid]::NewGuid().ToString('N'))"
  Invoke-Download -Url "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zipPath
  Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

  $archFolder = "win32"
  if ([Environment]::Is64BitOperatingSystem) { $archFolder = "win64" }
  $sourceExe = Join-Path $extractDir "nssm-2.24\$archFolder\nssm.exe"
  if (-not (Test-Path $sourceExe)) {
    Fail "Downloaded NSSM archive did not contain expected binary: $sourceExe"
  }

  $installRoot = Join-Path $env:ProgramData "AdClassifier\nssm"
  New-Item -Path $installRoot -ItemType Directory -Force | Out-Null
  $installedExe = Join-Path $installRoot "nssm.exe"
  Copy-Item -Path $sourceExe -Destination $installedExe -Force
  Copy-Item -Path $sourceExe -Destination $localNssm -Force

  Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
  Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue

  Write-Host "NSSM installed: $installedExe" -ForegroundColor Green
  return $installedExe
}

function Ensure-Node {
  Write-Step "Checking Node.js + npm"
  $nodeCmd = Get-Command node.exe -ErrorAction SilentlyContinue
  $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $npmCmd) { $npmCmd = Get-Command npm.exe -ErrorAction SilentlyContinue }

  if ($nodeCmd -and $npmCmd) {
    $nodeVersion = (& $nodeCmd.Source -v 2>$null).Trim()
    Write-Host "Node.js found: $nodeVersion" -ForegroundColor Green
    return @{
      node = $nodeCmd.Source
      npm = $npmCmd.Source
    }
  }

  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    Fail "Node.js/npm not found and winget is unavailable. Install Node.js 20+ manually and re-run."
  }

  Write-Host "Installing Node.js LTS via winget..." -ForegroundColor Yellow
  Invoke-Checked -FilePath $winget.Source -ArgumentList @(
    "install",
    "--id", "OpenJS.NodeJS.LTS",
    "--exact",
    "--source", "winget",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity"
  ) -FailureMessage "Failed to install Node.js LTS."

  Refresh-PathFromRegistry
  $nodeCmd = Get-Command node.exe -ErrorAction SilentlyContinue
  $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $npmCmd) { $npmCmd = Get-Command npm.exe -ErrorAction SilentlyContinue }
  if (-not $nodeCmd -or -not $npmCmd) {
    Fail "Node.js installation did not yield usable node/npm executables."
  }

  $nodeVersion = (& $nodeCmd.Source -v 2>$null).Trim()
  Write-Host "Node.js installed: $nodeVersion" -ForegroundColor Green
  return @{
    node = $nodeCmd.Source
    npm = $npmCmd.Source
  }
}

function Ensure-ServeCommand {
  param(
    [string]$NpmExe
  )

  Write-Step "Checking static file server (serve)"
  $serveCmd = Get-Command serve.cmd -ErrorAction SilentlyContinue
  if (-not $serveCmd) {
    $serveCmd = Get-Command serve.exe -ErrorAction SilentlyContinue
  }
  if ($serveCmd) {
    Write-Host "serve found: $($serveCmd.Source)" -ForegroundColor Green
    return $serveCmd.Source
  }

  Write-Host "Installing serve globally..." -ForegroundColor Yellow
  Invoke-Checked -FilePath $NpmExe -ArgumentList @("install", "-g", "serve") -FailureMessage "Failed to install serve globally."
  Refresh-PathFromRegistry

  $serveCmd = Get-Command serve.cmd -ErrorAction SilentlyContinue
  if (-not $serveCmd) {
    $serveCmd = Get-Command serve.exe -ErrorAction SilentlyContinue
  }
  if ($serveCmd) {
    Write-Host "serve installed: $($serveCmd.Source)" -ForegroundColor Green
    return $serveCmd.Source
  }

  $npmPrefix = (& $NpmExe config get prefix 2>$null).Trim()
  if ($npmPrefix) {
    $candidate = Join-Path $npmPrefix "serve.cmd"
    if (Test-Path $candidate) {
      Write-Host "serve found at npm prefix: $candidate" -ForegroundColor Green
      return $candidate
    }
    $candidate = Join-Path $npmPrefix "node_modules\serve\build\main.js"
    if (Test-Path $candidate) {
      Write-Host "serve JS entrypoint found: $candidate" -ForegroundColor Green
      return $candidate
    }
  }

  Fail "serve command not found after npm global install."
}

function Ensure-FirewallRule {
  param(
    [string]$RuleName,
    [int]$LocalPort
  )
  $existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
  if ($existing) { return }
  New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $LocalPort | Out-Null
}

if (-not (Test-IsAdmin)) {
  Fail "Run this script as Administrator."
}

Ensure-PowerShellVersion
$repoRoot = Resolve-RepoRoot

if ([string]::IsNullOrWhiteSpace($DashboardDir)) {
  $DashboardDir = Join-Path $repoRoot "frontend"
}
if (-not (Test-Path $DashboardDir)) {
  Fail "Dashboard directory not found: $DashboardDir"
}

if ([string]::IsNullOrWhiteSpace($LogDir)) {
  $LogDir = Join-Path $repoRoot "logs"
}
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stdoutLog = Join-Path $LogDir "dashboard.out.log"
$stderrLog = Join-Path $LogDir "dashboard.err.log"

$nssm = Ensure-Nssm
$nodeTools = Ensure-Node
$nodeExe = $nodeTools.node
$npmExe = $nodeTools.npm

Write-Step "Installing dashboard dependencies"
Push-Location $DashboardDir
try {
  & $npmExe ci
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "npm ci failed; falling back to npm install"
    Invoke-Checked -FilePath $npmExe -ArgumentList @("install") -FailureMessage "npm install failed."
  }

  Write-Step "Building dashboard"
  $env:VITE_API_BASE_URL = $ApiBaseUrl
  Invoke-Checked -FilePath $npmExe -ArgumentList @("run", "build") -FailureMessage "npm run build failed."
} finally {
  Pop-Location
}

$distIndex = Join-Path $DashboardDir "dist\index.html"
if (-not (Test-Path $distIndex)) {
  Fail "Dashboard build output missing: $distIndex"
}
Write-Host "Build output detected: $distIndex" -ForegroundColor Green

$serveTarget = Ensure-ServeCommand -NpmExe $npmExe

Write-Step "Installing NSSM service '$ServiceName'"
try {
  & $nssm stop $ServiceName 2>$null | Out-Null
  & $nssm remove $ServiceName confirm 2>$null | Out-Null
} catch {}

if ($serveTarget.ToLowerInvariant().EndsWith(".js")) {
  $serviceExe = $nodeExe
  $serviceArgs = "`"$serveTarget`" -s dist -l $Port --single --no-clipboard"
} else {
  $serviceExe = $serveTarget
  $serviceArgs = "-s dist -l $Port --single --no-clipboard"
}

Invoke-Checked -FilePath $nssm -ArgumentList @("install", $ServiceName, $serviceExe, $serviceArgs) -FailureMessage "Failed to install dashboard NSSM service."
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppDirectory", $DashboardDir)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "DisplayName", $ServiceName)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "Description", "Ad-classifier dashboard static web UI")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "Start", "SERVICE_AUTO_START")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppStdout", $stdoutLog)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppStderr", $stderrLog)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRotateFiles", "1")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRotateOnline", "1")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRotateBytes", "10485760")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppNoConsole", "1")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppExit", "Default", "Restart")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRestartDelay", "5000")

if (-not [string]::IsNullOrWhiteSpace($LogonUser)) {
  Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "ObjectName", $LogonUser, $LogonPass)
}

if ($OpenFirewall) {
  Write-Step "Configuring Windows Firewall"
  Ensure-FirewallRule -RuleName "$ServiceName $Port" -LocalPort $Port
}

Write-Step "Starting dashboard service"
Start-Service -Name $ServiceName
Start-Sleep -Seconds 2
$svc = Get-Service -Name $ServiceName

Write-Step "Dashboard installation complete"
Write-Host "Service Name: $ServiceName"
Write-Host "Service Status: $($svc.Status)"
Write-Host "Dashboard URL: http://localhost:$Port"
Write-Host "API base URL baked into build: $ApiBaseUrl"
Write-Host "stdout log: $stdoutLog"
Write-Host "stderr log: $stderrLog"
