# W2160 / CRW-Xs serial entry. Serial enumeration and selection happen before opening a device.
[CmdletBinding()]
param(
    [string]$Port,
    [ValidateSet('auto','E','N')][string]$Parity='auto',
    [ValidateSet(9600,19200,38400,57600,115200)][int]$BaudRate=9600,
    [ValidateRange(1,65535)][int]$VpcdPort=35963,
    [ValidateRange(0,86400)][int]$RunSeconds=0,
    [switch]$ListPorts
)
$ErrorActionPreference='Stop'
try {
    $root=Split-Path -Parent $PSScriptRoot
    $script=Join-Path $root 'W2160（CRW-Xs）\serial_bridge.py'
    $python=Get-Command python.exe -ErrorAction Stop
    $argsList=@($script,'--parity',$Parity,'--baudrate',"$BaudRate",'--vpcd-port',"$VpcdPort",'--run-seconds',"$RunSeconds")
    if($Port){$argsList+=@('--port',$Port)}
    if($ListPorts){$argsList+='--list-ports'}
    & $python.Source @argsList
    exit $LASTEXITCODE
} catch {
    Write-Error -ErrorAction Continue $_
    exit 1
}
