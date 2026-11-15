"""همهٔ ایده‌های آمادهٔ بانکِ ایده در یک dictِ فقط‌خواندنی (کلید ⇒ ایده). نوشته‌شده در فایل‌های ``seeds_*.py``.

۹۹ ایدهٔ فارسی در ۸ دسته. هیچ‌کدام عدد، قیمت، آمار، نتیجه یا نقلِ قولِ ساختگی ندارند (آزمونِ ``tests_seeds``)."""
from __future__ import annotations

from .seeds_content import BEHIND, TIPS
from .seeds_occasion import OCCASION
from .seeds_sell import OFFER, PRODUCT
from .seeds_talk import ENGAGE, FAQ, PROOF

_ALL = [*TIPS, *BEHIND, *PRODUCT, *FAQ, *PROOF, *OCCASION, *ENGAGE, *OFFER]
BUILTIN_IDEAS: dict[str, dict] = dict(_ALL)
assert len(BUILTIN_IDEAS) == len(_ALL), "کلیدِ ایده‌های آماده یکتا نیست"
