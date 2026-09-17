$ErrorActionPreference = 'Stop'
$runtimeDir = Join-Path $PSScriptRoot '.runtime'

foreach ($serviceName in @('frontend', 'backend')) {
    $statePath = Join-Path $runtimeDir ($serviceName + '.json')
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Host "$serviceName is not managed by these scripts."
        continue
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $identities = @($state.Processes)
    # Children first; verify PID, creation time, executable and command line before stopping.
    [array]::Reverse($identities)
    foreach ($saved in $identities) {
        $actual = Get-CimInstance Win32_Process -Filter "ProcessId = $($saved.ProcessId)" -ErrorAction SilentlyContinue
        if ($null -eq $actual) { continue }
        if (('utc:' + $actual.CreationDate.ToUniversalTime().ToString('o')) -eq $saved.Created -and
            $actual.ExecutablePath -eq $saved.Executable -and $actual.CommandLine -eq $saved.CommandLine) {
            Stop-Process -Id $saved.ProcessId -ErrorAction SilentlyContinue
            Write-Host "Stopped $serviceName process $($saved.ProcessId)."
        } else {
            Write-Host "Skipped PID $($saved.ProcessId): its identity no longer matches."
        }
    }
    Remove-Item -LiteralPath $statePath
}
