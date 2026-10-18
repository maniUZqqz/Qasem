import uuid

from django.utils.text import slugify


def unique_slug(model_cls, name: str, *, slug_field: str = "slug") -> str:
    """Build a unicode-safe slug, guaranteed unique for the given model."""
    base = slugify(name, allow_unicode=True) or uuid.uuid4().hex[:8]
    slug = base
    while model_cls.objects.filter(**{slug_field: slug}).exists():
        slug = f"{base}-{uuid.uuid4().hex[:6]}"
    return slug


def with_tag(queryset, tag: str, field: str = "tags"):
    """Rows whose JSON list field contains `tag`, on any database.

    `tags__contains=[tag]` is the obvious spelling and it only works on
    PostgreSQL. On SQLite — which is what development runs on — it raises
    `NotSupportedError`. So the query that works in production fails on the
    machine it was written on, or worse, the other way round: written against
    SQLite with `icontains` and silently matching «سئوکار» when someone asked
    for «سئو».

    This narrows in the database with a LIKE (cheap, indexable-ish, portable)
    and then confirms exactly in Python, so the answer is the same everywhere.
    """
    tag = (tag or "").strip()
    if not tag:
        return queryset

    # Narrowed with a LIKE against **both** spellings of the tag, because
    # Django writes JSON with `ensure_ascii=True`: SQLite stores «سئو» as
    # `["سئو"]`, so a LIKE for the Persian text matches
    # nothing there, while PostgreSQL's jsonb::text gives the readable form and
    # a LIKE for the escaped one matches nothing. Trying both covers each.
    import json

    from django.db.models import Q

    escaped = json.dumps(tag)[1:-1]
    narrowed = queryset.filter(
        Q(**{f"{field}__icontains": tag}) | Q(**{f"{field}__icontains": escaped})
    )

    # Confirmed exactly in Python, so «سئو» never matches «سئوکار». The LIKE is
    # only there to keep this from reading the whole table; correctness is
    # decided here.
    exact = [
        row.pk for row in narrowed
        if tag in [str(t).strip() for t in (getattr(row, field, None) or [])]
    ]
    return queryset.filter(pk__in=exact)
