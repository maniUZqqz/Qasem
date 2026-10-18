# Download the photo models again (new computer, or the models folder was deleted). Needs internet.
#   powershell -ExecutionPolicy Bypass -File tools\Download-Models.ps1            upscaler only (5 MB) - enough for a normal PC
#   powershell -ExecutionPolicy Bypass -File tools\Download-Models.ps1 -Server    + AI background remover (224 MB, needs ~6.5 GB free RAM to run)
# Every slider, filter, auto, the light background remover and the web editor work WITHOUT any model.
# Files that already exist are skipped.
param([switch]$Server)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$models = Join-Path $root 'models'

function Get-File([string]$url, [string]$out, [string]$sha256) {
    if (Test-Path $out) { Write-Host "  exists: $out"; return }
    New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
    Write-Host "  download: $url"
    & curl.exe -L --fail --retry 3 -C - -o "$out.part" $url
    if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
    $h = (Get-FileHash "$out.part" -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha256 -and $h -ne $sha256) { throw "checksum mismatch for $out ($h)" }
    Move-Item -Force "$out.part" $out
}

Write-Host '1/2 Upscaler: Real-ESRGAN general-x4v3 (BSD-3, 5 MB)'
Get-File 'https://huggingface.co/CoderViking/realesr-general-x4v3-onnx/resolve/main/realesr-general-x4v3.onnx' `
    (Join-Path $models 'upscale\realesr-general-x4v3.onnx') '1940a93ee08283a0a7286183186357b1688fe9fa8ede74604b424586aaddf112'

if ($Server) {
    Write-Host '2/2 AI background remover: BiRefNet-lite (MIT, 224 MB) - heavy: ~6.5 GB free RAM and ~70 s per photo on a 4-core CPU'
    Get-File 'https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/main/onnx/model.onnx' `
        (Join-Path $models 'background\birefnet-lite.onnx') '5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333'
} else {
    Write-Host '2/2 AI background remover skipped (use -Server on a machine with 16 GB RAM). The light remover needs no model.'
}

Write-Host ''
Write-Host "Done: $models  -  now run Run-SelfTest.bat"
