"""Free music a shop can actually use. §7 (phase 22).

The engine to lay music under narration already exists in `music.py`. What was
missing was the music, and shipping our own files was the thing not to do: a
track with an imperfect licence becomes a copyright strike on the *customer's*
account, weeks later, with no explanation they can act on.

**Openverse is the source, because of what it returns rather than what it has.**
It is the Creative Commons search index — the successor to CC Search — and every
result carries its licence and the attribution string that licence requires. A
library that hands you an MP3 and no licence data is a library that has moved
the problem to you.

Three rules this module will not bend:

**Only licences a shop can use commercially.** These are businesses selling
things. `NC` means non-commercial, and a shop's advertising video is the
definition of commercial — so NC results are filtered out here rather than shown
with a warning nobody reads. `ND` means no derivatives, and putting a track
under narration and ducking it is a derivative.

**Attribution travels with the file.** CC-BY requires credit. The attribution
text comes back with every track and is stored with it, so a shop publishing the
video has the exact line to paste. A picker that dropped it would be handing
people a licence violation.

**Nothing is cached as "free forever".** A licence is a fact about a moment;
uploaders change them and take things down. Each track keeps the URL it came
from and the date we saw it, the same way competitor prices do.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

API = "https://api.openverse.org/v1/audio/"
TIMEOUT = 15

#: Licences a shop selling things may actually use. Everything else is filtered
#: out rather than shown with a caveat — a caveat on a download button is a
#: caveat nobody reads.
#:
#: `by` needs credit, `cc0`/`pdm` need nothing. `sa` (share-alike) is left out
#: on purpose: it would arguably require the shop to license their own video
#: under the same terms, and that is not a decision a music picker should make
#: for somebody.
USABLE = ("cc0", "pdm", "by")

LICENCE_NAMES = {
    "cc0": "CC0 — بدون هیچ شرطی",
    "pdm": "مالکیت عمومی — بدون هیچ شرطی",
    "by": "CC-BY — باید نام سازنده را ذکر کنید",
}

#: What a fifteen-second ad needs. Anything under this is a sound effect and
#: anything over ten minutes is a set nobody will scrub through.
MIN_SECONDS = 15
MAX_SECONDS = 600


class LibraryUnavailable(Exception):
    """The search could not run. Says so rather than returning an empty list —
    "no results" and "we could not look" send a shop in opposite directions."""


def _duration(row: dict) -> float:
    """Openverse reports milliseconds, and sometimes nothing at all."""
    raw = row.get("duration")
    try:
        return float(raw) / 1000 if raw else 0.0
    except (TypeError, ValueError):
        return 0.0


def _attribution(row: dict) -> str:
    """The credit line the licence requires, as Openverse composes it.

    Taken verbatim rather than assembled from parts: the required wording is a
    property of the licence, and inventing our own phrasing is how a shop ends
    up with a credit that does not satisfy it.
    """
    text = (row.get("attribution") or "").strip()
    if text:
        return text
    creator = row.get("creator") or "نامشخص"
    title = row.get("title") or "بدون نام"
    return f"«{title}» اثر {creator} — {row.get('license', '').upper()}"


def _track(row: dict) -> dict:
    licence = str(row.get("license", "")).lower()
    return {
        "id": row.get("id"),
        "title": (row.get("title") or "بدون نام")[:160],
        "creator": (row.get("creator") or "")[:120],
        "seconds": round(_duration(row), 1),
        "url": row.get("url"),
        "page": row.get("foreign_landing_url") or row.get("url"),
        "licence": licence,
        "licence_name": LICENCE_NAMES.get(licence, licence.upper()),
        # Empty for CC0 and public domain — and that emptiness is the useful
        # signal, not a missing field.
        "attribution": _attribution(row) if licence == "by" else "",
        "needs_credit": licence == "by",
        "source": row.get("source") or "openverse",
    }


def search(query: str = "", *, limit: int = 20, page: int = 1) -> dict:
    """Tracks a shop may use in an advertising video.

    An empty query is a browse, not an error: most people opening a music
    picker do not arrive with a search term.
    """
    params = {
        "q": (query or "instrumental background").strip()[:120],
        "license": ",".join(USABLE),
        "page_size": max(1, min(50, int(limit))),
        "page": max(1, min(20, int(page))),
        "mature": "false",
    }

    try:
        response = requests.get(
            API, params=params,
            headers={"User-Agent": "NMarketing/1.0 (+https://nmarketing.ir)"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise LibraryUnavailable(
            f"کتابخانه‌ی موسیقی در دسترس نیست: {exc}. می‌توانید فایل خودتان را "
            "آپلود کنید."
        ) from exc
    except ValueError as exc:
        raise LibraryUnavailable("پاسخ کتابخانه‌ی موسیقی خوانده نشد.") from exc

    tracks = []
    for row in payload.get("results", []):
        licence = str(row.get("license", "")).lower()
        # Belt and braces: the API filter above should already have done this,
        # and the consequence of it not having is a shop publishing a video
        # with a track they are not allowed to use.
        if licence not in USABLE:
            continue
        seconds = _duration(row)
        if seconds and not (MIN_SECONDS <= seconds <= MAX_SECONDS):
            continue
        if not row.get("url"):
            continue
        tracks.append(_track(row))

    return {
        "tracks": tracks,
        "total": payload.get("result_count", len(tracks)),
        "page": params["page"],
        # Said on every result set, because "free" is the word people hear and
        # "free for commercial use, with credit" is what it actually means.
        "note": (
            "همه‌ی این‌ها را می‌توانید در ویدیوی تبلیغاتی استفاده کنید. "
            "هرکدام که «CC-BY» است، باید نام سازنده‌اش را در توضیحات پست "
            "بنویسید — متنش کنار خودش آمده."
        ),
    }


def fetch(url: str, out_path) -> "Path":  # noqa: F821 - typing only
    """Download one track. Refuses anything that is not audio.

    A URL that comes back as HTML is a takedown page or a login wall, and
    handing that to ffmpeg produces an error about a corrupt file rather than
    an explanation.
    """
    from pathlib import Path

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(
            url, stream=True, timeout=60,
            headers={"User-Agent": "NMarketing/1.0 (+https://nmarketing.ir)"},
        ) as response:
            response.raise_for_status()
            kind = response.headers.get("content-type", "")
            if "audio" not in kind and "octet-stream" not in kind:
                raise LibraryUnavailable(
                    "این نشانی فایل صوتی برنگرداند — احتمالاً آهنگ برداشته شده "
                    "است. یکی دیگر را انتخاب کنید."
                )
            size = 0
            with out.open("wb") as handle:
                for chunk in response.iter_content(1 << 16):
                    size += len(chunk)
                    # A "track" this big is not a track. Twenty megabytes is
                    # the same ceiling the upload path uses.
                    if size > 20 * 1024 * 1024:
                        raise LibraryUnavailable("این فایل از ۲۰ مگابایت بزرگ‌تر است.")
                    handle.write(chunk)
    except requests.RequestException as exc:
        raise LibraryUnavailable(f"دانلود آهنگ انجام نشد: {exc}") from exc

    if not out.exists() or out.stat().st_size == 0:
        raise LibraryUnavailable("فایل دانلود شد ولی خالی بود.")
    return out


def available() -> dict:
    """What the panel says about the library before anyone searches."""
    return {
        "source": "Openverse",
        "why": (
            "Openverse فهرست رسمی آثار Creative Commons است و مجوز و متن "
            "لازم برای ذکر منبع را همراه هر آهنگ می‌دهد. کتابخانه‌ای که فقط "
            "فایل بدهد و مجوزش را نه، مشکل را به شما منتقل کرده است."
        ),
        "licences": [LICENCE_NAMES[key] for key in USABLE],
        # Stated up front: these are shops selling things, and the licence that
        # forbids that is the one people most often miss.
        "excluded": (
            "آهنگ‌های «غیرتجاری» (NC) نشان داده نمی‌شوند، چون ویدیوی تبلیغاتی "
            "فروشگاه دقیقاً استفاده‌ی تجاری است."
        ),
    }
