param(
    [Parameter(Mandatory=$true)][string]$AmdIP,
    [Parameter(Mandatory=$true)][string]$IntelIP
)
# READ-ONLY. Never modifies route metrics, gateways, firewalls, switches or UniFi.
$ErrorActionPreference = 'Continue'
Write-Host 'INNEROS LAN CHECK (read-only)' -ForegroundColor Cyan
Write-Host 'Two network adapters are allowed: cellular Wi-Fi internet and home Wi-Fi LAN.'
Write-Host 'No IP addresses or credentials will be sent anywhere by this script.'
Write-Host 'Network interfaces:'
Get-NetIPConfiguration | Where-Object {$_.IPv4Address} |
    Select-Object InterfaceAlias,InterfaceIndex,IPv4Address,IPv4DefaultGateway |
    Format-Table -AutoSize
foreach ($target in @(@{Name='AMD 1.5';IP=$AmdIP}, @{Name='Intel 1.4';IP=$IntelIP})) {
    Write-Host ("`nHost {0} ({1})" -f $target.Name, $target.IP) -ForegroundColor Yellow
    try {
        $route = Find-NetRoute -RemoteIPAddress $target.IP -ErrorAction Stop |
            Select-Object -First 1 InterfaceAlias,InterfaceIndex,NextHop,RouteMetric
        $route | Format-List
    } catch { Write-Host 'Could not determine route automatically.' }
    foreach ($port in @(22,8000,8001)) {
        $test = Test-NetConnection -ComputerName $target.IP -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
        Write-Host ("TCP port {0}: {1}" -f $port, ($(if ($test) {'reachable'} else {'unreachable / blocked'})))
    }
}
Write-Host "`nDiagnostic completed. No network settings were changed." -ForegroundColor Green