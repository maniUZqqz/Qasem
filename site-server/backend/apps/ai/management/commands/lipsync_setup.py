"""Install lip-sync into the ComfyUI on this machine.

    python manage.py lipsync_setup --comfyui-dir D:\\ComfyUI_windows_portable
    python manage.py lipsync_setup --check --comfyui-dir ...   # exit 1 + one line per missing piece
    python manage.py lipsync_setup --english ...               # English output (for start.bat)

What it puts in place, each step skipped when already done:

1. The custom node ComfyUI-LatentSyncWrapper (github.com/ShmuelRonen), from
   the GitHub zip — no git needed — into ComfyUI's `custom_nodes`.
2. Its Python packages, into ComfyUI's OWN Python (the portable build's
   `python_embeded`), not this project's: the node runs inside ComfyUI.
3. The LatentSync 1.6 checkpoints (`latentsync_unet.pt`, `whisper/tiny.pt`)
   into the node's `checkpoints` folder, from Hugging Face or its mirror. The
   node would otherwise download them itself on the first lip-sync request,
   in the middle of a customer's job, from inside ComfyUI where a blocked
   Hugging Face is a stack trace nobody sees.

Used only by scenes marked «گوینده در تصویر»; see services/video/lipsync.py.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import requests
from django.core.management.base import BaseCommand

from .audio_setup import _download, _hf_bases, _looks_complete

NODE_FOLDER = "ComfyUI-LatentSyncWrapper"
NODE_ZIP = "https://github.com/ShmuelRonen/ComfyUI-LatentSyncWrapper/archive/refs/heads/main.zip"
CHECKPOINTS = {
    "latentsync_unet.pt": "latentsync_unet.pt",
    "whisper/tiny.pt": "whisper/tiny.pt",
}
#: Packages whose import proves the requirements went into ComfyUI's Python.
PROBE_IMPORTS = "import omegaconf, einops, decord, face_alignment, diffusers"


def _comfy_root(given: str | None) -> Path | None:
    raw = given or os.environ.get("COMFYUI_DIR") or ""
    return Path(raw) if raw and Path(raw).exists() else None


def _custom_nodes(root: Path) -> Path:
    """Portable builds keep ComfyUI one level down."""
    portable = root / "ComfyUI" / "custom_nodes"
    return portable if portable.exists() else root / "custom_nodes"


def _long(path: Path) -> str:
    """A Windows path that is not limited to 260 characters."""
    text = str(path.resolve())
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def _extract(archive: zipfile.ZipFile, target: Path) -> None:
    """Unpack a GitHub zip into `target`, dropping its top folder and .github.

    Directly, not via extractall into a staging folder: the archive's own
    top-level folder name plus a deep ComfyUI path goes past Windows' 260
    characters (measured: WinError 206 on a nested .github template).
    """
    staged = target.with_name(target.name + ".partial")
    shutil.rmtree(_long(staged), ignore_errors=True)
    for member in archive.infolist():
        parts = member.filename.split("/")[1:]
        if not parts or not parts[0] or parts[0] == ".github":
            continue
        destination = staged.joinpath(*parts)
        if member.is_dir():
            os.makedirs(_long(destination), exist_ok=True)
            continue
        os.makedirs(_long(destination.parent), exist_ok=True)
        with archive.open(member) as source, open(_long(destination), "wb") as sink:
            shutil.copyfileobj(source, sink)
    # Only a complete download becomes the node folder ComfyUI loads.
    os.replace(_long(staged), _long(target))


def _python(root: Path) -> Path | None:
    embedded = root / "python_embeded" / "python.exe"
    return embedded if embedded.exists() else None


class Command(BaseCommand):
    help = "لب‌خوانی (LatentSync) را روی ComfyUI همین سیستم نصب می‌کند"

    def add_arguments(self, parser):
        parser.add_argument("--comfyui-dir", help="پوشه‌ی ComfyUI (یا متغیر COMFYUI_DIR)")
        parser.add_argument("--check", action="store_true", help="فقط بررسی؛ کد خروج ۱ اگر چیزی کم است")
        parser.add_argument("--english", action="store_true", help="پیام‌ها به انگلیسی (برای start.bat)")

    def say(self, persian: str, english: str) -> None:
        self.stdout.write(english if self.english else persian)

    def handle(self, *args, **options):
        self.english = bool(options["english"] or options["check"])
        root = _comfy_root(options.get("comfyui_dir"))
        if root is None:
            self.say("پوشه‌ی ComfyUI پیدا نشد — --comfyui-dir را بدهید.",
                     "[SKIP] ComfyUI folder not found - pass --comfyui-dir")
            if options["check"]:
                sys.exit(1)
            return
        if options["check"]:
            missing = self.missing(root)
            for line in missing:
                self.stdout.write(line)
            if missing:
                sys.exit(1)
            return
        self.install(root)
        missing = self.missing(root)
        for line in missing:
            self.stdout.write(line)
        if not missing:
            self.say("لب‌خوانی آماده است. ComfyUI را یک بار دوباره اجرا کنید تا نود بارگذاری شود.",
                     "[OK] Lip-sync is ready. Restart ComfyUI once so it loads the node.")

    # ------------------------------------------------------------ check

    def missing(self, root: Path) -> list[str]:
        node = _custom_nodes(root) / NODE_FOLDER
        lines = []
        if not (node / "nodes.py").exists():
            lines.append(f"[MISSING] lip-sync node {NODE_FOLDER} in {node.parent}")
            return lines
        python = _python(root)
        if python is not None:
            probe = subprocess.run([str(python), "-c", PROBE_IMPORTS], capture_output=True, text=True)
            if probe.returncode != 0:
                lines.append("[MISSING] lip-sync Python packages in ComfyUI's python_embeded")
        for name in CHECKPOINTS:
            if not _looks_complete(node / "checkpoints" / name):
                lines.append(f"[MISSING] lip-sync model file checkpoints/{name}")
        return lines

    # ------------------------------------------------------------ install

    def install(self, root: Path) -> None:
        nodes = _custom_nodes(root)
        node = nodes / NODE_FOLDER
        if not (node / "nodes.py").exists():
            self.say("دانلود نود لب‌خوانی از GitHub…", "Downloading the lip-sync node from GitHub...")
            try:
                response = requests.get(NODE_ZIP, timeout=120, headers={"User-Agent": "UpMarket/1.0"})
                response.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    _extract(archive, node)
                self.say("  ✓ نود نصب شد", "  [OK] node installed")
            except Exception as exc:  # noqa: BLE001
                self.say(f"  ✗ نود نصب نشد: {exc}", f"  [FAILED] node: {exc}")
                return

        python = _python(root)
        if python is None:
            self.say(
                "این ComfyUI نسخه‌ی portable نیست؛ بسته‌ها را با Python خود ComfyUI نصب کنید: "
                f"pip install -r \"{node / 'requirements.txt'}\"",
                "[INFO] Not a portable ComfyUI: install the packages with ComfyUI's own Python: "
                f"pip install -r \"{node / 'requirements.txt'}\"",
            )
        else:
            self.say("نصب بسته‌های Python در ComfyUI (چند دقیقه)…",
                     "Installing the node's Python packages into ComfyUI (a few minutes)...")
            result = subprocess.run(
                [str(python), "-m", "pip", "install", "-r", str(node / "requirements.txt")],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self.say("  ✓ بسته‌ها نصب شد", "  [OK] packages installed")
            else:
                tail = (result.stderr or result.stdout)[-300:]
                self.say(f"  ✗ نصب بسته‌ها: {tail}", f"  [FAILED] packages: {tail}")

        self.say("مدل LatentSync 1.6 (حدود ۵ گیگابایت، یک بار):",
                 "LatentSync 1.6 model (about 5 GB, once):")
        for name, remote in CHECKPOINTS.items():
            _download(
                [f"{base}/ByteDance/LatentSync-1.6/resolve/main/{remote}" for base in _hf_bases()],
                node / "checkpoints" / name, label=name, say=self.say,
            )
