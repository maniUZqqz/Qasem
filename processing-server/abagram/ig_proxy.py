"""Showing Instagram's pictures and videos inside our own page. Instagram's picture host answers with
`Cross-Origin-Resource-Policy: same-origin`, so a browser refuses to show them on any other site (the people lists
showed only letters). The local server fetches them instead: pictures once, then from a cache on disk (so they keep
working after their address expires); videos are streamed through with the browser's Range header (no caching).
Only Instagram's own hosts are allowed (and the test site)."""
import asyncio
import hashlib
from pathlib import Path

import httpx

import ig_prefs
import ig_profile as pr
from ig_common import BASE
from ig_store import sniff_image

AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
IMAGE_MAX = 12 * 1024 * 1024
_client, _via = None, None


def client():
    """One shared pool, through his saved proxy (Instagram's hosts are filtered in Iran); rebuilt when he changes it."""
    global _client, _via
    via = ig_prefs.load()["proxy"] or None
    if _client is None or via != _via:
        opts = dict(follow_redirects=True, timeout=httpx.Timeout(20.0, read=60.0),
                    headers={"User-Agent": AGENT, "Accept": "*/*", "Referer": BASE + "/"},
                    limits=httpx.Limits(max_connections=12, max_keepalive_connections=6))
        try:
            _client = httpx.AsyncClient(proxy=via, **opts)
        except Exception:   # for example a socks5 proxy without the optional package: go direct rather than show nothing
            _client = httpx.AsyncClient(**opts)
        _via = via
    return _client


def allowed(url):
    return isinstance(url, str) and url.startswith(("https://", "http://")) and pr.safe_image_url(url, BASE)


class ImageCache:
    def __init__(self, root):
        self.dir = Path(root) / "cache" / "img"
        self._inflight = {}     # url -> task, so a picture shown twice at once is fetched once

    def path(self, url):
        return self.dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img")

    async def get(self, url):
        """(path, content type) of the picture, fetched once; None when Instagram no longer serves it or it is not a picture."""
        task = self._inflight.get(url)
        if task is None:
            task = self._inflight[url] = asyncio.ensure_future(self._get(url))
            task.add_done_callback(lambda _t: self._inflight.pop(url, None))
        return await asyncio.shield(task)

    async def _get(self, url):
        path = self.path(url)
        if path.is_file():
            with open(path, "rb") as f:
                kind = sniff_image(f.read(16))
            if kind:
                return path, kind
        try:
            r = await client().get(url)
        except httpx.HTTPError:
            return None
        data = r.content
        kind = sniff_image(data[:16])
        if r.status_code != 200 or not kind or len(data) > IMAGE_MAX:
            return None
        pr.write_atomic(path, data)
        return path, kind


async def open_video(url, range_header=None):
    """A streaming response from Instagram's video host (status, headers, the open response) or None."""
    headers = {"Range": range_header} if range_header else {}
    try:
        req = client().build_request("GET", url, headers=headers)
        r = await client().send(req, stream=True)
    except httpx.HTTPError:
        return None
    if r.status_code not in (200, 206) or not (r.headers.get("content-type") or "").startswith(("video/", "application/octet-stream")):
        await r.aclose()
        return None
    keep = {k: r.headers[k] for k in ("content-type", "content-length", "content-range", "accept-ranges") if k in r.headers}
    return r.status_code, keep, r
