# -*- coding: utf-8 -*-
"""دادهٔ «ui-ux-pro-max-skill» (MIT، Next Level Builder): سبک‌ها، پالت‌ها، جفتِ قلم‌ها و رهنمودهای UX — جست‌وجوپذیر.

فایلِ dataset/uiux_pro_max.json را import_uiux.py از مخزنِ اصلی ساخته (مجوز و نشانیِ مخزن کنارش است).
این‌جا فقط خواندن و جست‌وجوی ساده (امتیازِ کلمه‌های مشترک) هست؛ چیزی از اینترنت نمی‌آید.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, 'dataset', 'uiux_pro_max.json')
KINDS = ('styles', 'colors', 'fonts', 'ux', 'landing', 'motion')
_cache = {}


def data():
    if 'd' not in _cache:
        try:
            with open(DATA_PATH, encoding='utf-8') as fh:
                _cache['d'] = json.load(fh)
        except (OSError, ValueError):
            _cache['d'] = {k: [] for k in KINDS}
    return _cache['d']


def attribution():
    d = data()
    return {'source': d.get('source', ''), 'license': d.get('license', ''), 'copyright': d.get('copyright', ''), 'commit': d.get('commit', ''),
            'retrieved': d.get('retrieved', ''), 'counts': {k: len(d.get(k, [])) for k in KINDS}}


def _words(text):
    return [w for w in re.split(r'[^\w؀-ۿ]+', (text or '').lower()) if len(w) > 1]


def _score(row, q_words, fields):
    hay = ' '.join(str(row.get(f, '')) for f in fields).lower()
    if not hay:
        return 0
    score = 0
    for w in q_words:
        if w in hay:
            score += 3 if w in str(row.get(fields[0], '')).lower() else 1
    return score


SEARCH_FIELDS = {
    'styles': ('name', 'keywords', 'best_for', 'effects', 'id'),
    'colors': ('product', 'notes'),
    'fonts': ('name', 'mood', 'best_for', 'category', 'heading', 'body'),
    'ux': ('issue', 'category', 'description'),
    'landing': ('name', 'keywords', 'sections'),
    'motion': ('category', 'keywords'),
}


def search(kind, query, limit=8):
    """⇒ ردیف‌های مرتبط‌ترین؛ کلمه‌های فارسی هم برای جست‌وجوی نامِ فارسیِ سبک‌های خودمان در styles.find_by_text است."""
    if kind not in SEARCH_FIELDS:
        return []
    words = _words(query)
    rows = data().get(kind, [])
    if not words:
        return rows[:limit]
    scored = [(_score(r, words, SEARCH_FIELDS[kind]), i, r) for i, r in enumerate(rows)]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [r for _s, _i, r in scored[:limit]]


def by_id(kind, key, value):
    for r in data().get(kind, []):
        if str(r.get(key, '')).lower() == str(value).lower():
            return r
    return None


def reference_for(style):
    """سطرهای مرجعِ یک سبکِ ما در دادهٔ ui-ux-pro-max (برای نمایش و پرامپت)."""
    ref = style.get('uiux') or {}
    return {'style': by_id('styles', 'id', ref.get('style_id', '')), 'font_pairing': by_id('fonts', 'name', ref.get('font_pairing', '')),
            'palette': by_id('colors', 'product', ref.get('palette', ''))}


__all__ = ['data', 'search', 'attribution', 'by_id', 'reference_for', 'KINDS']
