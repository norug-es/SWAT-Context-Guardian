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
$Params = @( (Join-Path $Root 'control_center\server.py'), '--port', "$Port" )
if ($Demo) { $Params += '--demo' }
if ($WithToasts) { $Params += '--native-toasts' }
if ($WithAppServer) { $Params += @('--appserver-url', 'ws://127.0.0.1:4500') }
if ($TokenFile) { $Params += @('--appserver-token-file', $TokenFile) }
if ($CodexCommand) { $Params += @('--codex-command', $CodexCommand) }
Write-Host "Panel local: http://127.0.0.1:$Port"
& $Python @Params
