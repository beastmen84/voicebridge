param(
    [switch]$RuntimeOnly,
    [switch]$ModelsOnly,
    [switch]$IncludeModels
)

$ErrorActionPreference = "Stop"

if ($RuntimeOnly -and ($ModelsOnly -or $IncludeModels)) {
    throw "Choose either -RuntimeOnly or a model-copy option, not both."
}

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
    Copy-Item -Path (Join-Path $PSScriptRoot "local_tts_worker.py") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "voice_modeling_worker.py") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "video_anomaly_worker.py") -Destination $bundleDir -Force
    $workerPackageDir = Join-Path $bundleDir "voicebridge"
    New-Item -ItemType Directory -Path $workerPackageDir -Force | Out-Null
    Copy-Item -Path (Join-Path $PSScriptRoot "voicebridge\__init__.py") -Destination $workerPackageDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "voicebridge\video_anomalies.py") -Destination $workerPackageDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "requirements-stt.txt") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "requirements-local-tts.txt") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "README.md") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "CHANGELOG.md") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "CONTRIBUTING.md") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "SECURITY.md") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "Manual.it.html") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "Manual.en.html") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "VERSION") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "LICENSE") -Destination $bundleDir -Force
    Copy-Item -Path (Join-Path $PSScriptRoot "THIRD_PARTY_LICENSES") -Destination $bundleDir -Force

    $mlVenv = Join-Path $PSScriptRoot ".venv-ml"
    if (Test-Path $mlVenv) {
        $runtimeVenv = $mlVenv
        $runtimeName = "python-ml"
    }
    else {
        throw ".venv-ml not found. Offline ML runtime cannot be bundled."
    }

    $venvConfig = Join-Path $runtimeVenv "pyvenv.cfg"
    $pythonHome = ((Get-Content $venvConfig | Where-Object { $_ -match "^home\s*=" } | Select-Object -First 1) -replace "^home\s*=\s*", "").Trim()
    if (!(Test-Path (Join-Path $pythonHome "python.exe"))) {
        throw "Could not find the base Python runtime for ${runtimeVenv}: $pythonHome"
    }

    $portablePython = Join-Path $bundleDir $runtimeName
    Invoke-RobocopyChecked -Source $pythonHome -Destination $portablePython -ExtraArgs @("/XD", "__pycache__", "/XF", "*.pyc")
    Invoke-RobocopyChecked -Source (Join-Path $runtimeVenv "Lib\site-packages") -Destination (Join-Path $portablePython "Lib\site-packages") -ExtraArgs @("/XD", "__pycache__", "/XF", "*.pyc")

    $sttShare = Join-Path $runtimeVenv "share"
    if (Test-Path $sttShare) {
        Invoke-RobocopyChecked -Source $sttShare -Destination (Join-Path $portablePython "share") -ExtraArgs @("/XD", "__pycache__", "/XF", "*.pyc")
    }
}

if ($ModelsOnly -or $IncludeModels) {
    $modelsDir = Join-Path $PSScriptRoot "models"
    if (!(Test-Path $modelsDir)) {
        throw "Models folder not found. Run prepare_stt_models.py first: $modelsDir"
    }
    Invoke-RobocopyChecked -Source $modelsDir -Destination (Join-Path $bundleDir "models")
}

if ($RuntimeOnly -or (-not $ModelsOnly -and -not $IncludeModels)) {
    $bundledModelsDir = Join-Path $bundleDir "models"
    if (Test-Path $bundledModelsDir) {
        $resolvedBundle = (Resolve-Path $bundleDir).Path
        $resolvedModels = (Resolve-Path $bundledModelsDir).Path
        if (-not $resolvedModels.StartsWith($resolvedBundle, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to delete models outside bundle folder: $resolvedModels"
        }
        Remove-Item -LiteralPath $resolvedModels -Recurse -Force
    }
}

Write-Host "Offline ML bundle synchronized: $bundleDir"
