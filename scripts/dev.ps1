<#
.SYNOPSIS
    Windows PowerShell one-click dev script for RPG Roleplay Platform
.DESCRIPTION
    Manages backend (FastAPI :7860), frontend (Vite :5173), and PostgreSQL (pgvector :5433).
.EXAMPLE
    .\scripts\dev.ps1 start
    .\scripts\dev.ps1 stop
    .\scripts\dev.ps1 status
#>
[CmdletBinding()]
param (
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status"
)

$RootDir = Resolve-Path "$PSScriptRoot\.."
$RpgDir = Join-Path $RootDir "rpg"
$FrontendDir = Join-Path $RootDir "frontend"
$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"

function Ensure-Postgres {
    $c = docker ps -q --filter "name=rpg-postgres"
    if (-not $c) {
        Write-Host "PostgreSQL container is not running, starting..." -ForegroundColor Yellow
        $exists = docker ps -a -q --filter "name=rpg-postgres"
        if ($exists) {
            docker start rpg-postgres | Out-Null
        } else {
            docker run --name rpg-postgres -d --restart unless-stopped -p 127.0.0.1:5433:5432 -v rpg_postgres_data:/var/lib/postgresql/data -e POSTGRES_DB=rpg -e POSTGRES_USER=rpg -e POSTGRES_PASSWORD=rpg_dev pgvector/pgvector:pg16 | Out-Null
            Start-Sleep -Seconds 3
            docker exec rpg-postgres psql -U rpg -d rpg -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS pgcrypto;" | Out-Null
        }
    }
    Write-Host "[OK] PostgreSQL (pgvector) on port 5433" -ForegroundColor Green
}

function Start-Dev {
    Ensure-Postgres

    # Backend
    $backendConn = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
    if (-not $backendConn) {
        Write-Host "Starting backend (Uvicorn :7860)..." -ForegroundColor Cyan
        Start-Process -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "app:app", "--port", "7860", "--reload" -WorkingDirectory $RpgDir -WindowStyle Minimized
        Start-Sleep -Seconds 2
    } else {
        Write-Host "[OK] Backend already running on port 7860" -ForegroundColor Green
    }

    # Frontend
    $frontendConn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    if (-not $frontendConn) {
        Write-Host "Starting frontend (Vite :5173)..." -ForegroundColor Cyan
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm", "run", "dev" -WorkingDirectory $FrontendDir -WindowStyle Minimized
        Start-Sleep -Seconds 2
    } else {
        Write-Host "[OK] Frontend already running on port 5173" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host "RPG Roleplay dev environment ready!" -ForegroundColor Green
    Write-Host "  Login:    http://localhost:5173/Login.html" -ForegroundColor Yellow
    Write-Host "  Platform: http://localhost:5173/Platform.html" -ForegroundColor Yellow
    Write-Host "  Console:  http://localhost:5173/Game%20Console.html" -ForegroundColor Yellow
    Write-Host "  Tavern:   http://localhost:5173/Tavern.html" -ForegroundColor Yellow
    Write-Host "  API Docs: http://localhost:7860/docs" -ForegroundColor Yellow
    Write-Host "================================================" -ForegroundColor Cyan
}

function Stop-Dev {
    Write-Host "Stopping backend and frontend processes..." -ForegroundColor Yellow
    $conns = Get-NetTCPConnection -LocalPort 7860, 5173 -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped process on port $($c.LocalPort) (PID: $($c.OwningProcess))" -ForegroundColor Gray
        } catch {}
    }
    Write-Host "[OK] Services stopped" -ForegroundColor Green
}

function Show-Status {
    $pg = docker ps -q --filter "name=rpg-postgres"
    if ($pg) {
        Write-Host "[OK] PostgreSQL container: Running (:5433)" -ForegroundColor Green
    } else {
        Write-Host "[!]  PostgreSQL container: Not running" -ForegroundColor Red
    }

    $be = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
    if ($be) {
        Write-Host "[OK] Backend (Uvicorn):     Running (:7860)" -ForegroundColor Green
    } else {
        Write-Host "[!]  Backend (Uvicorn):     Not running" -ForegroundColor Red
    }

    $fe = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    if ($fe) {
        Write-Host "[OK] Frontend (Vite):       Running (:5173)" -ForegroundColor Green
    } else {
        Write-Host "[!]  Frontend (Vite):       Not running" -ForegroundColor Red
    }
}

switch ($Action) {
    "start"   { Start-Dev }
    "stop"    { Stop-Dev }
    "restart" { Stop-Dev; Start-Sleep -Seconds 1; Start-Dev }
    "status"  { Show-Status }
}
