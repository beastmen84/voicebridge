param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "build_app.ps1") -Clean:$Clean
& (Join-Path $PSScriptRoot "sync_stt_bundle.ps1") -RuntimeOnly

Write-Host "Full distributable ready: $(Join-Path $PSScriptRoot 'dist\VoiceBridge')"
