param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$bundleDir = Join-Path $PSScriptRoot "dist\VoiceBridge"
$preserveRoot = Join-Path $PSScriptRoot "dist\.preserve-stt-$PID"
$preserveNames = @("python-ml", ".stt-bin", "voice_profiles", "modeling_exports", "voice_models")

if ($Clean) {
    $buildDir = Join-Path $PSScriptRoot "build"
    foreach ($target in @($buildDir, $bundleDir)) {
        if (Test-Path $target) {
            $resolvedRoot = (Resolve-Path $PSScriptRoot).Path
            $resolvedTarget = (Resolve-Path $target).Path
            if (-not $resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to delete outside project folder: $resolvedTarget"
            }
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
        }
    }
}

if (-not $Clean -and (Test-Path $bundleDir)) {
    New-Item -ItemType Directory -Path $preserveRoot -Force | Out-Null
    foreach ($name in $preserveNames) {
        $source = Join-Path $bundleDir $name
        if (Test-Path $source) {
            Move-Item -LiteralPath $source -Destination (Join-Path $preserveRoot $name) -Force
        }
    }
}

try {
    & (Join-Path $PSScriptRoot ".venv\Scripts\pyinstaller.exe") `
        --noconfirm `
        --onedir `
        --windowed `
        --icon (Join-Path $PSScriptRoot "images\file_to_mp3.ico") `
        --add-data "$PSScriptRoot\images;images" `
        --hidden-import sounddevice `
        --collect-all _sounddevice_data `
        --name VoiceBridge `
        (Join-Path $PSScriptRoot "voicebridge_qt.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed. Exit code: $LASTEXITCODE"
    }
}
finally {
    if (Test-Path $preserveRoot) {
        New-Item -ItemType Directory -Path $bundleDir -Force | Out-Null
        foreach ($name in $preserveNames) {
            $preserved = Join-Path $preserveRoot $name
            if (Test-Path $preserved) {
                $destination = Join-Path $bundleDir $name
                if (Test-Path $destination) {
                    Remove-Item -LiteralPath $destination -Recurse -Force
                }
                Move-Item -LiteralPath $preserved -Destination $destination -Force
            }
        }
        Remove-Item -LiteralPath $preserveRoot -Recurse -Force
    }
}

if (!(Test-Path $bundleDir)) {
    throw "Expected bundle folder not found: $bundleDir"
}

$bundledModelsDir = Join-Path $bundleDir "models"
if (Test-Path $bundledModelsDir) {
    $resolvedBundle = (Resolve-Path $bundleDir).Path
    $resolvedModels = (Resolve-Path $bundledModelsDir).Path
    if (-not $resolvedModels.StartsWith($resolvedBundle, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete models outside bundle folder: $resolvedModels"
    }
    Remove-Item -LiteralPath $resolvedModels -Recurse -Force
}

Copy-Item -Path (Join-Path $PSScriptRoot "stt_worker.py") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "local_tts_worker.py") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "voice_modeling_worker.py") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "video_anomaly_worker.py") -Destination $bundleDir -Force
$workerPackageDir = Join-Path $bundleDir "voicebridge"
New-Item -ItemType Directory -Path $workerPackageDir -Force | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "voicebridge\__init__.py") -Destination $workerPackageDir -Force
$workerSupportModules = @(
    "app_paths",
    "app_settings",
    "file_checks",
    "json_schemas",
    "languages",
    "local_tts_presets",
    "modeling_datasets",
    "modeling_prompt_generator",
    "stt_preflight",
    "tts_text",
    "tts_timeline",
    "video_anomalies",
    "voice_modeling",
    "voice_profiles"
)
foreach ($moduleName in $workerSupportModules) {
    Copy-Item -Path (Join-Path $PSScriptRoot "voicebridge\$moduleName.py") -Destination $workerPackageDir -Force
}
Copy-Item -Path (Join-Path $PSScriptRoot "requirements-stt.txt") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "requirements-local-tts.txt") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "README.md") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "CHANGELOG.md") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "CONTRIBUTING.md") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "SECURITY.md") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "Manual.html") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "Manual.md") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "LICENSE") -Destination $bundleDir -Force
Copy-Item -Path (Join-Path $PSScriptRoot "THIRD_PARTY_LICENSES") -Destination $bundleDir -Force
$bundleDocsImagesDir = Join-Path $bundleDir "docs\images"
New-Item -ItemType Directory -Path $bundleDocsImagesDir -Force | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "docs\images\voicebridge-dashboard.png") -Destination $bundleDocsImagesDir -Force

Write-Host "App bundle updated: $bundleDir"
