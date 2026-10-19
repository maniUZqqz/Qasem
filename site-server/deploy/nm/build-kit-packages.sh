#!/bin/bash
# Builds the two packages the processing nodes download in Setup-Services.bat (setup_kit.py):
#   data/up3d/downloads/kit-apps-windows.zip    PersianAiKit Photo/Video/Voice published for win-x64 (self-contained) + ffmpeg.exe
#   data/up3d/downloads/kit-models-windows.zip  Piper (win) + 6 Persian voices + Vosk small fa + Real-ESRGAN upscaler
# Needed after moving to a new server (data/ is not in git). Uses a private .NET 8 SDK in /opt/dotnet8 (installed if missing).
set -eu
ROOT=/var/www/NM/upmarket; OUT=$ROOT/data/up3d/downloads; W=/root/kitbuild
mkdir -p "$OUT" "$W"; cd "$W"
if [ ! -x /opt/dotnet8/sdk/dotnet ]; then
  mkdir -p /opt/dotnet8 && curl -sSL -o /opt/dotnet8/dotnet-install.sh https://dot.net/v1/dotnet-install.sh
  bash /opt/dotnet8/dotnet-install.sh --channel 8.0 --install-dir /opt/dotnet8/sdk
fi
export DOTNET_ROOT=/opt/dotnet8/sdk PATH=/opt/dotnet8/sdk:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
get() { curl -L --fail --retry 3 -C - --connect-timeout 20 -o "$2" "$1"; }
# ---- apps
rm -rf src out && cp -r $ROOT/processing/tools/PersianAiKit src
for K in Photo Video Voice; do
  dotnet publish src/$K/src/PersianAiKit.$K.Server/PersianAiKit.$K.Server.csproj -c Release -r win-x64 --self-contained true -o out/PersianAiKit/$K/app
done
get https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip ff.zip
rm -rf ff && unzip -oq ff.zip -d ff && mkdir -p out/PersianAiKit/Video/tools/ffmpeg/bin && cp ff/*/bin/ffmpeg.exe ff/*/bin/ffprobe.exe out/PersianAiKit/Video/tools/ffmpeg/bin/
(cd out && rm -f "$OUT/kit-apps-windows.zip" && zip -qr9 "$OUT/kit-apps-windows.zip" PersianAiKit)
# ---- models
M=models/PersianAiKit; rm -rf models; mkdir -p "$M/Voice/models/piper/voices" "$M/Voice/models/vosk" "$M/Photo/models/upscale"
get https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip piper_win.zip && unzip -oq piper_win.zip -d "$M/Voice/models/piper"
for v in gyro ganji amir ganji_adabi reza_ibrahim; do b="https://huggingface.co/rhasspy/piper-voices/resolve/main/fa/fa_IR/$v/medium/fa_IR-$v-medium.onnx"; get "$b" "$M/Voice/models/piper/voices/fa_IR-$v-medium.onnx"; get "$b.json" "$M/Voice/models/piper/voices/fa_IR-$v-medium.onnx.json"; done
b=https://huggingface.co/MahtaFetrat/Mana-Persian-Piper/resolve/main/fa_IR-mana-medium.onnx; get $b "$M/Voice/models/piper/voices/fa_IR-mana-medium.onnx"; get $b.json "$M/Voice/models/piper/voices/fa_IR-mana-medium.onnx.json"
get https://alphacephei.com/vosk/models/vosk-model-small-fa-0.42.zip vosk.zip && unzip -oq vosk.zip -d "$M/Voice/models/vosk"
get https://huggingface.co/CoderViking/realesr-general-x4v3-onnx/resolve/main/realesr-general-x4v3.onnx "$M/Photo/models/upscale/realesr-general-x4v3.onnx"
(cd models && rm -f "$OUT/kit-models-windows.zip" && zip -qr9 "$OUT/kit-models-windows.zip" PersianAiKit)
ls -la "$OUT"
