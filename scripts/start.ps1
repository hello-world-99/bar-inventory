# Starts the app on this computer (called by start.bat). On the first run creates .env with random secrets.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function New-Secret([int]$bytes) {
  $b = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return ([Convert]::ToBase64String($b) -replace '[+/=]', '')
}

function Wait-Docker {
  cmd /c "docker info >nul 2>&1"
  if ($LASTEXITCODE -eq 0) { return }
  $exe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
  if (-not (Test-Path $exe)) { throw "Docker Desktop is not installed. Install it from https://www.docker.com/products/docker-desktop/ and run start.bat again." }
  Write-Host "Starting Docker Desktop..."
  Start-Process $exe
  for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    cmd /c "docker info >nul 2>&1"
    if ($LASTEXITCODE -eq 0) { return }
  }
  throw "Docker Desktop did not start within 3 minutes. Open it manually, wait until it says 'Engine running', and run start.bat again."
}

if (-not (Test-Path ".env")) {
  $envText = (Get-Content ".env.example" -Raw) `
    -replace '(?m)^POSTGRES_PASSWORD=.*$', "POSTGRES_PASSWORD=$(New-Secret 24)" `
    -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$(New-Secret 48)" `
    -replace '(?m)^INITIAL_ADMIN_PASSWORD=.*$', "INITIAL_ADMIN_PASSWORD=$(New-Secret 12)"
  [System.IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), ($envText -replace "`r`n", "`n"))
}

$port = "8080"
$m = Select-String -Path ".env" -Pattern '^HTTP_PORT=(\d+)' | Select-Object -First 1
if ($m) { $port = $m.Matches[0].Groups[1].Value }
if ($env:HTTP_PORT) { $port = $env:HTTP_PORT }  # compose prefers the environment over .env: do the same
$url = "http://localhost:$port"

Wait-Docker
Write-Host "Starting the app (the first start builds it and takes a few minutes)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw "docker compose failed, see the messages above." }

Write-Host "Waiting for $url ..."
$ok = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "$url/api/health"
    if ($r.StatusCode -eq 200) { $ok = $true; break }
  } catch { }
  Start-Sleep -Seconds 2
}
if (-not $ok) { throw "The app did not answer at $url. See: docker compose logs backend" }

Write-Host ""
Write-Host "Bar Inventory is running: $url"
# Shown on every start while the first password is still in .env (also after an interrupted first run).
$a = Select-String -Path ".env" -Pattern '^INITIAL_ADMIN_PASSWORD=(\S+)' | Select-Object -First 1
if ($a) {
  Write-Host ""
  Write-Host "First sign-in: user 'admin', password: $($a.Matches[0].Groups[1].Value)" -ForegroundColor Yellow
  Write-Host "After signing in, change it ('Change password' at the bottom of the left menu),"
  Write-Host "then open .env in Notepad and delete the value after INITIAL_ADMIN_PASSWORD= ."
  Write-Host "This reminder disappears once that value is deleted."
}
if (-not $env:BAR_NO_BROWSER) { Start-Process $url }
