"""ساختنِ همهٔ چیزهایی که استودیوی موشن لازم دارد؛ idempotent (هر کدام اگر آماده باشد رد می‌شود).

    manage.py motion_build                 همه: ابزار، فونت‌ها، کاتالوگ، بستهٔ رندر، پخش‌کننده، مرورگرِ سایت، بستهٔ گرهٔ ویندوزی
    manage.py motion_build --only shell    فقط یک مرحله: toolchain | catalog | fonts | shell | player | browser | pack

بستهٔ گره (ویندوز) = پوشهٔ motion/remotion ِ باندل‌شده + node_modules ِ ویندوزی (@remotion/renderer و کامپوزیتورِ win32-x64) که روی همین سایت با
`npm install --os=win32 --cpu=x64` ساخته می‌شود. به‌همراهِ دو فایلِ آینهٔ رسمی (Node.js portable و Chrome headless shell ِ win64) در پوشهٔ
دانلودهای سایت (`<data>/up3d/downloads`) می‌نشیند؛ عاملِ گره (processing/motion_jobs.py) همه را خودکار و با sha256 می‌گیرد و نصب می‌کند.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from . import catalog, runner

NODE_VERSION = "20.18.0"
CHROME_VERSION = "153.0.8010.12"
NODE_ZIP = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_URLS = [f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ZIP}", f"https://npmmirror.com/mirrors/node/v{NODE_VERSION}/{NODE_ZIP}"]
NODE_SUMS_URLS = [f"https://nodejs.org/dist/v{NODE_VERSION}/SHASUMS256.txt", f"https://npmmirror.com/mirrors/node/v{NODE_VERSION}/SHASUMS256.txt"]
CHROME_WIN_ZIP = f"chrome-headless-shell-win64-{CHROME_VERSION}.zip"
CHROME_URLS = [
    f"https://cdn.npmmirror.com/binaries/chrome-for-testing/{CHROME_VERSION}/win64/chrome-headless-shell-win64.zip",
    f"https://storage.googleapis.com/chrome-for-testing-public/{CHROME_VERSION}/win64/chrome-headless-shell-win64.zip",
]
CHROME_LINUX_URLS = [
    f"https://cdn.npmmirror.com/binaries/chrome-for-testing/{CHROME_VERSION}/linux64/chrome-headless-shell-linux64.zip",
]
PACK_PREFIX = "nm-motion-pack-"
MANIFEST_NAME = "nm-motion-pack.json"
REMOTION = "4.0.543"


def say(msg: str) -> None:
    print(msg, flush=True)


def run(cmd, cwd=None, timeout=1800, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=e)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))[:120]} failed ({p.returncode}): {(p.stderr or p.stdout)[-600:]}")
    return p.stdout


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(urls: list[str], dest: Path, sha256: str | None = None, size_hint: int | None = None, attempts: int = 3) -> Path:
    """اولین نشانیِ سالم؛ ادامه‌پذیر نیست ولی خطا را با نشانیِ بعدی جبران می‌کند؛ sha256 را می‌سنجد."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (not sha256 or sha256_file(dest) == sha256):
        return dest
    last = ""
    for url in urls:
        for i in range(attempts):
            part = dest.with_suffix(dest.suffix + ".part")
            try:
                say(f"  downloading {url} ...")
                req = urllib.request.Request(url, headers={"User-Agent": "nm-motion-build/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
                    shutil.copyfileobj(r, out, 1 << 20)
                if sha256 and sha256_file(part) != sha256:
                    last = f"checksum mismatch for {url}"
                    part.unlink(missing_ok=True)
                    break
                os.replace(part, dest)
                return dest
            except Exception as exc:  # noqa: BLE001
                last = f"{url}: {exc}"
                part.unlink(missing_ok=True)
                time.sleep(3 * (i + 1))
    raise RuntimeError(f"could not download {dest.name}: {last}")


# ───────────────────────────────────────────── steps

def step_toolchain() -> None:
    """/opt/nm-motion (Remotion، esbuild، sucrase، فونت‌ها) از motion/toolchain/package.json؛ و پیوندِ motion/node_modules."""
    tc = runner.toolchain_dir()
    src = runner.repo_motion_dir() / "toolchain"
    npm = shutil.which("npm") or "/usr/bin/npm"
    tc.mkdir(parents=True, exist_ok=True)
    want = (src / "package.json").read_bytes()
    have = (tc / "package.json").read_bytes() if (tc / "package.json").is_file() else b""
    if want != have or not (tc / "node_modules").is_dir():
        say("toolchain: installing (npm ci) ...")
        shutil.copyfile(src / "package.json", tc / "package.json")
        if (src / "package-lock.json").is_file():
            shutil.copyfile(src / "package-lock.json", tc / "package-lock.json")
        run([npm, "ci", "--no-audit", "--no-fund", "--ignore-scripts"], cwd=str(tc), timeout=1800) if (tc / "package-lock.json").is_file() else run(
            [npm, "install", "--no-audit", "--no-fund", "--ignore-scripts"], cwd=str(tc), timeout=1800)
    else:
        say("toolchain: ready")
    link = runner.repo_motion_dir() / "node_modules"
    if not link.exists():
        link.symlink_to(tc / "node_modules")
        say(f"toolchain: linked {link}")


def step_catalog() -> None:
    p = catalog.write_generated(runner.repo_motion_dir() / "remotion" / "src" / "styles.generated.json")
    say(f"catalog: {len(catalog.STYLES)} styles -> {p.name}")


def step_fonts() -> None:
    node = runner.node_bin()
    say(run([node, str(runner.tools_dir() / "prepare-fonts.mjs")], cwd=str(runner.repo_motion_dir())).strip())


def step_shell() -> None:
    node = runner.node_bin()
    say(run([node, str(runner.tools_dir() / "build-shell.mjs"), str(runner.bundle_dir())], cwd=str(runner.repo_motion_dir()), timeout=1800).strip())


def step_player() -> None:
    node = runner.node_bin()
    out = runner.data_dir() / "player"
    say(run([node, str(runner.tools_dir() / "build-player.mjs"), str(out)], cwd=str(runner.repo_motion_dir()), timeout=900).strip())


def step_browser() -> None:
    """مرورگرِ بی‌سرِ لینوکس برای رندرِ سایت (اگر روی سرور نیست از آینهٔ npmmirror)."""
    if runner.browser_path():
        say(f"browser: {runner.browser_path()}")
        return
    dest = runner.data_dir() / "browser"
    zp = download(CHROME_LINUX_URLS, dest / f"chrome-headless-shell-linux64-{CHROME_VERSION}.zip")
    with zipfile.ZipFile(zp) as z:
        z.extractall(dest / "linux64")
    exe = dest / "linux64" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
    exe.chmod(0o755)
    say(f"browser: {exe}")


def _node_sha() -> str:
    for u in NODE_SUMS_URLS:
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "nm-motion-build/1.0"}), timeout=60) as r:
                for line in r.read().decode().splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == NODE_ZIP:
                        return parts[0]
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("could not read the official SHA-256 of the portable Node.js")


