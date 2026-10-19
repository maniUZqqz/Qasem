"""Prepare the PersianAiKit editors (photo / video / voice) on this node - no .NET SDK, no internet needed.

Downloads two ready packages from the site and unpacks only what is missing:
  {site}/3d/files/downloads/kit-apps-windows.zip    the three editors, published for Windows (self-contained) + ffmpeg
  {site}/3d/files/downloads/kit-models-windows.zip  Piper + 6 Persian voices + Vosk (voice), upscaler (photo)
If the site cannot be reached it falls back to the kits' own scripts (dotnet publish / internet downloads).
Safe to run again. Used by Setup-Services.bat; can be run alone:   python setup_kit.py
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "tools", "PersianAiKit")
KITS = ("Photo", "Video", "Voice")


def site_url():
    for name in ("node.json", "site.json"):
        try:
            site = json.load(open(os.path.join(HERE, name), encoding="utf-8")).get("site")
            if site:
                return site.rstrip("/")
        except (OSError, ValueError):
            pass
    return os.environ.get("NM_SITE", "").rstrip("/")


def have_apps():
    return all(os.path.isfile(os.path.join(KIT, k, "app", "PersianAiKit.%s.Server.exe" % k)) for k in KITS)


def have_ffmpeg():
    return os.path.isfile(os.path.join(KIT, "Video", "tools", "ffmpeg", "bin", "ffmpeg.exe"))


def have_models():
    m = os.path.join(KIT, "Voice", "models")
    voices = os.path.join(m, "piper", "voices")
    return (os.path.isfile(os.path.join(m, "piper", "piper", "piper.exe")) and os.path.isdir(os.path.join(m, "vosk"))
            and os.path.isdir(voices) and any(f.endswith(".onnx") for f in os.listdir(voices))
            and os.path.isfile(os.path.join(KIT, "Photo", "models", "upscale", "realesr-general-x4v3.onnx")))


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "nm-node-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                print("\r  %d / %d MB" % (done >> 20, total >> 20), end="", flush=True)
        print()


def unpack_missing(zip_path):
    """Archive entries are PersianAiKit/<Kit>/...; files that already exist are kept."""
    added = 0
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            if member.endswith("/") or not member.startswith("PersianAiKit/"):
                continue
            target = os.path.join(KIT, *member.split("/")[1:])
            if os.path.isfile(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            added += 1
    return added


def from_site(name):
    site = site_url()
    if not site:
        print("  site URL unknown (site.json) - skipping")
        return False
    url = "%s/3d/files/downloads/%s" % (site, name)
    tmp = os.path.join(tempfile.gettempdir(), name)
    try:
        print("  downloading %s" % url)
        download(url, tmp)
        print("  %d file(s) unpacked" % unpack_missing(tmp))
        return True
    except Exception as e:  # noqa: BLE001
        print("  not available from the site (%s)" % str(e)[:150])
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def run(cmd, cwd=None):
    print("  > %s" % " ".join(cmd))
    try:
        return subprocess.call(cmd, cwd=cwd or HERE) == 0
    except OSError as e:
        print("  failed: %s" % e)
        return False


def main():
    print("[1/2] editors (photo / video / voice) + ffmpeg")
    if have_apps() and have_ffmpeg():
        print("  already prepared")
    else:
        from_site("kit-apps-windows.zip")
        for k in KITS:
            if not os.path.isfile(os.path.join(KIT, k, "app", "PersianAiKit.%s.Server.exe" % k)):
                print("  %s editor still missing - trying dotnet publish (needs the .NET 8 SDK and nuget.org)" % k)
                run(["dotnet", "publish", os.path.join(KIT, k, "src", "PersianAiKit.%s.Server" % k, "PersianAiKit.%s.Server.csproj" % k),
                     "-c", "Release", "-o", os.path.join(KIT, k, "app"), "--nologo", "-v", "q"])
        if not have_ffmpeg() and not shutil_which("ffmpeg"):
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(KIT, "Video", "tools", "Install-FFmpeg.ps1")])
    print("[2/2] models (Piper voices + Vosk for the voice editor, upscaler for the photo editor)")
    if have_models():
        print("  already there")
    else:
        from_site("kit-models-windows.zip")
        if not have_models():
            print("  still missing - trying the kits' own downloaders (internet)")
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(KIT, "Voice", "tools", "Download-Models.ps1")])
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(KIT, "Photo", "tools", "Download-Models.ps1")])
    ok = have_apps() and (have_ffmpeg() or bool(shutil_which("ffmpeg"))) and have_models()
    print("RESULT: %s" % ("editors ready" if ok else "INCOMPLETE - see the lines above"))
    return 0 if ok else 1


def shutil_which(name):
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    sys.exit(main())
