# SWAT Context Guardian - primer arranque seguro (no sobrescribe configuracion)
param(
    [switch]$WithAppServer,
    [switch]$WithToasts,
    [switch]$Demo,
    [int]$Port = 8765,
    [string]$TokenFile = "",
    [string]$CodexCommand = ""
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'

function Stop-ControlCenterOnPort {
    param([Parameter(Mandatory = $true)][int]$ListenPort)

    $pattern = "LISTENING\s+([1-9]\d*)\s*$"
    $listeners = @(netstat -ano -p tcp 2>$null |
        Select-String ":$ListenPort\s+.*LISTENING\s+[1-9]\d*\s*$" |
        ForEach-Object {
            $match = [regex]::Match($_.Line, $pattern)
            if ($match.Success) { [int]$match.Groups[1].Value }
        } | Select-Object -Unique)
    if (-not $listeners) { return }

    foreach ($processId in $listeners) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        $commandLine = [string]$processInfo.CommandLine
        $isGuardian = $commandLine -match 'control_center[\\/](run|server)\.py' -or
            $commandLine -match '(^|\s)-m\s+control_center\.run(\s|$)'
        if (-not $isGuardian) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ListenPort/api/health" -TimeoutSec 2 -ErrorAction Stop
                $isGuardian = $health.ok -eq $true -and $health.read_only -eq $true
            } catch {
                $isGuardian = $false
            }
        }
        if (-not $isGuardian) {
            throw "El puerto $ListenPort está ocupado por otro proceso (PID $processId). No se detendrá automáticamente."
        }

        Write-Host "Reiniciando Control Center existente (PID $processId, puerto $ListenPort)..."
        Stop-Process -Id $processId -Force
    }

    $deadline = (Get-Date).AddSeconds(5)
    do {
        Start-Sleep -Milliseconds 200
        $stillListening = @(netstat -ano -p tcp 2>$null |
            Select-String ":$ListenPort\s+.*LISTENING\s+[1-9]\d*\s*$")
    } while ($stillListening -and (Get-Date) -lt $deadline)
    if ($stillListening) { throw "El proceso anterior no liberó el puerto $ListenPort a tiempo." }
}

Stop-ControlCenterOnPort -ListenPort $Port

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host 'Creando entorno virtual local de Python...'
    python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear .venv' }
}
& $Python -c 'import fastapi,uvicorn,websockets' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -r (Join-Path $Root 'control_center\requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Fallo instalando dependencias' }
}
if ($WithToasts) {
    & $Python -c 'import winotify' 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $Python -m pip install winotify==1.1.0
        if ($LASTEXITCODE -ne 0) { throw 'Fallo instalando winotify' }
    }
}
$Params = @( '--port', "$Port" )
if ($Demo) { $Params += '--demo' }
if ($WithToasts) { $Params += '--native-toasts' }
if ($WithAppServer) { $Params += @('--appserver-url', 'ws://127.0.0.1:4500') }
if ($TokenFile) { $Params += @('--appserver-token-file', $TokenFile) }
if ($CodexCommand) { $Params += @('--codex-command', $CodexCommand) }
Write-Host "Panel local: http://127.0.0.1:$Port"
Push-Location $Root
try {
    & $Python -m control_center.run @Params
} finally {
    Pop-Location
}
