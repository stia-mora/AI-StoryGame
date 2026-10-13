<#
.SYNOPSIS
    Serve the built player frontend and API together on the local network.
.EXAMPLE
    .\scripts\lan.ps1 start
.EXAMPLE
    .\scripts\lan.ps1 status
.EXAMPLE
    .\scripts\lan.ps1 stop
#>
[CmdletBinding()]
param (
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "status",
    [ValidateRange(1024, 65535)]
    [int]$Port = 7860,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $ProjectDir "rpg"
$FrontendDir = Join-Path $ProjectDir "frontend"
$PythonPath = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectDir ".dev-logs\lan"
$StatePath = Join-Path $LogDir "backend-$Port.json"

function Get-Listener {
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Show-Addresses {
    Write-Host "Local player entry: http://localhost:$Port/play"
    Get-NetIPConfiguration | Where-Object {
        $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" -and $_.NetAdapter.HardwareInterface
    } | ForEach-Object {
        foreach ($address in $_.IPv4Address.IPAddress) {
            Write-Host "LAN player entry:   http://${address}:$Port/play"
        }
    }
}

if ($Action -eq "status") {
    $listeners = Get-Listener
    if ($listeners.Count -eq 0) {
        Write-Host "Service is not running on port $Port."
    } else {
        $listeners | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table
        if ($listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }) {
            Show-Addresses
        } else {
            Write-Host "Local-only listener. LAN access is not enabled yet."
        }
    }
    exit 0
}

if ($Action -eq "stop") {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        throw "No managed LAN process found. Other services will not be stopped."
    }
    $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($state.process_id)"
    if ($parent) {
        if ($parent.CreationDate.ToUniversalTime().Ticks -ne ([datetime]$state.started_at).ToUniversalTime().Ticks -or
            $parent.CommandLine -notmatch '-m uvicorn app:app --host 0\.0\.0\.0') {
            throw "Process identity changed. Refusing to stop an unrelated process."
        }
        # Windows virtualenv launchers may own a separate Python child listener.
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($state.process_id)" |
            Where-Object { $_.CommandLine -match '-m uvicorn app:app --host 0\.0\.0\.0' })
        foreach ($child in $children) {
            Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $StatePath
    Write-Host "Managed LAN service stopped."
    exit 0
}

if ((Get-Listener).Count -gt 0) {
    throw "Port $Port is already in use. Stop its existing service first, or select -Port with an unused port."
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "The project Python environment is missing: $PythonPath"
}
if (-not $SkipBuild) {
    Push-Location $FrontendDir
    try {
        $env:APP_VERSION = (Get-Content -LiteralPath (Join-Path $ProjectDir "VERSION") -Raw).Trim()
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "dist\Player.html"))) {
    throw "Built player frontend is missing. Run this script without -SkipBuild."
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$arguments = @("-X", "utf8", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "$Port")
if (Test-Path -LiteralPath (Join-Path $BackendDir ".env")) {
    $arguments += @("--env-file", ".env")
}
$server = Start-Process -FilePath $PythonPath -ArgumentList $arguments -WorkingDirectory $BackendDir `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogDir "backend-$Port-out.log") `
    -RedirectStandardError (Join-Path $LogDir "backend-$Port-err.log") -PassThru
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.Id)"
@{ process_id = $server.Id; started_at = $process.CreationDate.ToUniversalTime().ToString("o"); port = $Port } |
    ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    $server.Refresh()
    if ($server.HasExited) { throw "LAN service failed to start. See $LogDir." }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/play" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Show-Addresses
            Write-Host "Frontend and API share one origin. LAN players must sign in. Logs: $LogDir"
            exit 0
        }
    } catch {
        # Wait only for startup; the deadline remains bounded.
    }
} while ((Get-Date) -lt $deadline)
throw "Service startup timed out. See $LogDir."
