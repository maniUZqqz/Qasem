"""JSON rendering that never answers a request with an empty body."""
from rest_framework.renderers import JSONRenderer

# Responses that must NOT carry a body, per HTTP.
BODYLESS_STATUSES = {204, 304}


class NullableJSONRenderer(JSONRenderer):
    """Render `Response(None)` as the JSON literal `null`, not as zero bytes.

    Several endpoints answer "nothing generated yet" with `Response(None)` —
    intelligence, market analysis, video script — because a 404 for a normal
    empty state painted the browser console red on every product page load
    (beter.md #10). But DRF's JSONRenderer turns `None` into an EMPTY body, so
    those endpoints replied `200` with zero bytes: not valid JSON, impossible
    to `JSON.parse`, and axios hands the caller `""` instead of `null`. Any
    client stricter than the current UI breaks on it.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            response = (renderer_context or {}).get("response")
            status_code = getattr(response, "status_code", 200)
            if status_code in BODYLESS_STATUSES or status_code < 200:
                return b""
            return b"null"
        return super().render(data, accepted_media_type, renderer_context)