def _win_modules(work: Path) -> Path:
    """node_modules ِ ویندوزیِ @remotion/renderer (کامپوزیتورِ win32-x64 با npm برای os=win32 / cpu=x64)."""
    npm = shutil.which("npm") or "/usr/bin/npm"
    work.mkdir(parents=True, exist_ok=True)
    pj = {"name": "nm-motion-node", "private": True, "version": "1.0.0", "dependencies": {"@remotion/renderer": REMOTION, "remotion": REMOTION}}
    (work / "package.json").write_text(json.dumps(pj, indent=1), encoding="utf-8")
    lock = runner.repo_motion_dir() / "toolchain" / "node-package-lock.json"
    if lock.is_file():
        shutil.copyfile(lock, work / "package-lock.json")
    if not (work / "node_modules" / "@remotion" / "compositor-win32-x64-msvc").is_dir():
        say("pack: npm install --os=win32 --cpu=x64 ...")
        run([npm, "install", "--os=win32", "--cpu=x64", "--omit=dev", "--no-audit", "--no-fund", "--ignore-scripts"], cwd=str(work), timeout=1800)
    if not (work / "node_modules" / "@remotion" / "compositor-win32-x64-msvc").is_dir():
        raise RuntimeError("the win32 compositor package was not installed")
    return work / "node_modules"


