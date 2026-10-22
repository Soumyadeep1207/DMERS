$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) { throw 'Docker Desktop is required. Install it, start Docker Desktop, then rerun this script.' }

$envFile = Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    throw 'Project .env is missing. Copy .env.example to .env and set private POSTGRES_PASSWORD and SECRET_KEY values.'
}
$envText = Get-Content -LiteralPath $envFile -Raw
if ($envText -match '(?m)^POSTGRES_PASSWORD=\s*$|(?m)^POSTGRES_PASSWORD=.*(replace-with|your-password|changeme)' -or
    $envText -match '(?m)^SECRET_KEY=\s*$|(?m)^SECRET_KEY=.*(replace-with|change-this|your-secret)') {
    throw 'Replace the example POSTGRES_PASSWORD and SECRET_KEY values in .env before launching the stack.'
}

& docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) {
    $desktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (Test-Path -LiteralPath $desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 2
        & docker info --format '{{.ServerVersion}}' *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    }
    if (-not $ready) { throw 'Docker Desktop was launched, but its engine did not become ready. Open Docker Desktop and check its status, then rerun this script.' }
}

Push-Location $root
try {
    Write-Host 'Starting PostgreSQL...' -ForegroundColor Cyan
    & docker compose up -d postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not start. Inspect docker compose logs postgres.' }

    $postgresReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker compose exec -T postgres pg_isready -U dmers -d dmers *> $null
        if ($LASTEXITCODE -eq 0) { $postgresReady = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $postgresReady) { & docker compose logs --tail 80 postgres; throw 'PostgreSQL did not become ready.' }

    $courseExists = & docker compose exec -T postgres psql -U dmers -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='dmers_course'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not check for the Review II database.' }
    if (($courseExists -join '').Trim() -ne '1') {
        & docker compose exec -T postgres psql -U dmers -d postgres -c 'CREATE DATABASE dmers_course'
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Review II database dmers_course.' }
    }

    $courseReady = & docker compose exec -T postgres psql -U dmers -d dmers_course -tAc "SELECT CASE WHEN to_regclass('public.resource_allocations') IS NOT NULL AND to_regclass('public.v_zone_situation') IS NOT NULL THEN 'ready' ELSE 'missing' END"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Review II database schema.' }
    if (($courseReady -join '').Trim() -ne 'ready') {
        Write-Host 'Building the isolated Review II schema and running its demonstration scripts...' -ForegroundColor Cyan
        $demoLog = Join-Path $root 'tmp\review2_run.log'
        New-Item -ItemType Directory -Path (Split-Path $demoLog) -Force | Out-Null
        $demoOutput = & docker compose exec -T postgres psql -U dmers -d dmers_course -v ON_ERROR_STOP=1 -f /review2/run_all.sql 2>&1
        $demoExit = $LASTEXITCODE
        $demoOutput | Set-Content -LiteralPath $demoLog
        if ($demoExit -ne 0) { $demoOutput | Select-Object -Last 80; throw 'The Review II SQL scripts failed. See tmp\review2_run.log.' }
        Write-Host 'Review II database initialized. Expected constraint-test errors are recorded in tmp\review2_run.log.' -ForegroundColor Green
    } else {
        Write-Host 'Review II database already has its schema; preserving its data.' -ForegroundColor Green
    }

    Write-Host 'Building and starting Flask and the web frontend...' -ForegroundColor Cyan
    & docker compose up --build -d backend frontend
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed. Inspect docker compose logs.' }

    $health = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:5175/health' -TimeoutSec 3
            if ($health.status -eq 'ok' -and $health.database.connected -and $health.review2_database.connected) { break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $health -or $health.status -ne 'ok' -or -not $health.database.connected -or -not $health.review2_database.connected) {
        & docker compose ps
        & docker compose logs --tail 80 backend postgres
        throw 'The stack started, but its HTTP health check did not confirm a connected database.'
    }

    & docker compose ps
    Write-Host "Health check passed: $($health.database.engine) and Review II database connected." -ForegroundColor Green
    Write-Host 'Frontend: http://127.0.0.1:5175' -ForegroundColor Green
    Write-Host 'Backend health: http://127.0.0.1:5003/health' -ForegroundColor Green
    Write-Host 'Review II database: 127.0.0.1:5433 / dmers_course / user dmers' -ForegroundColor Green
} finally {
    Pop-Location
}
<<<<<<< HEAD
=======
& "$root\backend\.venv\Scripts\python.exe" -m pip install -r "$root\backend\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Some optional AI training packages could not be downloaded. Starting DMERS with its built-in advisory fallback.' -ForegroundColor Yellow
}
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; & '.\.venv\Scripts\python.exe' -m flask --app run run --host 127.0.0.1 --port 5000"
Set-Location "$root\frontend"
if (-not (Test-Path 'node_modules')) { npm install }
npm run dev
>>>>>>> origin/feature/ai-decision-support
