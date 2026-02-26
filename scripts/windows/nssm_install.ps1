<#
nssm_install.ps1 — Windows bootstrap + NSSM service install for Video Ad Classifier

Run as Administrator:
  Set-ExecutionPolicy RemoteSigned -Scope Process -Force
  cd <repo>\scripts\windows
  .\nssm_install.ps1
#>

param(
  [string]$ServiceName = "AdClassifierAPI",
  [string]$BindHost = "0.0.0.0",
  [int]$Port = 8000,
  [string]$NodeName = "node-a",
  [int]$WorkerProcesses = 2,
  [int]$PipelineThreadsPerJob = 1,
  [string]$LogLevel = "INFO",
  [string]$VenvPath = "",
  [string]$DatabasePath = "",
  [string]$UploadDir = "",
  [string]$ArtifactsDir = "",
  [string]$ClusterConfig = "",
  [bool]$InstallOllama = $true,
  [bool]$PullDefaultModel = $true,
  [string]$DefaultModel = "qwen3-vl:8b-instruct",
  [switch]$SkipVenvSetup = $false,
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

function Ensure-PowerShellVersion {
  $major = $PSVersionTable.PSVersion.Major
  $minor = $PSVersionTable.PSVersion.Minor
  Write-Host ("Detected PowerShell version: {0}.{1}" -f $major, $minor)

  if ($major -ge 5) {
    return
  }

  Write-Warning "PowerShell < 5 detected. Installing PowerShell 7..."
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "PowerShell is too old and winget is unavailable. Install PowerShell 7 manually, then re-run."
  }
  & $winget.Source install --id Microsoft.PowerShell --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
  Refresh-PathFromRegistry
  $pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue
  if ($pwsh) {
    throw "PowerShell 7 installed. Re-run this installer using: pwsh -File `"$PSCommandPath`""
  }
  throw "PowerShell 7 installation attempted but pwsh.exe is not available in PATH yet. Re-open terminal and re-run."
}

function Resolve-RepoRoot {
  return (Resolve-Path (Join-Path $script:InstallerScriptDir "..\..")).Path
}

function Get-Python311Path {
  $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    try {
      $path = (& py -3.11 -c "import sys;print(sys.executable)" 2>$null)
      if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($path)) {
        return $path.Trim()
      }
    } catch {}
  }

  $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    try {
      $version = (& $pythonCmd.Source -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
      if ($LASTEXITCODE -eq 0) {
        $parts = $version.Split(".")
        $maj = [int]$parts[0]
        $min = [int]$parts[1]
        if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) {
          return $pythonCmd.Source
        }
      }
    } catch {}
  }
  return $null
}

function Ensure-Python311 {
  Write-Step "Checking Python 3.11+"
  $python = Get-Python311Path
  if ($python) {
    Write-Host "Using Python: $python" -ForegroundColor Green
    return $python
  }

  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "Python 3.11+ not found and winget is unavailable. Install Python 3.11 manually and re-run."
  }

  Write-Host "Installing Python 3.11 via winget..." -ForegroundColor Yellow
  & $winget.Source install --id Python.Python.3.11 --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
  Refresh-PathFromRegistry

  $python = Get-Python311Path
  if (-not $python) {
    throw "Python 3.11 installation did not yield a usable interpreter in PATH."
  }
  Write-Host "Python installed: $python" -ForegroundColor Green
  return $python
}

function Ensure-FFmpeg {
  Write-Step "Checking ffmpeg"
  $ff = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
  if ($ff) {
    Write-Host "ffmpeg found: $($ff.Source)" -ForegroundColor Green
    return
  }

  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-Warning "ffmpeg not found and winget unavailable. Install ffmpeg manually."
    return
  }

  Write-Host "Installing ffmpeg via winget..." -ForegroundColor Yellow
  & $winget.Source install --id Gyan.FFmpeg --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
  if ($LASTEXITCODE -ne 0) {
    & $winget.Source install --id BtbN.FFmpeg --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
  }
  Refresh-PathFromRegistry

  $ff = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
  if ($ff) {
    Write-Host "ffmpeg installed: $($ff.Source)" -ForegroundColor Green
  } else {
    Write-Warning "ffmpeg installation was attempted but ffmpeg.exe is still not in PATH."
  }
}

function Ensure-VCRedist {
  Write-Step "Checking Visual C++ Runtime"
  $required = @(
    "VCRUNTIME140_1.dll",
    "VCRUNTIME140.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll"
  )
  $sysDir = Join-Path $env:windir "System32"
  foreach ($name in $required) {
    if (Test-Path (Join-Path $sysDir $name)) {
      Write-Host "Visual C++ Runtime detected." -ForegroundColor Green
      return
    }
  }

  Write-Host "Installing Visual C++ Redistributable (x64)..." -ForegroundColor Yellow
  $installer = Join-Path $env:TEMP "vc_redist.x64.exe"
  Invoke-Download -Url "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $installer
  Start-Process -FilePath $installer -ArgumentList "/install", "/passive", "/norestart" -Wait
  if (Test-Path $installer) { Remove-Item $installer -Force }
}

function Ensure-Nssm {
  Write-Step "Checking NSSM"
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
    throw "Downloaded NSSM archive did not contain expected binary: $sourceExe"
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

function Ensure-Ollama {
  param(
    [bool]$InstallRequested,
    [bool]$PullModelRequested,
    [string]$ModelName
  )

  if (-not $InstallRequested) {
    Write-Host "Skipping Ollama installation by request." -ForegroundColor DarkYellow
    return
  }

  Write-Step "Checking Ollama"
  $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
  if (-not $ollama) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
      Write-Warning "Ollama not found and winget unavailable. Install Ollama manually if you use provider=Ollama."
      return
    }
    Write-Host "Installing Ollama via winget..." -ForegroundColor Yellow
    & $winget.Source install --id Ollama.Ollama --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    Refresh-PathFromRegistry
    $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
  }

  if (-not $ollama) {
    Write-Warning "Ollama installation was attempted but ollama.exe is not available."
    return
  }

  Write-Host "Ollama found: $($ollama.Source)" -ForegroundColor Green
  if ($PullModelRequested) {
    Write-Host "Pulling Ollama model '$ModelName' (can take several minutes)..." -ForegroundColor Yellow
    try {
      & $ollama.Source pull $ModelName
    } catch {
      Write-Warning "Failed to pull model '$ModelName'. You can run manually later: ollama pull $ModelName"
    }
  }
}

function Convert-ToEnvPath {
  param([string]$PathValue)
  return ($PathValue -replace "\\", "/")
}

function Format-EnvValue {
  param([string]$Value)
  if ($null -eq $Value) { return "" }
  if ($Value -match "\s") {
    return "'$Value'"
  }
  return $Value
}

function Set-EnvVarInFile {
  param(
    [string]$FilePath,
    [string]$Key,
    [string]$Value
  )

  $formatted = Format-EnvValue -Value $Value
  $line = "$Key=$formatted"

  if (-not (Test-Path $FilePath)) {
    Set-Content -Path $FilePath -Value $line -Encoding UTF8
    return
  }

  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.AddRange([string[]](Get-Content -Path $FilePath))

  $matched = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*$([regex]::Escape($Key))\s*=") {
      if (-not $matched) {
        $lines[$i] = $line
        $matched = $true
      } else {
        $lines.RemoveAt($i)
        $i--
      }
    }
  }

  if (-not $matched) {
    $lines.Add($line)
  }

  Set-Content -Path $FilePath -Value $lines -Encoding UTF8
}

function Ensure-FirewallRule {
  param(
    [string]$RuleName,
    [int]$LocalPort
  )
  $existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
  if ($existing) {
    return
  }
  New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $LocalPort | Out-Null
}

if (-not (Test-IsAdmin)) {
  Write-Error "Run this script as Administrator."
  exit 1
}

Ensure-PowerShellVersion

$repoRoot = Resolve-RepoRoot

if ([string]::IsNullOrWhiteSpace($VenvPath)) {
  $VenvPath = Join-Path $repoRoot ".venv"
}
if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
  $DatabasePath = Join-Path $repoRoot "data\video_service.db"
}
if ([string]::IsNullOrWhiteSpace($UploadDir)) {
  $UploadDir = Join-Path $repoRoot "storage\uploads"
}
if ([string]::IsNullOrWhiteSpace($ArtifactsDir)) {
  $ArtifactsDir = Join-Path $repoRoot "storage\artifacts"
}

$logsDir = Join-Path $repoRoot "logs"
$stdoutLog = Join-Path $logsDir "service.out.log"
$stderrLog = Join-Path $logsDir "service.err.log"
$envFile = Join-Path $repoRoot ".env"
$envExample = Join-Path $repoRoot ".env.example"
$categoryCsv = Join-Path $repoRoot "video_service\data\categories.csv"

New-Item -Path (Split-Path $DatabasePath -Parent) -ItemType Directory -Force | Out-Null
New-Item -Path $UploadDir -ItemType Directory -Force | Out-Null
New-Item -Path $ArtifactsDir -ItemType Directory -Force | Out-Null
New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
New-Item -Path (Join-Path $repoRoot ".hf_cache") -ItemType Directory -Force | Out-Null

$python = Ensure-Python311
Ensure-FFmpeg
Ensure-VCRedist
$nssm = Ensure-Nssm
Ensure-Ollama -InstallRequested:$InstallOllama -PullModelRequested:$PullDefaultModel -ModelName $DefaultModel

Write-Step "Preparing .env"
if (-not (Test-Path $envFile)) {
  if (Test-Path $envExample) {
    Copy-Item -Path $envExample -Destination $envFile -Force
  } else {
    New-Item -Path $envFile -ItemType File -Force | Out-Null
  }
}

Set-EnvVarInFile -FilePath $envFile -Key "NODE_NAME" -Value $NodeName
Set-EnvVarInFile -FilePath $envFile -Key "PORT" -Value "$Port"
Set-EnvVarInFile -FilePath $envFile -Key "DATABASE_PATH" -Value (Convert-ToEnvPath $DatabasePath)
Set-EnvVarInFile -FilePath $envFile -Key "UPLOAD_DIR" -Value (Convert-ToEnvPath $UploadDir)
Set-EnvVarInFile -FilePath $envFile -Key "ARTIFACTS_DIR" -Value (Convert-ToEnvPath $ArtifactsDir)
Set-EnvVarInFile -FilePath $envFile -Key "CATEGORY_CSV_PATH" -Value (Convert-ToEnvPath $categoryCsv)
Set-EnvVarInFile -FilePath $envFile -Key "EMBED_WORKERS" -Value "true"
Set-EnvVarInFile -FilePath $envFile -Key "WORKER_PROCESSES" -Value "$WorkerProcesses"
Set-EnvVarInFile -FilePath $envFile -Key "PIPELINE_THREADS_PER_JOB" -Value "$PipelineThreadsPerJob"
Set-EnvVarInFile -FilePath $envFile -Key "LOG_LEVEL" -Value $LogLevel
if (-not [string]::IsNullOrWhiteSpace($ClusterConfig)) {
  Set-EnvVarInFile -FilePath $envFile -Key "CLUSTER_CONFIG" -Value (Convert-ToEnvPath $ClusterConfig)
}

Write-Step "Setting up Python virtual environment"
$venvPy = Join-Path $VenvPath "Scripts\python.exe"
if (-not $SkipVenvSetup) {
  if (-not (Test-Path $venvPy)) {
    & $python -m venv $VenvPath
  }
  if (-not (Test-Path $venvPy)) {
    throw "Virtual environment python not found at: $venvPy"
  }
  & $venvPy -m pip install --upgrade pip setuptools wheel
  & $venvPy -m pip install -r (Join-Path $repoRoot "requirements.txt")
  & $venvPy -m pip install "uvicorn[standard]" httpx pandas yt-dlp opencv-python easyocr
}

if (-not (Test-Path $venvPy)) {
  throw "Virtual environment python not found at: $venvPy"
}

Write-Step "Installing NSSM service '$ServiceName'"
try {
  & $nssm stop $ServiceName 2>$null | Out-Null
  & $nssm remove $ServiceName confirm 2>$null | Out-Null
} catch {}

$args = "-m uvicorn video_service.app.main:app --host $BindHost --port $Port --workers 1"
& $nssm install $ServiceName $venvPy $args
& $nssm set $ServiceName AppDirectory $repoRoot
& $nssm set $ServiceName DisplayName $ServiceName
& $nssm set $ServiceName Description "Video Ad Classifier API (FastAPI + embedded workers)"
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout $stdoutLog
& $nssm set $ServiceName AppStderr $stderrLog
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateOnline 1
& $nssm set $ServiceName AppRotateBytes 10485760
& $nssm set $ServiceName AppExit Default Restart
& $nssm set $ServiceName AppThrottle 5000

$hfHome = Convert-ToEnvPath (Join-Path $repoRoot ".hf_cache")
$envExtra = @(
  "PYTHONUNBUFFERED=1",
  "HF_HOME=$hfHome",
  "TOKENIZERS_PARALLELISM=false"
)
& $nssm set $ServiceName AppEnvironmentExtra ($envExtra -join "`n")

if (-not [string]::IsNullOrWhiteSpace($LogonUser)) {
  & $nssm set $ServiceName ObjectName $LogonUser $LogonPass
}

if ($OpenFirewall) {
  Write-Step "Configuring Windows Firewall"
  Ensure-FirewallRule -RuleName "$ServiceName $Port" -LocalPort $Port
}

Start-Service -Name $ServiceName
Start-Sleep -Seconds 2
$svc = Get-Service -Name $ServiceName

Write-Step "Installation complete"
Write-Host "Service Name: $ServiceName"
Write-Host "Service Status: $($svc.Status)"
Write-Host "API URL: http://$BindHost`:$Port"
Write-Host "OpenAPI Docs: http://localhost:$Port/docs"
Write-Host "stdout log: $stdoutLog"
Write-Host "stderr log: $stderrLog"
Write-Host ""
Write-Host "Notes:" -ForegroundColor Yellow
Write-Host "  - Uvicorn is configured with --workers 1."
Write-Host "  - Embedded workers are enabled via EMBED_WORKERS=true in .env."
Write-Host "  - If you use Ollama provider, ensure ollama is running and model '$DefaultModel' is available."
