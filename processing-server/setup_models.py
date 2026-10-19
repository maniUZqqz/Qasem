"""Download the models of the PersianAiKit editors (voice: Piper + Vosk, photo: upscaler) for this node.

Tries the site first ({site}/3d/files/downloads/kit-models-windows.zip, fast from inside the country),
then falls back to the kits' own download scripts (GitHub / HuggingFace / alphacephei).
Files that already exist are skipped. Safe to run again. Used by Setup-Services.bat; can be run alone:
    python setup_models.py
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
ZIP_NAME = "kit-models-windows.zip"


def site_url():
    for name in ("node.json", "site.json"):
        try:
            site = json.load(open(os.path.join(HERE, name), encoding="utf-8")).get("site")
            if site:
                return site.rstrip("/")
        except (OSError, ValueError):
            pass
    return os.environ.get("NM_SITE", "").rstrip("/")


def have_voice_models():
    m = os.path.join(KIT, "Voice", "models")
    return (os.path.isfile(os.path.join(m, "piper", "piper", "piper.exe"))
            and os.path.isdir(os.path.join(m, "vosk"))
            and any(f.endswith(".onnx") for f in os.listdir(os.path.join(m, "piper", "voices")) if os.path.isdir(os.path.join(m, "piper", "voices"))))


def have_photo_models():
    return os.path.isfile(os.path.join(KIT, "Photo", "models", "upscale", "realesr-general-x4v3.onnx"))


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


def extract_missing(zip_path):
    """The zip holds PersianAiKit/<Kit>/models/... — extract only files that do not exist yet."""
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
                dst.write(src.read())
            added += 1
    return added


def from_site():
    site = site_url()
    if not site:
        print("  site URL unknown (site.json) - skipping the site download")
        return False
    url = "%s/3d/files/downloads/%s" % (site, ZIP_NAME)
    tmp = os.path.join(tempfile.gettempdir(), ZIP_NAME)
    try:
        print("  downloading %s" % url)
        download(url, tmp)
        n = extract_missing(tmp)
        print("  %d file(s) added from the site package" % n)
        return True
    except Exception as e:  # noqa: BLE001
        print("  site package not available (%s)" % str(e)[:120])
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def powershell(script, *args):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script] + list(args)
    print("  running %s" % os.path.basename(script))
    return subprocess.call(cmd, cwd=os.path.dirname(os.path.dirname(script))) == 0


def main():
    if have_voice_models() and have_photo_models():
        print("models: already there (voice: Piper + Vosk, photo: upscaler)")
        return 0
    print("models: fetching what is missing")
    from_site()
    ok = True
    if not have_voice_models():
        print("voice models still missing - trying the kit's own downloader (internet: GitHub / HuggingFace / alphacephei)")
        ok = powershell(os.path.join(KIT, "Voice", "tools", "Download-Models.ps1")) and have_voice_models()
    if not have_photo_models():
        print("photo upscaler missing - trying the kit's own downloader (HuggingFace)")
        ok = powershell(os.path.join(KIT, "Photo", "tools", "Download-Models.ps1")) and have_photo_models() and ok
    print("models: %s" % ("OK" if ok else "INCOMPLETE - the voice editor (text-to-speech / speech-to-text) needs its models; run this again with internet or a VPN"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
