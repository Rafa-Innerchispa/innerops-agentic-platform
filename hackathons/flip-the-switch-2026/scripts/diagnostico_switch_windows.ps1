# Read-only Switch Console diagnostics for Windows. Do not run as admin.
[CmdletBinding()]
param()
$ErrorActionPreference = "Continue"
Write-Host "Switch Console diagnostic - read only"
Write-Host ("UTC: {0:u}" -f (Get-Date).ToUniversalTime())
foreach ($n in @("Switch Console","switch-console","codex","docker","com.docker.backend","mattermost","node","python")) {
  $p = @(Get-Process -Name $n -ErrorAction SilentlyContinue)
  Write-Host ("Process {0}: {1}" -f $n,$p.Count)
}
$watch = Join-Path $env:APPDATA "switchdash\agent-controller"
if (Test-Path -LiteralPath $watch) {
  $health = @(Get-ChildItem -LiteralPath $watch -Filter health.json -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match '[\\/]watchers[\\/]' })
  Write-Host ("Agent watcher health records: {0}" -f $health.Count)
} else {
  Write-Host "Agent controller watcher folder not found in current profile."
}
try {
  $listen = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in @(8000,50007,62226,8765) } | Select-Object LocalAddress,LocalPort,State)
  if ($listen.Count) { $listen | Format-Table -AutoSize }
} catch { Write-Host "Socket enumeration unavailable." }
if (Get-Command codex -ErrorAction SilentlyContinue) {
  Write-Host "Codex CLI authentication:"
  & codex login status 2>&1 | Select-Object -First 5
} else {
  Write-Host "Codex not on PowerShell PATH; Switch may use a different installation."
}
if (Get-Command docker -ErrorAction SilentlyContinue) {
  Write-Host "Docker containers (names/status only):"
  & docker ps --format '{{.Names}} :: {{.Status}}' 2>&1 | Select-Object -First 20
}
Write-Host "Manual: test Switch direct chat first; compare with Mattermost reply."
Write-Host "Look for kill EPERM or Bridge crashed in Switch logs; do not delete anything."