def source_hash() -> str:
    v = runner.bundle_version() or {}
    h = hashlib.sha256()
    h.update(str(v.get("hash", "")).encode())
    h.update((runner.tools_dir() / "render.mjs").read_bytes())
    h.update(REMOTION.encode())
    return h.hexdigest()[:12]


def downloads_dir() -> Path:
    from apps.compute import updates

    d = updates.downloads_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def step_pack() -> dict:
    """بستهٔ گره: zip ِ (render.mjs + bundle + node_modules ِ ویندوزی) + آینهٔ Node و Chrome + manifest."""
    if not runner.bundle_version():
        raise RuntimeError("build the shell first (manage.py motion_build --only shell)")
    out = downloads_dir()
    ver = source_hash()
    pack_name = f"{PACK_PREFIX}{ver}.zip"
    pack_path = out / pack_name
    node_sha = _node_sha()
    node_zip = download(NODE_URLS, out / NODE_ZIP, sha256=node_sha)
    chrome_zip = download(CHROME_URLS, out / CHROME_WIN_ZIP)
    if not pack_path.is_file():
        work = Path(os.environ.get("NM_MOTION_WIN_DIR") or "/opt/nm-motion-win")
        mods = _win_modules(work)
        tmp = pack_path.with_suffix(".tmp")
        say(f"pack: writing {pack_name} ...")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(runner.tools_dir() / "render.mjs", "render.mjs")
            z.writestr("VERSION", ver)
            z.writestr("package.json", json.dumps({"name": "nm-motion-node", "private": True, "type": "module", "version": ver}))
            for base, prefix in ((runner.bundle_dir(), "bundle"), (mods, "node_modules")):
                for p in sorted(base.rglob("*")):
                    if p.is_file() and not p.name.endswith(".map"):
                        z.write(p, f"{prefix}/{p.relative_to(base).as_posix()}")
        os.replace(tmp, pack_path)
    for old in out.glob(f"{PACK_PREFIX}*.zip"):
        if old.name != pack_name and old.stat().st_mtime < pack_path.stat().st_mtime - 3600:
            old.unlink(missing_ok=True)
    manifest = {
        "version": ver, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "remotion": REMOTION,
        "pack": {"name": pack_name, "size": pack_path.stat().st_size, "sha256": sha256_file(pack_path)},
        "node": {"name": NODE_ZIP, "version": NODE_VERSION, "size": node_zip.stat().st_size, "sha256": sha256_file(node_zip),
                 "license": "MIT (Node.js)", "source": NODE_URLS[0]},
        "browser": {"name": CHROME_WIN_ZIP, "version": CHROME_VERSION, "size": chrome_zip.stat().st_size, "sha256": sha256_file(chrome_zip),
                    "license": "BSD-3-Clause (Chromium) + third-party notices inside the zip", "source": CHROME_URLS[0]},
    }
    mp = out / MANIFEST_NAME
    tmpm = mp.with_suffix(".tmp")
    tmpm.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    os.replace(tmpm, mp)
    say(f"pack: {pack_name} {manifest['pack']['size'] // 1048576} MB; node {NODE_VERSION}; chrome {CHROME_VERSION}; manifest {MANIFEST_NAME}")
    return manifest


STEPS = {
    "toolchain": step_toolchain, "catalog": step_catalog, "fonts": step_fonts, "shell": step_shell, "player": step_player,
    "browser": step_browser, "pack": step_pack,
}
ORDER = ["toolchain", "catalog", "fonts", "shell", "player", "browser", "pack"]


def build(only: list[str] | None = None, skip: list[str] | None = None) -> int:
    failures = 0
    for name in ORDER:
        if only and name not in only:
            continue
        if skip and name in skip:
            continue
        say(f"== {name}")
        try:
            STEPS[name]()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            say(f"!! {name} failed: {exc}")
            if name in ("toolchain", "shell"):
                break          # the rest depends on it
    return failures


if __name__ == "__main__":
    sys.exit(build())
