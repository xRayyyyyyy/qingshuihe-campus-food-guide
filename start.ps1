$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'

if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Missing backend virtual environment. See the local deployment guide.' }
if (-not (Test-Path -LiteralPath $vitePath)) { throw 'Missing frontend dependencies. Run npm install in frontend.' }
$nodePath = (Get-Command node.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Get-Identity($processId) {
    $item = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    [pscustomobject]@{
        ProcessId = [int]$item.ProcessId
        Created = 'utc:' + $item.CreationDate.ToUniversalTime().ToString('o')
        Executable = $item.ExecutablePath
        CommandLine = $item.CommandLine
    }
}

function Test-Identity($saved) {
    $actual = Get-Identity $saved.ProcessId
    return ($null -ne $actual -and $actual.Created -eq $saved.Created -and
        $actual.Executable -eq $saved.Executable -and $actual.CommandLine -eq $saved.CommandLine)
}

function Get-ManagedProcesses($statePath) {
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        foreach ($saved in @($state.Processes)) {
            if (Test-Identity $saved) { $saved }
        }
    }
}

function Get-Listeners($port) {
    @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

$services = @(
    @{ Name = 'backend'; Port = 8000; File = $pythonPath; Args = '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'; Directory = (Join-Path $projectRoot 'backend') },
    @{ Name = 'frontend'; Port = 5173; File = $nodePath; Args = ('"' + $vitePath + '" --host 127.0.0.1 --port 5173 --strictPort'); Directory = (Join-Path $projectRoot 'frontend') }
)

# Check both ports before creating any new process. Never terminate a port owner.
foreach ($service in $services) {
    $statePath = Join-Path $runtimeDir ($service.Name + '.json')
    $managed = @(Get-ManagedProcesses $statePath)
    foreach ($listener in @(Get-Listeners $service.Port)) {
        if ($listener.OwningProcess -notin @($managed.ProcessId)) {
            throw "Port $($service.Port) is occupied by another process (PID $($listener.OwningProcess))."
        }
    }
    $service.StatePath = $statePath
    $service.Managed = $managed
}

foreach ($service in $services) {
    if ($service.Managed.Count -gt 0) {
        if (@(Get-Listeners $service.Port).Count -eq 0) {
            throw "$($service.Name) exists but is not listening. Check .runtime logs, then run stop.cmd before retrying."
        }
        Write-Host "$($service.Name) is already running."
        continue
    }

    $process = Start-Process -FilePath $service.File -ArgumentList $service.Args -WorkingDirectory $service.Directory `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir ($service.Name + '.stdout.log')) `
        -RedirectStandardError (Join-Path $runtimeDir ($service.Name + '.stderr.log'))
    $rootIdentity = Get-Identity $process.Id
    if ($null -eq $rootIdentity) { throw "$($service.Name) exited immediately. Check .runtime logs." }
    $identities = @($rootIdentity)
    $ready = $false

    # Record descendants too: Windows virtual-environment Python may use a child interpreter.
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        foreach ($parent in @($identities)) {
            if (-not (Test-Identity $parent)) { continue }
            foreach ($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($parent.ProcessId)")) {
                if ($child.ProcessId -notin @($identities.ProcessId)) {
                    $childIdentity = Get-Identity $child.ProcessId
                    if ($null -ne $childIdentity) { $identities += $childIdentity }
                }
            }
        }
        [pscustomobject]@{ Service = $service.Name; Processes = $identities } |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $service.StatePath -Encoding UTF8
        $alive = @($identities | Where-Object { Test-Identity $_ })
        $listeners = @(Get-Listeners $service.Port)
        if (@($listeners | Where-Object { $_.OwningProcess -in @($alive.ProcessId) }).Count -gt 0) {
            $ready = $true
            break
        }
        if ($alive.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    }
    if (-not $ready) { throw "$($service.Name) did not start. Check .runtime logs; run stop.cmd before retrying." }
    Write-Host "$($service.Name) started."
}

Write-Host 'App: http://127.0.0.1:5173'
Write-Host 'API docs: http://127.0.0.1:8000/docs'
