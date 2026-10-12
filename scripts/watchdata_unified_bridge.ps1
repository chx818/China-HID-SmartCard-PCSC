[CmdletBinding()]
param(
    [ValidateSet('auto','contact','rf')][string]$Mode='auto',
    [ValidateSet('ContactFirst','RfFirst')][string]$Priority='ContactFirst',
    [string]$Device,
    [string]$VpcdHost='127.0.0.1',
    [ValidateRange(1,65535)][int]$VpcdPort=35963,
    [ValidateRange(0,86400)][int]$RunSeconds=0,
    [ValidateRange(1,300)][int]$ApduTimeout=30,
    [switch]$ListDevices
)
$ErrorActionPreference='Stop'
try {
    $python=Get-Command python.exe -ErrorAction Stop
    $callArgs=@((Join-Path $PSScriptRoot 'watchdata_usb_bridge.py'),'--mode',$Mode,'--priority',$Priority,'--host',$VpcdHost,'--vpcd-port',"$VpcdPort",'--run-seconds',"$RunSeconds",'--apdu-timeout',"$ApduTimeout")
    if($Device){$callArgs+=@('--device',$Device)}
    if($ListDevices){$callArgs+='--list-devices'}
    & $python.Source @callArgs
    exit $LASTEXITCODE
} catch { Write-Error -ErrorAction Continue $_; exit 1 }
