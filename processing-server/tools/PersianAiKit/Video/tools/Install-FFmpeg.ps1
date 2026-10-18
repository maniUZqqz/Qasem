# Install FFmpeg (the video engine) - needs internet. Everything in this project runs through ffmpeg.exe / ffprobe.exe.
#   powershell -ExecutionPolicy Bypass -File tools\Install-FFmpeg.ps1
# 1) If ffmpeg is already found (PATH, winget, tools\ffmpeg\bin) nothing is done.
# 2) winget (Windows 10/11): Gyan.FFmpeg full build (has vidstab, lensfun, zimg, libx264/x265, loudnorm, afftdn...).
# 3) Otherwise: BtbN GPL build zip -> tools\ffmpeg\bin
# License: these FFmpeg builds are GPL. The app calls ffmpeg.exe as a separate program (no linking).
# If you ship ffmpeg.exe to customers, ship its license and offer its source (see README).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root 'tools\ffmpeg\bin'

function Test-FFmpeg([string]$dir) { return (Test-Path (Join-Path $dir 'ffmpeg.exe')) -and (Test-Path (Join-Path $dir 'ffprobe.exe')) }

if (Test-FFmpeg $local) { Write-Host "already here: $local"; exit 0 }
$onPath = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
if ($onPath -and (Get-Command ffprobe.exe -ErrorAction SilentlyContinue)) { Write-Host "already on PATH: $($onPath.Source)"; exit 0 }
$wingetPkgs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
$found = Get-ChildItem $wingetPkgs -Directory -Filter 'Gyan.FFmpeg*' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem $_.FullName -Directory -Filter 'ffmpeg-*' } | Where-Object { Test-FFmpeg (Join-Path $_.FullName 'bin') } | Select-Object -First 1
if ($found) { Write-Host "already installed by winget: $($found.FullName)"; exit 0 }

if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
    Write-Host 'Installing FFmpeg with winget (Gyan.FFmpeg, ~100 MB)...'
    winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) { Write-Host 'Done. Close and reopen the terminal, then run Run-SelfTest.bat'; exit 0 }
    Write-Host 'winget failed, downloading the zip instead...'
}

$free = (Get-PSDrive (Split-Path $root -Qualifier).TrimEnd(':')).Free / 1GB
if ($free -lt 1) { throw "Less than 1 GB free on the disk ($([math]::Round($free,1)) GB). Free some space first." }
$zip = Join-Path $env:TEMP 'ffmpeg-gpl.zip'
$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
Write-Host "download: $url"
& curl.exe -L --fail --retry 3 -o $zip $url
if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
$tmp = Join-Path $env:TEMP 'ffmpeg-gpl'
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive $zip $tmp
$bin = Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
New-Item -ItemType Directory -Force $local | Out-Null
Copy-Item (Join-Path $bin.DirectoryName '*.exe') $local
Remove-Item -Recurse -Force $tmp, $zip
Write-Host "Done: $local  -  now run Run-SelfTest.bat"
