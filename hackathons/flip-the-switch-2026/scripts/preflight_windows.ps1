# InnerOS Incident Room | read-only Windows preflight, 2026-11-06
# Does not install packages, edit network settings, or read secret values.
[CmdletBinding()]
param(
    [string]$SwitchUrl = 'http://127.0.0.1:8000',
    [switch]$IncludeHA
)
$ErrorActionPreference = 'Continue'
Write-Host 'INNEROS / SWITCH: DIAGNOSTICO INICIAL (SOLO LECTURA)' -ForegroundColor Cyan
Write-Host ('Hora local: {0}' -f (Get-Date))
Write-Host ('Carpeta: {0}' -f $PSScriptRoot)
foreach ($name in @('py','python','codex','agy','docker')) {
    $found = Get-Command $name -ErrorAction SilentlyContinue
    if ($null -ne $found) { Write-Host ("{0}: OK" -f $name) -ForegroundColor Green }
    else { Write-Host ("{0}: NO EN PATH" -f $name) -ForegroundColor Yellow }
}
$server = $SwitchUrl.TrimEnd('/')
if ($server -notmatch '^http://(localhost|127[.]0[.]0[.]1)(:[0-9]{2,5})?$') {
    Write-Host 'URL de Switch no es localhost. Prohibido consultar destinos arbitrarios.' -ForegroundColor Red
} else {
    try {
        $status = Invoke-WebRequest -Uri ($server + '/health') -UseBasicParsing -TimeoutSec 4
        Write-Host ("Switch API /health: HTTP {0}" -f $status.StatusCode) -ForegroundColor Green
    } catch {
        Write-Host 'Switch API /health: no responde en esta direccion. No implica que Switch este apagado; verifica direccion del servidor en Console.' -ForegroundColor Yellow
    }
}
if (Get-Command codex -ErrorAction SilentlyContinue) {
    Write-Host 'Estado de login Codex (no se imprime token):'
    & codex login status 2>&1 | Select-Object -First 3
}
if ($IncludeHA) {
    if (-not $env:HA_URL -or -not $env:HA_TOKEN) {
        Write-Host 'Home Assistant: HA_URL o HA_TOKEN no configurados en esta sesion.' -ForegroundColor Yellow
    } elseif ($env:HA_URL -notmatch '^https?://(localhost|127[.]0[.]0[.]1|192[.]168[.][0-9]{1,3}[.][0-9]{1,3}|10[.][0-9]{1,3}[.][0-9]{1,3}|172[.](1[6-9]|2[0-9]|3[01])[.][0-9]{1,3}[.][0-9]{1,3})(:[0-9]{1,5})?/?$') {
        Write-Host 'HA_URL no es direccion privada reconocida. No se envia token.' -ForegroundColor Yellow
    } else {
        try {
            $h = @{Authorization = 'Bearer ' + $env:HA_TOKEN}
            $response = Invoke-RestMethod -Method Get -Uri ($env:HA_URL.TrimEnd('/') + '/api/') -Headers $h -TimeoutSec 5
            if ($response.message -eq 'API running.') { Write-Host 'Home Assistant REST: CONECTADO (sin modificar dispositivos)' -ForegroundColor Green }
            else { Write-Host 'Home Assistant: respuesta inesperada' -ForegroundColor Yellow }
        } catch { Write-Host 'Home Assistant REST: no disponible con estas credenciales.' -ForegroundColor Yellow }
    }
}
Write-Host ''
Write-Host 'PRUEBA SWITCH: en #inneros-live-operations escribe !agents-status como mensaje independiente.' -ForegroundColor Cyan
Write-Host 'Si sale live, verifica hilo bajo mensaje original; luego usa !agents-greet.'
Write-Host 'Si agente no responde en privado, inspeccionar logs de controlador; NO reinstalar ni borrar sesiones.'
Write-Host 'Ninguna configuracion o dispositivo fue modificado.'