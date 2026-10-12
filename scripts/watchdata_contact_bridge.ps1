[CmdletBinding()]
param([string]$Device,[string]$VpcdHost='127.0.0.1',[ValidateRange(1,65535)][int]$VpcdPort=35963,[ValidateRange(0,86400)][int]$RunSeconds=0,[ValidateRange(1,300)][int]$ApduTimeout=30,[switch]$ListDevices)
& (Join-Path $PSScriptRoot 'watchdata_unified_bridge.ps1') -Mode contact -Device $Device -VpcdHost $VpcdHost -VpcdPort $VpcdPort -RunSeconds $RunSeconds -ApduTimeout $ApduTimeout -ListDevices:$ListDevices
exit $LASTEXITCODE
