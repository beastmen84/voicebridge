param(
    [switch]$RuntimeOnly,
    [switch]$ModelsOnly
)

$ErrorActionPreference = "Stop"

function Invoke-RobocopyChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    if (!(Test-Path $Source)) {
        throw "Source not found: $Source"
    }

    $args = @($Source, $Destination, "/MIR") + $ExtraArgs
    & robocopy @args | Out-Host
    if ($LASTEXITCODE -ge 8) {
        throw "Robocopy failed copying '$Source' to '$Destination'. Exit code: $LASTEXITCODE"
    }
    $global:LASTEXITCODE = 0
}

$bundleDir = Join-Path $PSScriptRoot "dist\VoiceBridge"
if (!(Test-Path $bundleDir)) {
    throw "Bundle folder not found. Run .\build_app.ps1 first: $bundleDir"
}

if (-not $ModelsOnly) {
    Copy-Item -Path (Join-Path $PSScriptRoot "stt_worker.py") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "requirements-stt.txt") -Destination $bundleDir -Force

    $sttVenv = Join-Path $PSScriptRoot ".venv-stt"
    if (!(Test-Path $sttVenv)) {
        throw ".venv-stt not found. STT runtime cannot be bundled."
    }

    $venvConfig = Join-Path $sttVenv "pyvenv.cfg"
    $pythonHome = ((Get-Content $venvConfig | Where-Object { $_ -match "^home\s*=" } | Select-Object -First 1) -replace "^home\s*=\s*", "").Trim()
    if (!(Test-Path (Join-Path $pythonHome "python.exe"))) {
        throw "Could not find the base Python runtime for .venv-stt: $pythonHome"
    }

    $portablePython = Join-Path $bundleDir "python-stt"
    Invoke-RobocopyChecked -Source $pythonHome -Destination $portablePython -ExtraArgs @("/XD", "__pycache__", "/XF", "*.pyc")
    Invoke-RobocopyChecked -Source (Join-Path $sttVenv "Lib\site-packages") -Destination (Join-Path $portablePython "Lib\site-packages") -ExtraArgs @("/XD", "__pycache__", "/XF", "*.pyc")

    $sttShare = Join-Path $sttVenv "share"
    if (Test-Path $sttShare) {
        Invoke-RobocopyChecked -Source $sttShare -Destination (Join-Path $portablePython "share") -ExtraArgs @("/XD", "__pycache__", "/XF", "*.pyc")
    }
}

if (-not $RuntimeOnly) {
    $modelsDir = Join-Path $PSScriptRoot "models"
    if (!(Test-Path $modelsDir)) {
        throw "Models folder not found. Run prepare_stt_models.py first: $modelsDir"
    }
    Invoke-RobocopyChecked -Source $modelsDir -Destination (Join-Path $bundleDir "models")
}

Write-Host "STT bundle synchronized: $bundleDir"
