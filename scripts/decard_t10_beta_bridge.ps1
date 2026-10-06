# DeCard T10 Beta (PID A133) Dual-Interface PC/SC Bridge (Contact Slot 0x0C + RF Pad)
[CmdletBinding()]
param(
    [string]$VpcdHost = '127.0.0.1',
    [ValidateRange(1,65535)][int]$VpcdPort = 35963,
    [ValidateSet('ContactFirst','RfFirst')][string]$Priority = 'ContactFirst',
    [ValidateSet('Auto','Contact','Rf')][string]$Mode = 'Auto',
    [ValidateRange(0,86400)][int]$RunSeconds = 0,
    [ValidateRange(0,65535)][int]$DirectPort = 0
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    if ([Environment]::Is64BitProcess) {
        $x86 = Join-Path $env:SystemRoot 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
        if (!(Test-Path -LiteralPath $x86)) { throw '32-bit Windows PowerShell is required for dcrf32.dll' }
        & $x86 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -VpcdHost $VpcdHost -VpcdPort $VpcdPort -Priority $Priority -Mode $Mode -RunSeconds $RunSeconds -DirectPort $DirectPort
        exit $LASTEXITCODE
    }
    $driverDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'drivers'
    Add-Type -Path (Join-Path $PSScriptRoot 'DecardT10BetaBridge.cs')
    [ChinaHid.T10Beta.Runner]::Run($driverDir, $VpcdHost, $VpcdPort, $Mode, ($Priority -eq 'ContactFirst'), $RunSeconds, $DirectPort)
    exit 0
} catch {
    Write-Error -ErrorAction Continue $_
    exit 1
}
