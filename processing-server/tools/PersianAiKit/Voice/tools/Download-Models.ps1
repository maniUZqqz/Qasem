# Download the base voice models again (new computer, or the models folder was deleted). Needs internet.
#   powershell -ExecutionPolicy Bypass -File tools\Download-Models.ps1
#   powershell -ExecutionPolicy Bypass -File tools\Download-Models.ps1 -Voices gyro        (only the default voice)
# Files that already exist are skipped. Total with all six voices: ~500 MB.
# Natural voices, voice cloning and sound-of-anything models: Setup-Voice.bat (tools\download_voice_models.py).
param([string[]]$Voices = @('gyro', 'amir', 'ganji', 'ganji_adabi', 'reza_ibrahim'))

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$models = Join-Path $root 'models'

function Get-File([string]$url, [string]$out) {
    if (Test-Path $out) { Write-Host "  exists: $out"; return }
    New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
    Write-Host "  download: $url"
    & curl.exe -L --fail --retry 3 -C - -o "$out.part" $url
    if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
    Move-Item -Force "$out.part" $out
}

Write-Host '1/4 Piper (text-to-speech engine)'
if (-not (Test-Path (Join-Path $models 'piper\piper\piper.exe'))) {
    $zip = Join-Path $env:TEMP 'piper_windows_amd64.zip'
    Get-File 'https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip' $zip
    Expand-Archive -Force $zip (Join-Path $models 'piper')
} else { Write-Host '  exists: piper.exe' }

Write-Host '2/4 Persian voices'
foreach ($v in $Voices) {
    $base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fa/fa_IR/$v/medium/fa_IR-$v-medium.onnx"
    Get-File $base (Join-Path $models "piper\voices\fa_IR-$v-medium.onnx")
    Get-File "$base.json" (Join-Path $models "piper\voices\fa_IR-$v-medium.onnx.json")
}

Write-Host '3/4 Mana voice (MIT, MahtaFetrat/Mana-Persian-Piper)'
$mana = 'https://huggingface.co/MahtaFetrat/Mana-Persian-Piper/resolve/main/fa_IR-mana-medium.onnx'
Get-File $mana (Join-Path $models 'piper\voices\fa_IR-mana-medium.onnx')
Get-File "$mana.json" (Join-Path $models 'piper\voices\fa_IR-mana-medium.onnx.json')

Write-Host '4/4 Vosk small Persian model (speech-to-text)'
if (-not (Test-Path (Join-Path $models 'vosk\vosk-model-small-fa-0.42\am'))) {
    $zip = Join-Path $env:TEMP 'vosk-model-small-fa-0.42.zip'
    Get-File 'https://alphacephei.com/vosk/models/vosk-model-small-fa-0.42.zip' $zip
    Expand-Archive -Force $zip (Join-Path $models 'vosk')
} else { Write-Host '  exists: vosk-model-small-fa-0.42' }

Write-Host ''
Write-Host "Done: $models  -  now run Run-SelfTest.bat"
