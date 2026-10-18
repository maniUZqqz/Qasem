"""Publish to Instagram through NovinHub.

Reference: https://novinhub.com/developers

The flow is two-step and file-based: every media file is uploaded first
(`POST /file` → an id), then a post is created referencing those ids
(`POST /post`). Nothing is published from a URL, so our generated files have
to be pushed up rather than linked.

n8n stays supported and is still the default: it needs no account and the
store owner wires it themselves. NovinHub is the managed path — it costs
money per customer, which is why the pitch counts it as a variable cost.
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.novinhub.com/token/v2"
UPLOAD_TIMEOUT = 300
CALL_TIMEOUT = 60


class NovinHubError(Exception):
    """NovinHub refused the request or returned something unusable."""


class NovinHubNotConfigured(NovinHubError):
    def __init__(self):
        super().__init__(
            "توکن نوین‌هاب تنظیم نشده است. "
            "در تنظیمات فروشگاه یا NOVINHUB_TOKEN در .env مقدارش را بگذار."
        )


def _config(store=None) -> tuple[str, str]:
    """Per-store token wins; the .env value is the shared fallback."""
    conf = getattr(settings, "UPMARKET_PUBLISHING", {})
    base = (conf.get("NOVINHUB_BASE_URL") or DEFAULT_BASE).rstrip("/")
    token = conf.get("NOVINHUB_TOKEN", "")

    profile = getattr(store, "profile", None) if store else None
    token = (getattr(profile, "novinhub_token", "") or token).strip()
    if not token:
        raise NovinHubNotConfigured()
    return base, token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _check(response: requests.Response, what: str) -> dict:
    if response.status_code == 401:
        raise NovinHubError("توکن نوین‌هاب پذیرفته نشد (۴۰۱).")
    if response.status_code == 429:
        raise NovinHubError("سقف درخواست نوین‌هاب پر شده است (۴۲۹). کمی بعد دوباره تلاش کن.")
    if response.status_code >= 400:
        raise NovinHubError(f"{what} ناموفق بود ({response.status_code}): {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise NovinHubError(f"پاسخ {what} JSON نبود.") from exc


# ------------------------------------------------------------------ media


def upload(path, *, store=None) -> int:
    """Push one file up and return its NovinHub file id."""
    base, token = _config(store)
    file_path = Path(path)
    if not file_path.exists():
        raise NovinHubError(f"فایل پیدا نشد: {file_path}")

    try:
        with file_path.open("rb") as fh:
            response = requests.post(
                f"{base}/file",
                headers=_headers(token),
                files={"file": (file_path.name, fh)},
                timeout=UPLOAD_TIMEOUT,
            )
    except requests.RequestException as exc:
        raise NovinHubError(f"آپلود فایل ممکن نشد: {exc}") from exc

    data = _check(response, "آپلود فایل")
    file_id = data.get("id") or (data.get("data") or {}).get("id")
    if not file_id:
        raise NovinHubError(f"شناسه فایل در پاسخ نبود: {str(data)[:200]}")
    logger.info("novinhub upload %s → id=%s", file_path.name, file_id)
    return int(file_id)


# ------------------------------------------------------------------- post


def create_post(
    *,
    account_ids: list[int],
    media_ids: list[int],
    caption: str = "",
    kind: str = "image",
    reels: bool = False,
    schedule_ts: int | None = None,
    first_comment: str = "",
    hashtags: list[str] | None = None,
    store=None,
) -> dict:
    """Create (or schedule) one post. Returns the raw NovinHub post object."""
    base, token = _config(store)
    if not account_ids:
        raise NovinHubError("هیچ اکانت اینستاگرامی برای انتشار انتخاب نشده است.")
    if not media_ids and kind != "text":
        raise NovinHubError("هیچ فایلی برای انتشار آپلود نشده است.")

    body: dict = {
        "type": kind,
        "caption": caption,
        "account_ids": account_ids,
        "media_ids": media_ids,
    }
    if reels:
        body["reels"] = 1
        body["reels_sharetofeed"] = 1
    if hashtags:
        body["hashtag"] = hashtags
    if first_comment:
        body["first_comment"] = first_comment
    if schedule_ts:
        body["is_scheduled"] = 1
        body["schedule_date"] = int(schedule_ts)

    try:
        response = requests.post(
            f"{base}/post", headers=_headers(token), json=body, timeout=CALL_TIMEOUT
        )
    except requests.RequestException as exc:
        raise NovinHubError(f"ارسال پست ممکن نشد: {exc}") from exc

    data = _check(response, "ایجاد پست")
    logger.info("novinhub post created: %s", str(data)[:200])
    return data


def post_status(post_group_id, *, store=None) -> dict:
    """Where a submitted post got to — NovinHub publishes asynchronously."""
    base, token = _config(store)
    try:
        response = requests.get(
            f"{base}/post/group/{post_group_id}",
            headers=_headers(token), timeout=CALL_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise NovinHubError(f"خواندن وضعیت پست ممکن نشد: {exc}") from exc
    return _check(response, "وضعیت پست")


def post_insights(store, post_group_id) -> dict:
    """How a published post performed — views, likes, comments, saves.

    Built on `post_status`, which is the only endpoint that reports back on a
    post after it went out. The shapes NovinHub returns vary by account type,
    so the keys are searched for rather than assumed: a missing metric comes
    back absent, never as zero. Zero means "nobody engaged"; absent means "the
    platform did not say", and a shop reading the first when it should read the
    second concludes its content failed.
    """
    payload = post_status(post_group_id, store=store)

    # The numbers sit at different depths depending on the account. Flatten
    # and pick, rather than guessing one shape and silently reading nothing.
    flat: dict = {}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (int, float)) and key not in flat:
                    flat[key] = value
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)

    aliases = {
        "views": ("views", "impressions", "reach", "video_views", "play_count"),
        "likes": ("likes", "like_count", "likes_count"),
        "comments": ("comments", "comment_count", "comments_count"),
        "saves": ("saves", "saved", "save_count"),
        "shares": ("shares", "share_count", "reshares"),
    }
    result = {}
    for name, keys in aliases.items():
        for key in keys:
            if key in flat:
                result[name] = int(flat[key])
                break
    return result


def accounts(*, store=None) -> list[dict]:
    """Connected social accounts — the owner picks which to publish to."""
    base, token = _config(store)
    try:
        response = requests.get(
            f"{base}/account", headers=_headers(token), timeout=CALL_TIMEOUT
        )
    except requests.RequestException as exc:
        raise NovinHubError(f"خواندن اکانت‌ها ممکن نشد: {exc}") from exc
    data = _check(response, "فهرست اکانت‌ها")
    rows = data.get("data") if isinstance(data, dict) else data
    return rows or []


# -------------------------------------------------------------- pipeline


def publish_campaign(campaign, *, account_ids: list[int], schedule_ts=None) -> dict:
    """Upload a campaign's media and post it as one Instagram entry.

    A video campaign becomes a Reel; images become a single post or an album.
    The caption comes from the campaign's own caption row, so what the owner
    approved is exactly what goes out.
    """
    store = campaign.store
    files: list[Path] = []
    kind = "image"

    video = getattr(campaign, "video_script", None)
    if video is not None and getattr(video, "final_video", None):
        files.append(Path(video.final_video.path))
        kind = "video"
    else:
        for image in campaign.images.all():
            if image.image:
                files.append(Path(image.image.path))
        if len(files) > 1:
            kind = "album"

    if not files:
        raise NovinHubError("این کمپین هیچ فایل قابل انتشاری ندارد.")

    caption_row = campaign.captions.filter(platform="INSTAGRAM").first()
    caption = ""
    hashtags: list[str] = []
    if caption_row is not None:
        caption = caption_row.medium_text or caption_row.short_text or ""
        if caption_row.cta:
            caption = f"{caption}\n\n{caption_row.cta}".strip()
        hashtags = list(caption_row.hashtags or [])

    media_ids = [upload(path, store=store) for path in files]
    return create_post(
        account_ids=account_ids,
        media_ids=media_ids,
        caption=caption,
        kind=kind,
        reels=(kind == "video"),
        hashtags=hashtags,
        schedule_ts=schedule_ts,
        store=store,
    )


def health(*, store=None) -> tuple[bool, str]:
    """Cheap probe for the admin: is the token good and are accounts linked?"""
    try:
        rows = accounts(store=store)
    except NovinHubNotConfigured as exc:
        return False, str(exc)
    except NovinHubError as exc:
        return False, str(exc)
    if not rows:
        return False, "توکن درست است اما هیچ اکانتی به نوین‌هاب وصل نیست."
    names = ", ".join(str(r.get("username") or r.get("name") or r.get("id")) for r in rows[:5])
    return True, f"{len(rows)} اکانت متصل: {names}"
