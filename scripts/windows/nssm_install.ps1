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

  if ($major -ge 5) {
    return
  }

  Write-Warning "PowerShell < 5 detected. Installing PowerShell 7..."
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "PowerShell is too old and winget is unavailable. Install PowerShell 7 manually, then re-run."
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
  $pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue
  if ($pwsh) {
    throw "PowerShell 7 installed. Re-run this installer using: pwsh -File `"$PSCommandPath`""
  }
  throw "PowerShell 7 installation attempted but pwsh.exe is not available in PATH yet. Re-open terminal and re-run."
}

function Resolve-RepoRoot {
  return (Resolve-Path (Join-Path $script:InstallerScriptDir "..\..")).Path
}

function Get-IsArm64Host {
  if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64" -or $env:PROCESSOR_ARCHITEW6432 -eq "ARM64") {
    return $true
  }
  try {
    $archCodes = @(Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Architecture)
    if ($archCodes -contains 12) {
      return $true
    }
  } catch {}
  return $false
}

function Get-PythonCandidatePaths {
  $paths = [System.Collections.Generic.List[string]]::new()

  $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    try {
      $lines = & $pyLauncher.Source -0p 2>$null
      foreach ($line in $lines) {
        if ($line -match "([A-Za-z]:\\.*?python(?:3)?\.exe)") {
          $candidate = $Matches[1]
          if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $paths.Add($candidate)
          }
        }
      }
    } catch {}
  }

  $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    $paths.Add($pythonCmd.Source)
  }

  $paths.Add("C:\Program Files\Python311\python.exe")
  $paths.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"))

  return @($paths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)
}

function Get-PythonMetadata {
  param([string]$PythonExe)

  try {
    $payload = & $PythonExe -c "import json,platform,struct,sys,sysconfig;print(json.dumps({'major':sys.version_info.major,'minor':sys.version_info.minor,'micro':sys.version_info.micro,'machine':platform.machine(),'bits':struct.calcsize('P')*8,'exe':sys.executable,'platform_tag':sysconfig.get_platform()}))" 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($payload)) {
      return $null
    }
    $obj = $payload | ConvertFrom-Json
    return [PSCustomObject]@{
      Path = [string]$obj.exe
      Major = [int]$obj.major
      Minor = [int]$obj.minor
      Micro = [int]$obj.micro
      Machine = [string]$obj.machine
      Bits = [int]$obj.bits
      PlatformTag = [string]$obj.platform_tag
    }
  } catch {
    return $null
  }
}

function Select-Python311 {
  param([bool]$RequireX64 = $true)

  $candidates = [System.Collections.Generic.List[object]]::new()
  foreach ($candidatePath in (Get-PythonCandidatePaths)) {
    $meta = Get-PythonMetadata -PythonExe $candidatePath
    if ($meta) {
      $candidates.Add($meta)
    }
  }

  $eligible = @(
    $candidates | Where-Object {
      ($_.Major -gt 3 -or ($_.Major -eq 3 -and $_.Minor -ge 11))
    }
  )

  if ($RequireX64) {
    $eligible = @(
      $eligible | Where-Object {
        $_.Bits -eq 64 -and $_.PlatformTag.ToLowerInvariant() -match "amd64"
      }
    )
  }

  if (-not $eligible -or $eligible.Count -eq 0) {
    return $null
  }

  return ($eligible | Sort-Object -Property @{Expression = "Major"; Descending = $true}, @{Expression = "Minor"; Descending = $true}, @{Expression = "Micro"; Descending = $true} | Select-Object -First 1)
}

function Ensure-Python311 {
  Write-Step "Checking Python 3.11+"
  $isArmHost = Get-IsArm64Host
  $selected = Select-Python311 -RequireX64 $true
  if ($selected) {
    Write-Host ("Using Python: {0} ({1}, {2}-bit, {3}, {4}.{5}.{6})" -f $selected.Path, $selected.Machine, $selected.Bits, $selected.PlatformTag, $selected.Major, $selected.Minor, $selected.Micro) -ForegroundColor Green
    return $selected.Path
  }

  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "Compatible Python 3.11+ x64 not found and winget is unavailable. Install Python 3.11 x64 manually and re-run."
  }

  if ($isArmHost) {
    Write-Host "ARM64 host detected. Installing Python 3.11 x64 for wheel compatibility..." -ForegroundColor Yellow
  } else {
    Write-Host "Installing Python 3.11 x64 via winget..." -ForegroundColor Yellow
  }
  Invoke-Checked -FilePath $winget.Source -ArgumentList @(
    "install",
    "--id", "Python.Python.3.11",
    "--exact",
    "--source", "winget",
    "--architecture", "x64",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity"
  ) -FailureMessage "Failed to install Python 3.11 x64."
  Refresh-PathFromRegistry

  $selected = Select-Python311 -RequireX64 $true
  if ($selected) {
    Write-Host ("Python installed: {0} ({1}, {2}-bit, {3})" -f $selected.Path, $selected.Machine, $selected.Bits, $selected.PlatformTag) -ForegroundColor Green
    return $selected.Path
  }

  $fallback = Select-Python311 -RequireX64 $false
  if ($fallback) {
    throw ("Found Python {0} ({1}, {2}-bit) but this installer requires x64 Python for torch/opencv wheels. Install Python 3.11 x64 and re-run." -f $fallback.Path, $fallback.Machine, $fallback.Bits)
  }

  throw "Python 3.11 x64 installation did not yield a usable interpreter in PATH."
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

  function Resolve-OllamaPath {
    $ollamaCmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
      return $ollamaCmd.Source
    }

    $candidates = @(
      (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
      "C:\Program Files\Ollama\ollama.exe"
    )
    foreach ($candidate in $candidates) {
      if ($candidate -and (Test-Path $candidate)) {
        return $candidate
      }
    }
    return $null
  }

  if (-not $InstallRequested) {
    Write-Host "Skipping Ollama installation by request." -ForegroundColor DarkYellow
    return
  }

  Write-Step "Checking Ollama"
  $ollama = Resolve-OllamaPath
  if (-not $ollama) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
      Write-Warning "Ollama not found and winget unavailable. Install Ollama manually if you use provider=Ollama."
      return
    }
    Write-Host "Installing Ollama via winget..." -ForegroundColor Yellow
    & $winget.Source install --id Ollama.Ollama --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    $installExit = $LASTEXITCODE
    if ($installExit -ne 0) {
      Write-Warning "winget reported a non-zero exit during Ollama install/upgrade (exit=$installExit). Will verify local installation."
    }
    Refresh-PathFromRegistry
    $ollama = Resolve-OllamaPath
    if (-not $ollama) {
      throw "Failed to install Ollama and no local ollama.exe was found."
    }
  }

  if (-not $ollama) {
    Write-Warning "Ollama installation was attempted but ollama.exe is not available."
    return
  }

  Write-Host "Ollama found: $ollama" -ForegroundColor Green
  if ($PullModelRequested) {
    Write-Host "Pulling Ollama model '$ModelName' (can take several minutes)..." -ForegroundColor Yellow
    try {
      & $ollama pull $ModelName
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
    Invoke-Checked -FilePath $python -ArgumentList @("-m", "venv", $VenvPath) -FailureMessage "Failed to create Python virtual environment."
  }
  if (-not (Test-Path $venvPy)) {
    throw "Virtual environment python not found at: $venvPy"
  }
  Invoke-Checked -FilePath $venvPy -ArgumentList @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel") -FailureMessage "Failed to upgrade pip/setuptools/wheel."
  Invoke-Checked -FilePath $venvPy -ArgumentList @("-m", "pip", "install", "--only-binary=:all:", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu") -FailureMessage "Failed to install torch CPU wheels. Ensure Python is x64 3.11+ on ARM hosts."
  Invoke-Checked -FilePath $venvPy -ArgumentList @("-m", "pip", "install", "--only-binary=:all:", "-r", (Join-Path $repoRoot "requirements.txt")) -FailureMessage "Failed to install requirements.txt dependencies as binary wheels."
  Invoke-Checked -FilePath $venvPy -ArgumentList @("-m", "pip", "install", "--only-binary=:all:", "uvicorn[standard]", "httpx", "pandas", "yt-dlp", "opencv-python", "easyocr") -FailureMessage "Failed to install runtime dependencies as binary wheels."
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
Invoke-Checked -FilePath $nssm -ArgumentList @("install", $ServiceName, $venvPy, $args) -FailureMessage "Failed to install NSSM service."
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppDirectory", $repoRoot)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "DisplayName", $ServiceName)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "Description", "Video Ad Classifier API (FastAPI + embedded workers)")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "Start", "SERVICE_AUTO_START")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppStdout", $stdoutLog)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppStderr", $stderrLog)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRotateFiles", "1")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRotateOnline", "1")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppRotateBytes", "10485760")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppExit", "Default", "Restart")
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppThrottle", "5000")

$hfHome = Convert-ToEnvPath (Join-Path $repoRoot ".hf_cache")
$envExtra = @(
  "PYTHONUNBUFFERED=1",
  "HF_HOME=$hfHome",
  "TOKENIZERS_PARALLELISM=false"
)
Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "AppEnvironmentExtra", ($envExtra -join "`n"))

if (-not [string]::IsNullOrWhiteSpace($LogonUser)) {
  Invoke-Checked -FilePath $nssm -ArgumentList @("set", $ServiceName, "ObjectName", $LogonUser, $LogonPass)
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
