# -*- coding: utf-8 -*-
"""نسخه‌بندی با Git (idea.md §۹): هر «تولیدِ کد» یک commit در پوشهٔ همان پروژه.

· تاریخچه همراهِ پروژه است (پوشهٔ .git داخلِ workspace)؛ با ZIP هم می‌شود بُردش.
· اگر git روی سرور نباشد یا خطا بدهد، تولیدِ کد نمی‌شکند — فقط تاریخچه ثبت نمی‌شود.
"""
import os
import re
import shutil
import subprocess

GITIGNORE = ('venv/\n.venv/\n__pycache__/\n*.pyc\ndb.sqlite3\n*.sqlite3\nmedia/\nstaticfiles/\n'
             '.env\n.preview.*\n.studio-*\n')
SHA_RE = re.compile(r'^[0-9a-f]{7,40}$')
MAX_SHOW = 400_000


def available():
    return shutil.which('git') is not None


def _git(project, *args, timeout=60):
    cmd = ['git', '-c', 'user.name=Commerce Studio', '-c', 'user.email=studio@localhost',
           '-c', 'core.quotepath=off', '-c', 'commit.gpgsign=false'] + list(args)
    return subprocess.run(cmd, cwd=str(project.path), capture_output=True, text=True,
                          timeout=timeout, encoding='utf-8', errors='replace')


def ensure_repo(project):
    root = str(project.path)
    if not os.path.isdir(root) or not available():
        return False
    if not os.path.isdir(os.path.join(root, '.git')):
        r = _git(project, 'init', '-q')
        if r.returncode != 0:
            return False
    gi = os.path.join(root, '.gitignore')
    if not os.path.exists(gi):
        with open(gi, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(GITIGNORE)
    return True


def commit(project, message):
    """⇒ {'sha', 'stat'} یا None اگر چیزی عوض نشده بود/گیت نبود."""
    try:
        if not ensure_repo(project):
            return None
        _git(project, 'add', '-A')
        if _git(project, 'diff', '--cached', '--quiet').returncode == 0:
            return None
        r = _git(project, 'commit', '-q', '-m', message or 'تولیدِ کد')
        if r.returncode != 0:
            return None
        sha = _git(project, 'rev-parse', '--short', 'HEAD').stdout.strip()
        stat = _git(project, 'show', '--stat', '--format=', 'HEAD').stdout.strip()
        return {'sha': sha, 'stat': stat}
    except (OSError, subprocess.SubprocessError):
        return None


def log(project, n=60):
    if not os.path.isdir(os.path.join(str(project.path), '.git')):
        return []
    r = _git(project, 'log', '-n', str(n), '--date=format:%Y/%m/%d %H:%M',
             '--pretty=format:%h\x1f%H\x1f%ad\x1f%s\x1f', '--shortstat')
    out = []
    for block in r.stdout.split('\n'):
        block = block.strip()
        if not block:
            continue
        if '\x1f' in block:
            short, full, date, subject, _ = (block.split('\x1f') + [''] * 5)[:5]
            out.append({'short': short, 'sha': full, 'date': date, 'subject': subject, 'stat': ''})
        elif out:
            out[-1]['stat'] = block
    return out


def show(project, sha):
    """یک commit: سربرگ + فهرستِ فایل‌ها + Diff ⇒ (meta, files, diff_text)"""
    if not SHA_RE.match(sha or ''):
        return None
    meta = _git(project, 'show', '-s', '--date=format:%Y/%m/%d %H:%M', '--pretty=format:%h\x1f%ad\x1f%s', sha)
    if meta.returncode != 0:
        return None
    short, date, subject = (meta.stdout.split('\x1f') + ['', '', ''])[:3]
    files = _git(project, 'show', '--numstat', '--format=', sha).stdout.strip().splitlines()
    rows = []
    for line in files:
        parts = line.split('\t')
        if len(parts) == 3:
            rows.append({'add': parts[0], 'del': parts[1], 'path': parts[2]})
    diff = _git(project, 'show', '--format=', '--patch', sha).stdout
    truncated = len(diff) > MAX_SHOW
    return {'short': short, 'date': date, 'subject': subject, 'files': rows,
            'diff': diff[:MAX_SHOW], 'truncated': truncated}
