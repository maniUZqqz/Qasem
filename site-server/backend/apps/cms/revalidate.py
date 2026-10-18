"""Telling the public website that something it shows has changed.

The site caches each page's data for a couple of minutes (website/lib/api.ts),
which is what makes it fast. The cost is that an edit in the Django admin
appears up to two minutes later — and someone who saves, switches tab and
refreshes sees the old text and concludes the site is not reading the database
at all. That is not a cache tuning problem; it is the difference between a
tool that looks broken and one that does not.

So every save here pings the site's revalidate endpoint with the tags that
changed, and the next visitor gets fresh HTML. The time window stays exactly
as it was, as the backstop for anything that misses the ping — a restart mid
edit, the site being down, a model nobody wired up yet.

Three rules this follows, all of them learned the hard way:

**A failed ping never fails a save.** The website being down must not stop the
shop editing its own blog. Everything here swallows its errors into the log.

**It runs after the transaction commits.** Pinging inside the transaction
tells the site to re-read a row that is not visible yet, and it re-caches the
old value — the exact bug this is meant to fix, now harder to see.

**It runs off the request thread.** A save in the admin must not wait on an
HTTP call to another service; two seconds of someone else's timeout on every
"Save" is how people stop using an admin.
"""
from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

#: How long to wait for the website. Short: nothing depends on the answer.
TIMEOUT_SECONDS = 5


def _endpoint() -> str:
    """Where the site listens, or "" when this is not wired up."""
    base = (settings.UPMARKET_AI.get("WEBSITE_URL") or "").strip().rstrip("/")
    return f"{base}/api/revalidate" if base else ""


def _post(url: str, secret: str, tags: list[str]) -> None:
    import requests

    try:
        response = requests.post(
            url,
            json={"tags": tags},
            headers={"x-revalidate-secret": secret},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            logger.warning(
                "The website refused the refresh (%s): %s",
                response.status_code, response.text[:200],
            )
        else:
            logger.info("Website refreshed: %s", ", ".join(tags))
    except Exception as exc:  # noqa: BLE001 — never break a save
        logger.info("Could not tell the website about %s: %s", ", ".join(tags), exc)


def ping(*tags: str) -> None:
    """Ask the website to drop its cache for these subjects, after commit."""
    wanted = sorted({t for t in tags if t})
    if not wanted:
        return
    url = _endpoint()
    secret = (settings.UPMARKET_AI.get("WEBSITE_REVALIDATE_SECRET") or "").strip()
    if not url or not secret:
        # Not configured — the site still catches up within its own window,
        # so this is a note in the log rather than a warning in anyone's face.
        logger.debug("Website refresh skipped: WEBSITE_URL/secret not set")
        return

    def later():
        threading.Thread(
            target=_post, args=(url, secret, wanted), daemon=True
        ).start()

    transaction.on_commit(later)
