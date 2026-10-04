[CmdletBinding()]
param(
    [string]$VpcdHost = '127.0.0.1',
    [ValidateRange(1,65535)][int]$VpcdPort = 35963,
    [ValidateRange(0,86400)][int]$RunSeconds = 0
)
& (Join-Path $PSScriptRoot 'decard_unified_bridge.ps1') -Mode Contact -VpcdHost $VpcdHost -VpcdPort $VpcdPort -RunSeconds $RunSeconds
exit $LASTEXITCODE
