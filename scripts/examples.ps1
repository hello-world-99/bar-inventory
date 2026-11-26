# Loads the example data into a fresh install (called by examples.bat). Runs inside a one-off backend container,
# so nothing besides Docker is needed on this computer.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $env:BAR_ADMIN_PASSWORD) {
  $a = Select-String -Path ".env" -Pattern '^INITIAL_ADMIN_PASSWORD=(\S+)' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($a) { $env:BAR_ADMIN_PASSWORD = $a.Matches[0].Groups[1].Value }
}
if (-not $env:BAR_ADMIN_PASSWORD) {
  $s = Read-Host "Password of the user 'admin'" -AsSecureString
  $env:BAR_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

$examples = Join-Path (Get-Location) "examples"
docker compose run --rm --no-deps -e BAR_ADMIN_PASSWORD -v "${examples}:/examples:ro" backend python /examples/load_examples.py http://web
if ($LASTEXITCODE -ne 0) { throw "Loading the examples failed, see the messages above." }
Write-Host ""
Write-Host "Example data loaded. Refresh the page in the browser."
