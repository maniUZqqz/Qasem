"""تولید PDF برنامه ورزشی و غذایی — چیدمان ستونی.

قواعد چیدمان (ثابت و غیرقابل مذاکره، چون خروجی چاپی است):

* هیچ جدول اطلاعات فردی در ابتدای PDF وجود ندارد.
* برنامه ورزشی: هر صفحه ۳ ستون عمودی، هر ستون یک جلسه کامل. حداکثر ۲ صفحه.
* برنامه غذایی: کادرهای سرتاسری زیر هم، هر کادر یک روز کامل و هر وعده یک
  ردیف (نام وعده در ستون راست، اقلامش در ستون چپ). دو روز در هر صفحه،
  حداکثر ۴ صفحه.
* برنامه ورزشی و غذایی هرگز در یک صفحه نمی‌آیند.
* یک جلسه یا یک روز هرگز بین دو صفحه نصف نمی‌شود.
* بالای هر صفحه یک سطر بسیار ریز: نام ورزشکار، نوع برنامه، تعداد روز، تاریخ.
* پایین وسط هر صفحه بسیار ریز: «هوش مصنوعی ممکن است اشتباه کند».

ساختار ورودی از خروجی مدل می‌آید (`### جلسه ۱` / `### روز ۱` / جداکننده `---`).
اگر برنامه‌ای با قالب قدیمی ذخیره شده باشد، به چیدمان جریانی چندستونی
برمی‌گردد تا برنامه‌های قبلی هم بدون خطا PDF بدهند.
"""

import base64
import io
import logging
import math
import mimetypes
import os
import re
from functools import lru_cache
from html import escape

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    logger.warning("WeasyPrint is not available. Will fallback to ReportLab PDF.")


from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepInFrame, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
from reportlab.lib import colors
import arabic_reshaper
from bidi.algorithm import get_display


# ---------------------------------------------------------------------------
# پالت رنگی — هماهنگ با تم لندینگ (آبی روشن / سفید)
# ---------------------------------------------------------------------------
COLOR_INK = '#163F75'        # آبی سرمه‌ای — عنوان‌ها
COLOR_ACCENT = '#126F85'     # فیروزه‌ای — شماره جلسه/روز
COLOR_TINT = '#DBE6FF'       # آبی روشن — پس‌زمینه سربرگ ستون
COLOR_BODY = '#1f2937'       # متن اصلی
COLOR_MUTED = '#6b7a90'      # متن‌های ریز سربرگ/پاورقی
COLOR_RULE = '#c9d8f2'       # خط جداکننده نازک
COLOR_NOTE_BG = '#F5F9FF'    # پس‌زمینه‌ی بسیار روشن کادر استراتژی و مکمل‌ها

DISCLAIMER_TEXT = 'هوش مصنوعی ممکن است اشتباه کند'
COACH_NOTE_TEXT = 'نکات و نوع اجرای حرکات با مربی متخصص هماهنگ شود'
# برنامهٔ دستی را خودِ مربیِ متخصص نوشته است؛ پس نه هشدارِ هوش مصنوعی معنا
# دارد و نه توصیهٔ «با مربی هماهنگ کن». جایش فقط یادآوریِ کوتاهِ پزشکی.
MANUAL_NOTE_TEXT = 'برنامهٔ اختصاصیِ شما، نوشتهٔ مربیِ شما'


# ---------------------------------------------------------------------------
# اندازه‌ها و فاصله‌های چیدمان
# ---------------------------------------------------------------------------
# همه در یک جا جمع‌اند چون خروجی چاپی است: تغییر یکی بدون دیدن بقیه، تناسب
# صفحه را به هم می‌زند. هر دو موتور (WeasyPrint و ReportLab) از همین اعداد
# می‌خوانند تا خروجی سرورهای مختلف شبیه هم بماند.

# سربرگ صفحه: لوگوها دو طرف، مشخصات ورزشکار وسط. ارتفاع لوگو تعیین می‌کند
# حاشیه‌ی بالا چقدر باشد، وگرنه لوگو روی محتوا می‌افتد.
LOGO_HEIGHT_MM = 13
LOGO_MAX_WIDTH_MM = 30
PAGE_MARGIN_TOP_MM = 28
PAGE_MARGIN_SIDE_MM = 11
PAGE_MARGIN_BOTTOM_MM = 16

# فاصله‌ی سطر مشخصات تا شروع محتوا — روی همه‌ی صفحه‌ها، نه فقط صفحه‌ای که
# کادر استراتژی دارد؛ وگرنه کادر «روز ۵» در صفحه‌ی سوم به سربرگ می‌چسبد.
HEADER_GAP_BELOW_MM = 9

HEADER_FONT_PT = 11.5        # نام ورزشکار · نوع برنامه · تعداد روز · تاریخ
COACH_NOTE_FONT_PT = 9       # اخطار هماهنگی با مربی
DISCLAIMER_FONT_PT = 8       # یادآوری خطای هوش مصنوعی

# کادر استراتژی/استراحت — و کادر هم‌شکلش برای مکمل‌ها
NOTE_FONT_PT = 11            # هم‌اندازه‌ی متن بدنه‌ی یک سند A4
NOTE_PAD_X_MM = 5
NOTE_PAD_Y_MM = 4.5
NOTE_LINE_GAP_MM = 3         # فاصله‌ی استراتژی تا استراحت، داخل همان کادر
NOTE_TOP_GAP_MM = 4          # فاصله‌ی کادر از بالای صفحه
NOTE_BOTTOM_GAP_MM = 5.5     # فاصله‌ی کادر تا ستون‌های جلسه

# ستون‌های جلسه‌ی ورزشی
COLUMN_GAP_MM = 5            # فاصله‌ی افقی کادرها از هم
COLUMN_PAD_X_MM = 4          # فاصله‌ی متن از کناره‌های کادر
COLUMN_PAD_Y_MM = 4.5        # فاصله‌ی متن از بالا و پایین کادر
COLUMN_HEAD_PAD_MM = 2.8

# کادرهای روز غذایی — سرتاسری و زیر هم، با تنفس بیشتر.
# هر وعده یک ردیف است: نام وعده در ستون باریکِ راست، اقلامش در ستون پهن چپ.
MEAL_BOX_GAP_MM = 5
MEAL_PAD_X_MM = 6
MEAL_PAD_Y_MM = 8
MEAL_LABEL_WIDTH_MM = 30     # ستون نام وعده
MEAL_ROW_PAD_PT = 5          # فاصله‌ی بالا و پایین هر ردیف وعده

# ---------------------------------------------------------------------------
# واترمارک لوگوی برند
# ---------------------------------------------------------------------------
# فایل PNG سیاه‌وسفید با پس‌زمینه‌ی شفاف است و آلفای خودش از قبل خیلی کم
# گذاشته شده. عمداً از opacity در CSS استفاده نمی‌کنیم: opacity روی عنصر،
# متن روی آن را هم کم‌رنگ می‌کند؛ آلفای داخل خود تصویر فقط خود لوگو را
# کم‌رنگ می‌کند و محتوای اصلی دست‌نخورده می‌ماند.
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
WATERMARK_FILE = os.path.join(_ASSETS_DIR, 'chegher_watermark.png')
LOGO_FILE = os.path.join(_ASSETS_DIR, 'chegher_logo.png')

# اندازه‌ی واترمارک نسبت به عرض صفحه — به‌اندازه‌ای بزرگ که دیده شود،
# نه آن‌قدر که با ستون‌ها رقابت کند.
WATERMARK_WIDTH_MM = 120


@lru_cache(maxsize=1)
def _watermark_data_uri():
    """واترمارک را یک بار می‌خواند و به data URI تبدیل می‌کند.

    اگر فایل نبود، رشته‌ی خالی برمی‌گردد و PDF بدون واترمارک ساخته می‌شود؛
    نبودِ یک تصویر تزئینی نباید تولید برنامه را بشکند.
    """
    try:
        with open(WATERMARK_FILE, 'rb') as handle:
            encoded = base64.b64encode(handle.read()).decode('ascii')
        return f'data:image/png;base64,{encoded}'
    except OSError:
        logger.warning('Watermark file is missing: %s', WATERMARK_FILE)
        return ''


def _image_data_uri(path):
    """هر تصویری را به data URI تبدیل می‌کند تا داخل HTML جاسازی شود.

    نبودن یا خراب‌بودن یک لوگو نباید تولید برنامه را بشکند؛ در آن صورت
    رشته‌ی خالی برمی‌گردد و آن لوگو ساده چاپ نمی‌شود.
    """
    if not path:
        return ''
    try:
        with open(path, 'rb') as handle:
            encoded = base64.b64encode(handle.read()).decode('ascii')
    except OSError:
        logger.warning('Logo file could not be read: %s', path)
        return ''
    mime = mimetypes.guess_type(path)[0] or 'image/png'
    return f'data:{mime};base64,{encoded}'


@lru_cache(maxsize=1)
def _platform_logo_data_uri():
    """لوگوی ثابت خودمان — یک بار خوانده و کش می‌شود."""
    return _image_data_uri(LOGO_FILE)


def _gym_brand(client_obj):
    """برند باشگاهی که این برنامه به آن تعلق دارد (اگر وجود داشته باشد).

    دو حالت ممکن است: برنامه را مربی برای شاگردش ساخته (برند خودِ مربی) یا
    ورزشکار با اکانت خودش ساخته (برند باشگاهی که به آن متصل است). برنامه‌ی
    کاربر شخصی به هیچ باشگاهی وصل نیست و فقط لوگوی ما را می‌گیرد.

    رابطه‌ی یک‌به‌یکِ بدون رکورد، `RelatedObjectDoesNotExist` می‌دهد که
    زیرکلاس `AttributeError` است؛ پس `getattr` با مقدار پیش‌فرض خودش آن را
    می‌گیرد و نیازی به import مدل‌های اپ اینجا نیست.
    """
    user = getattr(client_obj, 'user', None)
    if user is None:
        return None

    brand = getattr(user, 'gym_brand', None)
    if brand is not None:
        return brand

    try:
        membership = user.client_profile.first()
    except Exception:
        return None
    if membership is None:
        return None
    return getattr(getattr(membership, 'gym_owner', None), 'gym_brand', None)


def _gym_logo_path(client_obj):
    """مسیر فایل لوگوی باشگاه، اگر مربی لوگو آپلود کرده باشد."""
    logo = getattr(_gym_brand(client_obj), 'logo', None)
    if not logo:
        return ''
    try:
        path = logo.path
    except Exception:
        # ذخیره‌سازی ابری یا فایل جابه‌جاشده — لوگو را بی‌خیال می‌شویم
        return ''
    return path if path and os.path.exists(path) else ''


# سقف صفحه و تعداد کادر برای هر بخش
WORKOUT_MAX_PAGES = 2
WORKOUT_COLS_PER_PAGE = 3
# یک روز واقعی شش هفت وعده دارد و در کادر سرتاسری حدود نصف صفحه می‌گیرد،
# پس دو روز در هر صفحه. هفت روز یعنی چهار صفحه — سقف قبلی (سه صفحه) مربوط
# به چیدمان دوستونی بود و با کادر سرتاسری متن را به اندازه‌ی ناخوانا کوچک
# می‌کرد.
MEAL_MAX_PAGES = 4
# برنامه غذایی ستون کنار هم ندارد: کادرهای سرتاسری زیر هم می‌نشینند و این
# عدد یعنی «چند کادر در هر صفحه».
MEAL_BOXES_PER_PAGE = 2


# ---------------------------------------------------------------------------
# تاریخ شمسی
# ---------------------------------------------------------------------------

def _to_jalali(gy, gm, gd):
    """تبدیل تاریخ میلادی به شمسی (بدون وابستگی خارجی)."""
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    yy = gy - 1600
    g_day_no = 365 * yy + (yy + 3) // 4 - (yy + 99) // 100 + (yy + 399) // 400
    for i in range(gm - 1):
        g_day_no += g_days_in_month[i]
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    g_day_no += gd - 1

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            return jy, i + 1, j_day_no + 1
        j_day_no -= j_days_in_month[i]
    return jy, 12, j_day_no + 1


def _format_date_fa(dt):
    """تاریخ شمسی کوتاه برای سربرگ PDF."""
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    jy, jm, jd = _to_jalali(dt.year, dt.month, dt.day)
    return f"{jy}/{jm:02d}/{jd:02d}"


# ---------------------------------------------------------------------------
# پارسر خروجی مدل
# ---------------------------------------------------------------------------

# ارقام فارسی/عربی به لاتین — برای تشخیص شماره جلسه و روز
_DIGIT_MAP = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

_SESSION_RE = re.compile(r'^#{1,6}\s*جلسه\s*[:\-]?\s*(\d+)?\s*$')
_DAY_RE = re.compile(r'^#{1,6}\s*روز\s*[:\-]?\s*(\d+)?\s*$')
_SUPPLEMENT_RE = re.compile(r'^#{1,6}\s*(مکمل|مکمل‌ها|مکمل ها|ویتامین)')
_SECTION_RE = re.compile(r'^#{1,6}\s*برنامه\s*(ورزشی|غذایی)')
_RULE_RE = re.compile(r'^\s*(?:-{3,}|\*{3,}|_{3,})\s*$')
_NUMBERED_RE = re.compile(r'^(\d+)[.)]\s*(.+)$')


# --- اصلاح جهت «ست × تکرار» ---
# در یک پاراگراف راست‌به‌چپ، علامت × یک نویسه خنثی است و الگوریتم دوسویه
# یونیکد دو عدد کنارش را جدا می‌کند؛ نتیجه این است که «۴×۸» وارونه و به شکل
# «۸×۴» چاپ می‌شود — یعنی تعداد ست و تکرار جای هم عوض می‌شوند. برای جلوگیری،
# این نشانه را داخل یک جاسازی صریح چپ‌به‌راست می‌گذاریم. هم WeasyPrint و هم
# python-bidi این دو نویسه کنترلی را پشتیبانی می‌کنند (برخلاف isolate‌های جدید
# که در python-bidi خطا می‌دهند).
# U+202A / U+202C به‌صورت chr نوشته می‌شوند، نه نویسه‌ی خام:
# نویسه‌ی نامرئی در سورس هم در بازبینی دیده نمی‌شود و هم ممکن است در
# ویرایش یا copy/paste حذف شود و این محافظ را بی‌صدا از کار بیندازد.
_LRE = chr(0x202A)       # LEFT-TO-RIGHT EMBEDDING
_PDF_MARK = chr(0x202C)  # POP DIRECTIONAL FORMATTING

_DIGITS = r'0-9۰-۹٠-٩'
# هر طرف علامت × می‌تواند یک عدد یا یک بازه باشد («۳×۸-۱۰» یا «۲-۳×۱۰»).
# بازه فقط با خط تیره‌ی کوتاه یا en-dash شناخته می‌شود، نه em-dash — چون
# em-dash همان جداکننده‌ی نام حرکت از ست/تکرار است و اگر وارد الگو شود،
# نصف عنوان حرکت هم داخل جاسازی می‌افتد.
_NUMBER_OR_RANGE = rf'[{_DIGITS}]+(?:\s*[-–]\s*[{_DIGITS}]+)?'
_SETS_REPS_RE = re.compile(
    rf'({_NUMBER_OR_RANGE})\s*([×xX*])\s*({_NUMBER_OR_RANGE})'
)


def _protect_sets_reps(text):
    """«ست × تکرار» را در جاسازی چپ‌به‌راست می‌پیچد تا وارونه چاپ نشود.

    بازه‌ی تکرار هم باید **کامل** داخل جاسازی بیفتد. اگر فقط «۳×۸» پوشیده
    شود و «-۱۰» بیرون بماند، الگوریتم دوسویه آن تکه را جدا جابه‌جا می‌کند و
    ورزشکار عدد اشتباه می‌خواند.
    """
    if not text:
        return text
    # ابتدا جاسازی‌های قبلی برداشته می‌شوند تا اعمال دوباره، تودرتو نسازد
    stripped = text.replace(_LRE, '').replace(_PDF_MARK, '')
    return _SETS_REPS_RE.sub(
        lambda m: f"{_LRE}{m.group(1)}{m.group(2)}{m.group(3)}{_PDF_MARK}",
        stripped,
    )


def _clean_inline(text):
    """پاک‌سازی نشانه‌های مارک‌داون درون‌خطی، با حفظ متن."""
    txt = (text or '').strip()
    txt = re.sub(r'`([^`]+)`', r'\1', txt)
    txt = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', txt)
    txt = txt.replace('**', '').replace('__', '')
    txt = re.sub(r'(?<!\*)\*(?!\*)', '', txt)
    return _protect_sets_reps(txt.strip())


def _strip_code_fences(text):
    """اگر مدل کل خروجی را داخل ``` گذاشته باشد، حصار را بردار."""
    lines = []
    for line in (text or '').splitlines():
        if line.strip().startswith('```'):
            continue
        lines.append(line)
    return '\n'.join(lines)


def _normalize_digits(text):
    return (text or '').translate(_DIGIT_MAP)


# ارقام لاتین → فارسی، برای اقلامی که خودمان تولید می‌کنیم (شماره جلسه/روز،
# تعداد روز، تاریخ). متن بدنه از مدل می‌آید و خودش فارسی است؛ بدون این تبدیل،
# سربرگ «4 روز» کنار بدنه‌ی «۳×۱۲» می‌نشیند و سند دورگه به نظر می‌رسد.
_FA_DIGIT_MAP = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def _fa_digits(value):
    return str(value).translate(_FA_DIGIT_MAP)


def parse_workout(md_text):
    """برنامه ورزشی را به سربرگ + فهرست جلسات تبدیل می‌کند.

    خروجی: (intro_lines, sessions)
      sessions = [{'number': 1, 'blocks': [[line, ...], [line, ...]]}]
      هر block یک گروه حرکتی است که با `---` از گروه بعدی جدا شده.
    """
    text = _strip_code_fences(md_text or '')
    intro = []
    sessions = []
    current = None

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        normalized = _normalize_digits(stripped)

        if _SECTION_RE.match(normalized):
            continue

        match = _SESSION_RE.match(normalized)
        if match:
            number = int(match.group(1)) if match.group(1) else len(sessions) + 1
            current = {'number': number, 'blocks': [[]]}
            sessions.append(current)
            continue

        if current is None:
            cleaned = _clean_inline(stripped)
            if cleaned and not _RULE_RE.match(stripped):
                intro.append(cleaned)
            continue

        if _RULE_RE.match(stripped):
            # جداکننده گروه عضلانی — بلوک جدید، فقط اگر بلوک فعلی خالی نباشد
            if current['blocks'][-1]:
                current['blocks'].append([])
            continue

        cleaned = _clean_inline(stripped)
        if cleaned:
            current['blocks'][-1].append(cleaned)

    for session in sessions:
        session['blocks'] = [block for block in session['blocks'] if block]

    return intro, [s for s in sessions if s['blocks']]


def _is_meal_label(line):
    """آیا این سطر فقط عنوان یک وعده است و قلمی روبه‌رویش ندارد؟

    عنوان وعده گاهی زمان هم دارد — «قبل از تمرین (۹۰ دقیقه مانده):» — پس
    سقف طول باید جای پرانتز را هم بدهد، وگرنه آن وعده عنوان شمرده نمی‌شود و
    اقلامش به وعده‌ی قبلی می‌چسبد.
    """
    text = (line or '').strip()
    return text.endswith(':') and len(text) <= 44


def _split_meal_label(label):
    """عنوان وعده را از توضیح زمانی داخل پرانتزش جدا می‌کند.

    «قبل از تمرین (۹۰ دقیقه مانده)» → («قبل از تمرین»، «(۹۰ دقیقه مانده)»)
    تا ستون باریکِ نام وعده کوتاه بماند و زمان کنار اقلام بنشیند؛ همان‌طور
    که مربی می‌نویسد.
    """
    match = re.match(r'^(.*?)\s*(\([^)]*\))\s*$', label or '')
    if match and match.group(1).strip():
        return match.group(1).strip(), match.group(2).strip()
    return (label or '').strip(), ''


def group_meal_rows(lines):
    """سطرهای یک روز غذایی را به ردیف‌های «وعده / اقلام» تبدیل می‌کند.

    مدل هر قلم غذا را در یک سطر جدا می‌نویسد، یعنی یک روز بیست‌وچند سطر
    می‌شود. مربی واقعی برنامه را این‌طور نمی‌نویسد: هر وعده یک ردیف است و
    اقلامش کنار هم. همان کار اینجا انجام می‌شود — هم خواناتر است و هم روز
    را از بیست‌وچند سطر به شش هفت ردیف می‌رساند تا در صفحه جا شود.

    خروجی: [{'label': str|None, 'text': str}]
    """
    rows = []
    current = None

    for raw in lines:
        line = (raw or '').strip()
        if not line:
            continue

        if _is_meal_label(line):
            label, timing = _split_meal_label(line.rstrip(':').strip())
            current = {'label': label, 'prefix': timing, 'items': []}
            rows.append(current)
            continue

        label, sep, rest = line.partition(':')
        if sep and rest.strip() and len(label.strip()) <= 24:
            # سطر خودکفا مثل «جمع روز ۱: کالری ...» — ردیف مستقل خودش
            current = None
            rows.append({'label': label.strip(), 'prefix': '',
                         'items': [rest.strip()]})
            continue

        if current is None:
            current = {'label': None, 'prefix': '', 'items': []}
            rows.append(current)
        current['items'].append(line)

    grouped = []
    for row in rows:
        if not (row['items'] or row['label']):
            continue
        text = '، '.join(row['items'])
        if row.get('prefix'):
            text = f"{row['prefix']} {text}".strip()
        grouped.append({'label': row['label'], 'text': text})
    return grouped


# تخمین تعداد نویسه‌ای که با قلم ۱۱ در عرض مفید یک کادر سرتاسری جا می‌شود
_MEAL_CHARS_PER_LINE = 72


def _meal_rows_line_estimate(day):
    """چند سطر بصری لازم است تا ردیف‌های این روز چاپ شوند؟"""
    total = 0
    for row in group_meal_rows(day['lines']):
        total += max(1, math.ceil(len(row['text']) / _MEAL_CHARS_PER_LINE))
    return total


def parse_meal(md_text):
    """برنامه غذایی را به خلاصه + روزها + مکمل‌ها تبدیل می‌کند.

    خروجی: (summary_lines, days, supplement_lines)
      days = [{'number': 1, 'lines': [line, ...]}]
    """
    text = _strip_code_fences(md_text or '')
    summary = []
    days = []
    supplements = []
    current = None
    in_supplements = False

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        normalized = _normalize_digits(stripped)

        if _SECTION_RE.match(normalized):
            continue

        if _SUPPLEMENT_RE.match(normalized):
            in_supplements = True
            current = None
            continue

        match = _DAY_RE.match(normalized)
        if match:
            in_supplements = False
            number = int(match.group(1)) if match.group(1) else len(days) + 1
            current = {'number': number, 'lines': []}
            days.append(current)
            continue

        if _RULE_RE.match(stripped):
            continue

        cleaned = _clean_inline(stripped)
        if not cleaned:
            continue

        if in_supplements:
            supplements.append(cleaned)
        elif current is None:
            summary.append(cleaned)
        else:
            current['lines'].append(cleaned)

    return summary, [d for d in days if d['lines']], supplements


_HEADING_RE = re.compile(r'^#{1,6}\s*(.+?)\s*$')


def parse_meal_sections(md_text):
    """برنامهٔ غذاییِ **دستی** ⇒ [{'title': ..., 'lines': [...]}] و مکمل‌ها.

    چرا جدا از parse_meal: آن یکی دنبالِ «روز ۱، روز ۲» می‌گردد چون برنامهٔ
    هوش مصنوعی روزمحور است. برنامهٔ دستی تیترِ آزاد دارد («صبحانه»، «میان‌وعدهٔ
    قبل تمرین») و هیچ روزی ندارد، برای همین به مسیرِ «متنِ ساده» می‌افتاد و
    بی‌کادر چاپ می‌شد — همان چیزی که مالک دید.
    """
    text = _strip_code_fences(md_text or '')
    sections = []
    supplements = []
    current = None
    in_supplements = False

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        normalized = _normalize_digits(stripped)

        heading = _HEADING_RE.match(normalized)
        if heading:
            if _SUPPLEMENT_RE.match(normalized):
                in_supplements = True
                current = None
                continue
            in_supplements = False
            current = {'title': _clean_inline(heading.group(1)), 'lines': []}
            sections.append(current)
            continue

        if _RULE_RE.match(stripped):
            continue
        cleaned = _clean_inline(stripped)
        if not cleaned:
            continue

        if in_supplements:
            supplements.append(cleaned)
        elif current is not None:
            current['lines'].append(cleaned)
        else:
            current = {'title': '', 'lines': [cleaned]}
            sections.append(current)

    return [x for x in sections if x['lines']], supplements


def _chunk_columns(items, cols_per_page, max_pages):
    """آیتم‌ها را به صفحه‌ها تقسیم می‌کند بدون اینکه از سقف صفحه رد شود.

    دو قاعده:

    ۱. تعداد صفحه‌ها هیچ‌وقت از `max_pages` بیشتر نمی‌شود؛ اگر آیتم‌ها زیاد
       باشند، ستون‌های بیشتری در یک صفحه فشرده می‌شوند تا هیچ جلسه/روزی
       حذف نشود.
    ۲. آیتم‌ها بین همان تعداد صفحه **متوازن** پخش می‌شوند، نه اینکه صفحه‌ی
       اول پر و صفحه‌ی آخر با یک ستون تنها بماند. ۴ جلسه به شکل ۲+۲ چاپ
       می‌شود، نه ۳+۱؛ یک ستون تنها در عرض کامل صفحه کشیده می‌شد و خروجی
       چاپی را نامتوازن نشان می‌داد.
    """
    if not items:
        return []

    pages_needed = min(math.ceil(len(items) / cols_per_page), max_pages)
    per_page = math.ceil(len(items) / pages_needed)

    return [items[i:i + per_page] for i in range(0, len(items), per_page)]


def _has_structured_workout(sessions):
    return len(sessions) > 0


def _has_structured_meal(days):
    return len(days) > 0


# ---------------------------------------------------------------------------
# اطلاعات سربرگ
# ---------------------------------------------------------------------------

_PROGRAM_TYPE_LABELS = {
    'both': 'برنامه ورزشی و غذایی',
    'workout': 'برنامه ورزشی',
    'meal': 'برنامه غذایی',
}


def _header_info(client_obj, section):
    """چهار قلم اطلاعات سربرگ: نام، نوع برنامه، تعداد روز، تاریخ."""
    return {
        'name': (client_obj.name or '').strip() or 'ورزشکار',
        'type': _PROGRAM_TYPE_LABELS.get(section, 'برنامه'),
        'days': f"{_fa_digits(client_obj.program_days)} روز",
        'date': _fa_digits(_format_date_fa(client_obj.created_at)),
    }


def _adaptive_font_scale(columns, max_lines_hint, columns_per_page=None,
                         nominal_columns=None):
    """اندازه قلم ستون‌ها را به شلوغی و پهنای واقعی ستون وابسته می‌کند.

    دو فشار جدا وجود دارد:

    * **ارتفاع** — جلسه‌ی پرحرکت باید در یک ستون جا شود.
    * **پهنا** — وقتی تعداد جلسه‌ها از سقف صفحه بیشتر می‌شود، ستون‌های
      بیشتری در یک صفحه فشرده می‌شوند و هر ستون باریک‌تر می‌شود. با قلم
      بزرگ‌تر، همان خط به دو یا سه سطر می‌شکند و ارتفاع ستون ناگهان چند
      برابر می‌شود. بدون این ضریب، برنامه‌های پرجلسه از صفحه بیرون می‌زدند.

    برنامه‌های معمولی (که اکثر موارد هستند) ضریب ۱ می‌گیرند، یعنی قلم پایه
    و خوانا.
    """
    if not columns:
        return 1.0

    busiest = max(max_lines_hint(col) for col in columns)
    if busiest <= 9:
        # برنامه‌ی سبک: صفحه جای زیادی خالی دارد، پس متن بزرگ‌تر چاپ می‌شود
        height_scale = 1.12
    elif busiest <= 16:
        height_scale = 1.0
    elif busiest <= 20:
        height_scale = 0.94
    elif busiest <= 26:
        height_scale = 0.86
    else:
        height_scale = 0.78

    width_scale = 1.0
    if columns_per_page and columns_per_page >= 3:
        # ستون باریک به‌علاوه‌ی حاشیه‌ی داخلی بیشتر یعنی خط‌های دوتکه.
        # یک سطر کامل با قلم کمی کوچک‌تر، از دو سطر شکسته خواناتر است.
        width_scale = 0.92
    if columns_per_page and nominal_columns and columns_per_page > nominal_columns:
        width_scale = max(0.72, nominal_columns / float(columns_per_page))

    return round(height_scale * width_scale, 3)


def _column_pad_x_mm(box_width):
    """حاشیه‌ی افقی داخل کادر جلسه، متناسب با پهنای همان کادر.

    حاشیه‌ی ثابت روی کادر پهن (دو جلسه در صفحه) کم به نظر می‌رسد و روی کادر
    باریک (چهار جلسه در صفحه) نصف عرض متن را می‌خورد. پس نسبتی از پهنا
    گرفته می‌شود، با سقف و کفِ مشخص.
    """
    proportional = (box_width / mm) * 0.05
    return max(2.5, min(COLUMN_PAD_X_MM, proportional))


# ارتفاع تقریبی اجزای یک کادر روز غذایی با ضریب قلم ۱ (میلی‌متر).
# با اینها ارتفاع صفحه پیش از رندر تخمین زده می‌شود.
# جای کنارگذاشته‌شده برای کادر خلاصه/مکمل‌ها روی صفحه‌ای که آن را دارد
NOTE_BOX_RESERVE_MM = 34
# کمی جای خالی ته صفحه، تا آخرین کادر به حاشیه نچسبد و تخمین ارتفاع هم
# حاشیه‌ی خطا داشته باشد (سطر بلندی که به دو خط می‌شکند)
STACK_SLACK_MM = 6
MEAL_LINE_HEIGHT_MM = 8.0    # یک سطر وعده، شامل فاصله‌ی بالا و پایینش
MEAL_HEAD_HEIGHT_MM = 9.6    # نوار «روز N»
A4_HEIGHT_MM = 297


def _stacked_font_scale(page_groups, lines_hint, reserved_mm=0):
    """اندازه قلم کادرهای سرتاسری که زیر هم می‌نشینند.

    اینجا برخلاف ستون‌ها فشار پهنا وجود ندارد — کادر تمام عرض صفحه را دارد و
    تنها محدودیت ارتفاع است. ارتفاع لازم از قبل تخمین زده می‌شود و ضریب قلم
    طوری انتخاب می‌شود که شلوغ‌ترین صفحه جا شود.

    این محاسبه عمداً به‌جای دسته‌بندی تقریبی انجام می‌شود: مسیر ReportLab
    توانایی «کوچک‌کردن تا جا شود» دارد ولی WeasyPrint ندارد و محتوای اضافه را
    به صفحه‌ی بعد می‌ریزد — یعنی سقف صفحات بخش غذایی نقض می‌شد.
    """
    if not page_groups:
        return 1.0

    available = (
        A4_HEIGHT_MM - PAGE_MARGIN_TOP_MM - PAGE_MARGIN_BOTTOM_MM
        - reserved_mm - STACK_SLACK_MM
    )
    scale = 1.1

    for group in page_groups:
        if not group:
            continue
        # حاشیه‌ی داخلی و فاصله‌ی کادرها بر حسب میلی‌متر است و با قلم کوچک
        # نمی‌شود؛ پس از سهم قابل‌مقیاس جدا حساب می‌شود.
        fixed = len(group) * 2 * MEAL_PAD_Y_MM + (len(group) - 1) * MEAL_BOX_GAP_MM
        scalable = sum(
            MEAL_HEAD_HEIGHT_MM + lines_hint(item) * MEAL_LINE_HEIGHT_MM
            for item in group
        )
        if scalable <= 0:
            continue
        scale = min(scale, (available - fixed) / scalable)

    return round(max(0.7, min(1.1, scale)), 3)


# ---------------------------------------------------------------------------
# مسیر WeasyPrint (اصلی)
# ---------------------------------------------------------------------------

def _html_session_column(session, scale):
    rows = []
    for block_index, block in enumerate(session['blocks']):
        if block_index:
            rows.append('<div class="grp-rule"></div>')
        for line in block:
            normalized = _normalize_digits(line)
            match = _NUMBERED_RE.match(normalized)
            if match:
                move_text = _clean_inline(match.group(2))
                href = _exercise_link(move_text)
                # همان لینکِ مسیرِ ReportLab، تا هر دو موتور یک رفتار داشته باشند
                label = (f'<a href="{escape(href)}" class="mv-link">{escape(move_text)}</a>'
                         if href else escape(move_text))
                rows.append(
                    '<div class="mv">'
                    f'<span class="mv-n">{escape(_fa_digits(match.group(1)))}</span>'
                    f'<span class="mv-t">{label}</span>'
                    '</div>'
                )
            else:
                rows.append(f'<div class="mv mv-plain">{escape(line)}</div>')

    return (
        '<div class="col">'
        f'<div class="col-head">جلسه {_fa_digits(session["number"])}</div>'
        f'<div class="col-body">{"".join(rows)}</div>'
        '</div>'
    )


def _html_day_column(day, scale):
    rows = []
    for row in group_meal_rows(day['lines']):
        label = f'<span class="ml-k">{escape(row["label"])}</span>' if row['label'] else ''
        rows.append(
            '<div class="ml">'
            f'{label}'
            f'<span class="ml-v">{escape(row["text"])}</span>'
            '</div>'
        )

    return (
        '<div class="col">'
        f'<div class="col-head">روز {_fa_digits(day["number"])}</div>'
        f'<div class="col-body">{"".join(rows)}</div>'
        '</div>'
    )


def _html_flow_fallback(md_text, title):
    """چیدمان جریانی برای برنامه‌های قدیمی که قالب ستونی ندارند."""
    import markdown
    body = markdown.markdown(
        md_text or '',
        extensions=['extra', 'tables', 'nl2br', 'sane_lists'],
    )
    return (
        f'<section class="page"><div class="legacy"><h3>{escape(title)}</h3>{body}</div></section>'
    )


def _note_box_html(lines, css_class, head=None):
    """کادر متنی هم‌شکل — برای استراتژی/استراحت و برای مکمل‌ها.

    هر دو یک ظاهر دارند چون هر دو «توضیح کنار برنامه» هستند، نه خود برنامه.
    """
    head_html = f'<span class="note-head">{escape(head)}</span>' if head else ''
    body = ''.join(f'<span>{escape(line)}</span>' for line in lines)
    return f'<div class="note {css_class}">{head_html}{body}</div>'


def _build_html(client_obj, section='both'):
    info = _header_info(client_obj, section)
    header_line = ' · '.join([info['name'], info['type'], info['days'], info['date']])

    pages_html = []

    # ---------------- برنامه ورزشی ----------------
    if section in ('both', 'workout'):
        raw = client_obj.generated_workout or ''
        intro, sessions = parse_workout(raw)

        if _has_structured_workout(sessions):
            page_groups = _chunk_columns(sessions, WORKOUT_COLS_PER_PAGE, WORKOUT_MAX_PAGES)
            scale = _adaptive_font_scale(
                sessions,
                lambda s: sum(len(b) for b in s['blocks']) + len(s['blocks']),
                columns_per_page=max(len(g) for g in page_groups),
                nominal_columns=WORKOUT_COLS_PER_PAGE,
            )
            for page_index, group in enumerate(page_groups):
                intro_html = ''
                if page_index == 0 and intro:
                    # استراتژی و استراحت بین ست‌ها — دوتایی در یک کادر، با
                    # فاصله از بالای صفحه و از ستون‌های زیرش.
                    intro_html = _note_box_html(intro, 'note-intro')
                # پهنای واقعی هر کادر، برای اینکه حاشیه‌ی داخلی با همان
                # نسبتی حساب شود که مسیر ReportLab حساب می‌کند
                content_width_mm = 210 - 2 * PAGE_MARGIN_SIDE_MM
                box_width_mm = content_width_mm / len(group) - COLUMN_GAP_MM
                pad_x = _column_pad_x_mm(box_width_mm * mm)

                cols = ''.join(_html_session_column(s, scale) for s in group)
                pages_html.append(
                    f'<section class="page workout" '
                    f'style="--scale:{scale}; --pad-x:{pad_x:.2f}mm">'
                    f'{intro_html}'
                    f'<div class="grid" style="--cols:{len(group)}">{cols}</div>'
                    '</section>'
                )
        elif raw.strip():
            pages_html.append(_html_flow_fallback(raw, 'برنامه ورزشی'))
        else:
            pages_html.append(
                '<section class="page"><div class="empty">برنامه ورزشی تولید نشده است.</div></section>'
            )

    # ---------------- برنامه غذایی ----------------
    if section in ('both', 'meal'):
        raw = client_obj.generated_meal_plan or ''
        summary, days, supplements = parse_meal(raw)

        if _has_structured_meal(days):
            page_groups = _chunk_columns(days, MEAL_BOXES_PER_PAGE, MEAL_MAX_PAGES)
            # کادرهای روز سرتاسری‌اند، پس فشار پهنا ندارند و اندازه قلم فقط
            # از ارتفاع می‌آید. جای کادر خلاصه/مکمل‌ها از قبل کنار گذاشته
            # می‌شود، وگرنه همان کادر، کادرِ روزِ آخر را از صفحه بیرون می‌زند.
            reserved = NOTE_BOX_RESERVE_MM if (summary or supplements) else 0
            scale = _stacked_font_scale(
                page_groups, _meal_rows_line_estimate, reserved_mm=reserved,
            )
            last_index = len(page_groups) - 1
            for page_index, group in enumerate(page_groups):
                summary_html = ''
                if page_index == 0 and summary:
                    summary_html = _note_box_html(summary, 'note-intro')
                supp_html = ''
                if page_index == last_index and supplements:
                    supp_html = _note_box_html(supplements, 'note-supp', head='مکمل‌ها')
                cols = ''.join(_html_day_column(d, scale) for d in group)
                pages_html.append(
                    f'<section class="page meal" style="--scale:{scale}">'
                    f'{summary_html}'
                    f'<div class="grid">{cols}</div>'
                    f'{supp_html}'
                    '</section>'
                )
        else:
            # برنامهٔ دستی: روز ندارد، تیترِ آزاد دارد. هر تیتر یک کادر می‌شود
            # و مکمل‌ها کادرِ جدا و پررنگ‌ترِ خودش را می‌گیرد.
            sections, supp_lines = parse_meal_sections(raw)
            if sections or supp_lines:
                boxes = ''.join(
                    _note_box_html(sec['lines'], 'note-meal', head=sec['title'] or None)
                    for sec in sections
                )
                if supp_lines:
                    boxes += _note_box_html(supp_lines, 'note-supp', head='مکمل‌ها و ویتامین‌ها')
                pages_html.append(
                    '<section class="page meal">' + boxes + '</section>'
                )
            elif raw.strip():
                pages_html.append(_html_flow_fallback(raw, 'برنامه غذایی'))
            else:
                pages_html.append(
                    '<section class="page"><div class="empty">برنامه غذایی تولید نشده است.</div></section>'
                )

    body = ''.join(pages_html)
    watermark = _watermark_data_uri()
    watermark_rule = (
        f'background-image: url({watermark});\n'
        '    background-repeat: no-repeat;\n'
        '    background-position: center 48%;\n'
        f'    background-size: {WATERMARK_WIDTH_MM}mm auto;'
    ) if watermark else ''

    # دو لوگو بالای هر صفحه: لوگوی ثابت ما و لوگوی همان باشگاه.
    # از background به‌جای content استفاده می‌شود تا با background-size
    # دقیقاً در کادر تعیین‌شده جا شود؛ `content: url()` اندازه‌پذیر نیست.
    def _logo_box(corner, data_uri, align):
        if not data_uri:
            return ''
        return f"""@{corner} {{
      content: "";
      width: {LOGO_MAX_WIDTH_MM}mm;
      height: {LOGO_HEIGHT_MM}mm;
      background-image: url({data_uri});
      background-repeat: no-repeat;
      background-position: {align} bottom;
      background-size: contain;
    }}"""

    # لوگوی باشگاه سمت راست (شروع متن فارسی) و لوگوی ما سمت چپ
    gym_logo_css = _logo_box('top-right', _image_data_uri(_gym_logo_path(client_obj)), 'right')
    platform_logo_css = _logo_box('top-left', _platform_logo_data_uri(), 'left')

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<title>{escape(info['name'])}</title>
<style>
  @page {{
    size: A4;
    margin: {PAGE_MARGIN_TOP_MM}mm {PAGE_MARGIN_SIDE_MM}mm {PAGE_MARGIN_BOTTOM_MM}mm;

    /* لوگوی برند، سیاه‌وسفید و بسیار کم‌رنگ، پشت محتوای هر صفحه */
    {watermark_rule}

    {gym_logo_css}
    @top-center {{
      content: "{escape(header_line)}";
      font-family: Vazirmatn, Tahoma, Arial, sans-serif;
      font-size: {HEADER_FONT_PT}pt;
      color: {COLOR_INK};
      letter-spacing: .2px;
      vertical-align: bottom;
      padding-bottom: {HEADER_GAP_BELOW_MM}mm;
    }}
    {platform_logo_css}
    /* پاورقی دو سطری و وسط‌چین — همان دو سطری که مسیر ReportLab می‌کشد.
       کنار هم نمی‌نشینند چون مجموع عرضشان از عرض صفحه بیشتر است. */
    @bottom-center {{
      content: "{escape(COACH_NOTE_TEXT)}\\A{escape(DISCLAIMER_TEXT)}";
      white-space: pre-line;
      font-family: Vazirmatn, Tahoma, Arial, sans-serif;
      font-size: {COACH_NOTE_FONT_PT}pt;
      line-height: 1.6;
      color: {COLOR_MUTED};
      vertical-align: top;
      padding-top: 2.5mm;
    }}
  }}

  * {{ box-sizing: border-box; }}
  body {{
    font-family: Vazirmatn, Tahoma, Arial, sans-serif;
    direction: rtl;
    text-align: right;
    color: {COLOR_BODY};
    margin: 0;
  }}

  .page {{ break-after: page; }}
  .page:last-of-type {{ break-after: auto; }}

  /* --- کادر توضیحی: استراتژی + استراحت بین ست‌ها، و مکمل‌ها --- */
  .note {{
    border: .5pt solid {COLOR_RULE};
    border-radius: 2.5mm;
    background: {COLOR_NOTE_BG};
    padding: {NOTE_PAD_Y_MM}mm {NOTE_PAD_X_MM}mm;
    break-inside: avoid;
  }}
  .note span {{
    display: block;
    font-size: {NOTE_FONT_PT}pt;
    line-height: 1.8;
    color: {COLOR_BODY};
  }}
  .note span + span {{ margin-top: {NOTE_LINE_GAP_MM}mm; }}
  .note-head {{ color: {COLOR_INK}; font-weight: 700; }}
  .note-intro {{ margin: {NOTE_TOP_GAP_MM}mm 0 {NOTE_BOTTOM_GAP_MM}mm; }}
  .note-supp {{ margin-top: {NOTE_BOTTOM_GAP_MM}mm; }}
  /* کادرِ هر وعدهٔ برنامهٔ دستی — هم‌شکلِ کادرهای دیگر، با فاصلهٔ یک‌دست */
  .note-meal {{ margin: 0 0 {NOTE_BOTTOM_GAP_MM}mm; }}
  .note-meal:first-child {{ margin-top: {NOTE_TOP_GAP_MM}mm; }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(var(--cols, 3), 1fr);
    gap: {COLUMN_GAP_MM}mm;
    align-items: start;
  }}
  /* برنامه غذایی ستون کنار هم ندارد: کادرهای سرتاسری، زیر هم */
  .meal .grid {{
    grid-template-columns: 1fr;
    gap: {MEAL_BOX_GAP_MM}mm;
  }}

  .col {{
    break-inside: avoid;
    border: .4pt solid {COLOR_RULE};
    border-radius: 2.5mm;
    overflow: hidden;
  }}
  .col-head {{
    background: {COLOR_TINT};
    color: {COLOR_INK};
    font-size: calc(11.5pt * var(--scale, 1));
    font-weight: 700;
    text-align: center;
    padding: {COLUMN_HEAD_PAD_MM}mm 1.5mm;
    letter-spacing: .2px;
  }}
  .col-body {{
    padding: {COLUMN_PAD_Y_MM}mm var(--pad-x, {COLUMN_PAD_X_MM}mm);
  }}
  .meal .col-body {{ padding: {MEAL_PAD_Y_MM}mm {MEAL_PAD_X_MM}mm; }}

  /* --- حرکت ورزشی --- */
  .mv {{
    display: flex;
    gap: 1.6mm;
    font-size: calc(11pt * var(--scale, 1));
    line-height: 1.75;
    padding: 1.3mm 0;
  }}
  .mv-n {{
    color: {COLOR_ACCENT};
    font-weight: 700;
    min-width: 5.5mm;
  }}
  .mv-t {{ flex: 1; }}
  .mv-plain {{ color: {COLOR_ACCENT}; font-size: calc(10pt * var(--scale, 1)); }}

  /* خط جداکننده گروه عضلانی — نازک و کوتاه، بدون متن */
  .grp-rule {{
    height: 0;
    border-top: .35pt solid {COLOR_RULE};
    width: 38%;
    margin: 1.3mm auto;
  }}

  /* --- وعده غذایی --- */
  .ml {{
    display: flex;
    gap: 2mm;
    font-size: calc(11pt * var(--scale, 1));
    line-height: 1.9;
    padding: 1.8mm 0;
  }}
  .ml + .ml {{ border-top: .3pt solid {COLOR_RULE}; }}
  .ml-k {{
    color: {COLOR_INK};
    font-weight: 700;
    flex: 0 0 {MEAL_LABEL_WIDTH_MM}mm;
  }}
  .ml-v {{ color: {COLOR_BODY}; flex: 1; }}

  .empty {{ font-size: 12pt; color: {COLOR_MUTED}; text-align: center; padding-top: 20mm; }}

  /* چیدمان جریانی برای برنامه‌های قدیمی */
  .legacy {{ column-count: 2; column-gap: 6mm; font-size: 10.5pt; line-height: 1.8; }}
  .legacy h3 {{ column-span: all; color: {COLOR_INK}; font-size: 14pt; margin: 0 0 3mm; }}
  .legacy h1, .legacy h2 {{ font-size: 12pt; color: {COLOR_INK}; margin: 2mm 0 1mm; }}
  .legacy h4, .legacy h5 {{ font-size: 11pt; color: {COLOR_ACCENT}; margin: 2mm 0 1mm; }}
  .legacy p, .legacy li {{ margin: 0 0 1mm; }}
  .legacy ul, .legacy ol {{ padding-right: 4mm; margin: 0 0 2mm; }}
  .legacy table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
  .legacy th, .legacy td {{ border: .4pt solid {COLOR_RULE}; padding: 1mm; text-align: right; }}
  .legacy hr {{ border: 0; border-top: .35pt solid {COLOR_RULE}; width: 38%; margin: 1.5mm auto; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# مسیر ReportLab (پشتیبان — وقتی WeasyPrint روی سرور نصب نیست)
# ---------------------------------------------------------------------------

def _rtl(text):
    """شکل‌دهی صحیح متن فارسی برای ReportLab."""
    if not text:
        return ""
    try:
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return str(text)


def _xml_escape(text):
    """فرار دادن نویسه‌های نشانه‌گذاری برای Paragraph در ReportLab."""
    return (
        str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    )


def _exercise_link(text):
    """اگر این خط یکی از حرکت‌های کتابخانه باشد، آدرسِ صفحهٔ آموزشش را برمی‌گرداند.

    آدرس مطلق است چون PDF بیرون از سایت باز می‌شود. پایهٔ آدرس از تنظیماتِ
    PUBLIC_BASE_URL خوانده می‌شود تا با عوض‌شدنِ دامنه، لینک‌ها نشکنند.
    خطا در این بخش نباید ساختِ PDF را بشکند؛ در بدترین حالت لینک نمی‌خورد.
    """
    try:
        from django.conf import settings as _st
        from app.exercise_match import find_exercise, note_unmatched
        hit = find_exercise(text)
        if not hit:
            # ثبت می‌شود تا در «نام‌های بی‌تطبیق» دیده شود و مالک تصمیم بگیرد
            import re as _re
            note_unmatched(_re.sub(r'\s*—.*$', '', text).strip(), text)
            return None
        base = getattr(_st, 'PUBLIC_BASE_URL', '') or 'http://185.239.3.189:8000/chagher'
        return '%s/exercise/%s/' % (base.rstrip('/'), hit[0])
    except Exception:
        return None


def _rtl_paragraph(text, style, max_width, href=None):
    """پاراگراف فارسی که *قبل از* جهت‌دهی به عرض ستون شکسته می‌شود.

    ReportLab از دوسویه‌سازی یونیکد پشتیبانی نمی‌کند، پس اگر اول کل خط را
    جهت‌دهی کنیم و بعد بگذاریم خودش بشکند، ترتیب کلمات به هم می‌ریزد و مثلاً
    «صبحانه:» از ابتدای وعده به انتهای پاراگراف پرتاب می‌شود. راه درست این
    است که اول در ترتیب منطقی بشکنیم و بعد هر سطر را جداگانه جهت‌دهی کنیم.
    """
    font_name = style.fontName
    font_size = style.fontSize
    # حاشیه اطمینان: اگر اندازه‌گیری ما مویی از محاسبه ReportLab بزرگ‌تر شود،
    # خود ReportLab خط را دوباره می‌شکند و چون آن خط قبلاً جهت‌دهی شده،
    # کلمه‌ی اول (مثل «ناهار:») به سطر بعد پرت می‌شود.
    limit = max(float(max_width) - 2.0, 1.0)

    def width_of(candidate):
        return pdfmetrics.stringWidth(_rtl(candidate), font_name, font_size)

    words = str(text or '').split()
    if not words:
        return Paragraph('', style)

    lines = []
    current = []
    for word in words:
        trial = current + [word]
        if current and width_of(' '.join(trial)) > limit:
            lines.append(' '.join(current))
            current = [word]
        else:
            current = trial
    if current:
        lines.append(' '.join(current))

    body = '<br/>'.join(_xml_escape(_rtl(line)) for line in lines)
    if href:
        # رنگ و زیرخط تا کاربر بفهمد قابلِ کلیک است (ReportLab لینکِ داخلیِ PDF می‌سازد)
        body = '<a href="%s" color="#1565c0"><u>%s</u></a>' % (_xml_escape(href), body)
    return Paragraph(body, style)


def persian_font_candidates():
    """مسیرهایی که برای یافتن فونت فارسی بررسی می‌شوند (به ترتیب اولویت)."""
    return [
        os.environ.get('GYM_PDF_FONT_PATH', ''),
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Regular.ttf",
        "/usr/share/fonts/truetype/vazir/Vazir.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/farsiweb/nazli.ttf",
        "/System/Library/Fonts/Supplemental/Tahoma.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]


def find_persian_font():
    """اولین فونت فارسی موجود را برمی‌گرداند، یا None اگر هیچ‌کدام نبود."""
    for path in persian_font_candidates():
        if path and os.path.exists(path):
            return path
    return None


def _register_font():
    """فونت فارسی را برای ReportLab ثبت می‌کند."""
    candidates = persian_font_candidates()
    for path in candidates:
        if path and os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("AppFont", path))
                return "AppFont"
            except Exception:
                continue
    logger.error(
        "No Persian-capable TTF font found for ReportLab PDF. "
        "Set GYM_PDF_FONT_PATH to a Persian font file (e.g. Vazirmatn)."
    )
    return "Helvetica"


def _draw_logo(canvas, path, x_left, x_right, top_y, align='left'):
    """یک لوگو را در کادر تعیین‌شده و با حفظ نسبت ابعاد می‌کشد.

    `x_left`/`x_right` مرز افقی کادر مجاز است؛ لوگو داخل همین کادر و
    چسبیده به همان طرف قرار می‌گیرد تا دو لوگوی دو سمت صفحه هم‌تراز شوند.
    """
    if not path or not os.path.exists(path):
        return
    try:
        reader = ImageReader(path)
        src_w, src_h = reader.getSize()
        if not src_w or not src_h:
            return

        max_h = LOGO_HEIGHT_MM * mm
        max_w = min(LOGO_MAX_WIDTH_MM * mm, x_right - x_left)
        scale = min(max_w / float(src_w), max_h / float(src_h))
        width, height = src_w * scale, src_h * scale

        x = x_left if align == 'left' else x_right - width
        canvas.drawImage(
            reader, x, top_y - height, width=width, height=height,
            mask='auto', preserveAspectRatio=True,
        )
    except Exception:
        # لوگو تزئینی است؛ خراب‌بودنش نباید تولید برنامه را بشکند
        logger.warning('Failed to draw logo %s', path, exc_info=True)


class _ColumnDoc(BaseDocTemplate):
    """سند تک‌فریمی با سربرگ (لوگوها + مشخصات) و پاورقی روی همه صفحات."""

    def __init__(self, buf, header_line, gym_logo_path='', ai_generated=True, **kwargs):
        super().__init__(buf, pagesize=A4, **kwargs)
        self._header_line = header_line
        self._gym_logo_path = gym_logo_path
        # «برنامه را هوش مصنوعی ساخته یا مربی؟» — فقط پاورقی را عوض می‌کند
        self._ai_generated = ai_generated
        frame = Frame(
            self.leftMargin, self.bottomMargin,
            self.width, self.height,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
            id='body',
        )
        self.addPageTemplates([
            PageTemplate(id='main', frames=[frame], onPage=self._decorate)
        ])

    def _decorate(self, canvas, doc):
        canvas.saveState()
        width, height = A4
        font = getattr(doc, 'app_font', 'Helvetica')

        # واترمارک لوگو، پیش از هر چیز دیگری تا پشت محتوا بماند.
        # شفافیت از خود فایل PNG می‌آید، نه از تنظیمات بوم.
        if os.path.exists(WATERMARK_FILE):
            try:
                mark_w = WATERMARK_WIDTH_MM * mm
                mark_h = mark_w * 790.0 / 846.0
                canvas.drawImage(
                    WATERMARK_FILE,
                    (width - mark_w) / 2.0,
                    (height - mark_h) / 2.0,
                    width=mark_w,
                    height=mark_h,
                    mask='auto',
                    preserveAspectRatio=True,
                )
            except Exception:
                logger.warning('Failed to draw watermark on ReportLab page', exc_info=True)

        side = PAGE_MARGIN_SIDE_MM * mm
        logo_top = height - 5 * mm

        # لوگوی باشگاه سمت راست (شروع متن فارسی) و لوگوی ثابت ما سمت چپ.
        # هر دو داخل حاشیه‌ی بالا می‌نشینند، بالاتر از سطر مشخصات.
        _draw_logo(
            canvas, self._gym_logo_path,
            width - side - LOGO_MAX_WIDTH_MM * mm, width - side,
            logo_top, align='right',
        )
        _draw_logo(
            canvas, LOGO_FILE,
            side, side + LOGO_MAX_WIDTH_MM * mm,
            logo_top, align='left',
        )

        # سربرگ: نام · نوع · تعداد روز · تاریخ
        canvas.setFont(font, HEADER_FONT_PT)
        canvas.setFillColor(colors.HexColor(COLOR_INK))
        canvas.drawCentredString(
            width / 2.0,
            height - (PAGE_MARGIN_TOP_MM - HEADER_GAP_BELOW_MM) * mm,
            _rtl(self._header_line),
        )

        # پاورقی دو سطری و وسط‌چین: اخطار هماهنگی با مربی، بعد یادآوری خطای
        # هوش مصنوعی. دو سطر جدا، چون کنار هم به عرض صفحه نمی‌خورند.
        canvas.setFillColor(colors.HexColor(COLOR_MUTED))
        if getattr(self, '_ai_generated', True):
            canvas.setFont(font, COACH_NOTE_FONT_PT)
            canvas.drawCentredString(width / 2.0, 11.5 * mm, _rtl(COACH_NOTE_TEXT))
            canvas.setFont(font, DISCLAIMER_FONT_PT)
            canvas.drawCentredString(width / 2.0, 6.5 * mm, _rtl(DISCLAIMER_TEXT))
        else:
            # برنامهٔ دستی: هیچ هشدارِ هوش مصنوعی‌ای نباید دیده شود
            canvas.setFont(font, COACH_NOTE_FONT_PT)
            canvas.drawCentredString(width / 2.0, 8.0 * mm, _rtl(MANUAL_NOTE_TEXT))

        canvas.restoreState()


def _rl_styles(font_name, scale):
    """سبک‌های متنی مسیر ReportLab — هم‌اندازه با مسیر WeasyPrint.

    `leading` همان نقش `line-height` را دارد و عمداً سخاوتمندانه است: خروجی
    چاپی است و سطرهای چسبیده، برگه را خسته‌کننده می‌کند.
    """
    base = getSampleStyleSheet()
    return {
        'head': ParagraphStyle(
            'col_head', parent=base['Normal'], fontName=font_name,
            fontSize=11.5 * scale, leading=16 * scale, alignment=1,
            textColor=colors.HexColor(COLOR_INK),
        ),
        'move': ParagraphStyle(
            'move', parent=base['Normal'], fontName=font_name,
            fontSize=11 * scale, leading=19 * scale, alignment=2,
            spaceBefore=1.8 * scale, spaceAfter=1.8 * scale,
            textColor=colors.HexColor(COLOR_BODY),
        ),
        'move_plain': ParagraphStyle(
            'move_plain', parent=base['Normal'], fontName=font_name,
            fontSize=10 * scale, leading=18 * scale, alignment=2,
            spaceBefore=1.8 * scale, spaceAfter=1.8 * scale,
            textColor=colors.HexColor(COLOR_ACCENT),
        ),
        # وعده‌های غذایی نفس بیشتری می‌گیرند — کادرشان سرتاسری است و جا دارد
        'meal': ParagraphStyle(
            'meal', parent=base['Normal'], fontName=font_name,
            fontSize=11 * scale, leading=22 * scale, alignment=2,
            spaceBefore=2.5 * scale, spaceAfter=2.5 * scale,
            textColor=colors.HexColor(COLOR_BODY),
        ),
        # عنوان وعده («صبحانه:») — تا ساختار روز در کادر پهن خوانده شود
        'meal_label': ParagraphStyle(
            'meal_label', parent=base['Normal'], fontName=font_name,
            fontSize=11 * scale, leading=22 * scale, alignment=2,
            spaceBefore=4 * scale, spaceAfter=1 * scale,
            textColor=colors.HexColor(COLOR_INK),
        ),
        # متن کادر استراتژی/استراحت و کادر مکمل‌ها — اندازه‌ی متن بدنه‌ی A4
        'note': ParagraphStyle(
            'note', parent=base['Normal'], fontName=font_name,
            fontSize=NOTE_FONT_PT, leading=NOTE_FONT_PT * 1.8, alignment=2,
            textColor=colors.HexColor(COLOR_BODY),
        ),
        'note_head': ParagraphStyle(
            'note_head', parent=base['Normal'], fontName=font_name,
            fontSize=NOTE_FONT_PT, leading=NOTE_FONT_PT * 1.8, alignment=2,
            textColor=colors.HexColor(COLOR_INK),
        ),
        'empty': ParagraphStyle(
            'empty', parent=base['Normal'], fontName=font_name,
            fontSize=12, leading=18, alignment=1,
            textColor=colors.HexColor(COLOR_MUTED),
        ),
    }


def _rl_note_box(lines, styles, width, head=None):
    """کادر استراتژی/استراحت — و همان ظاهر برای مکمل‌ها.

    خط‌ها داخل یک کادر می‌مانند ولی از هم فاصله می‌گیرند، چون «استراتژی» و
    «استراحت بین ست‌ها» دو حرف جدا هستند که با هم خوانده می‌شوند.
    """
    inner_width = width - 2 * NOTE_PAD_X_MM * mm
    rows = []
    if head:
        rows.append([_rtl_paragraph(head, styles['note_head'], inner_width)])
    for index, line in enumerate(lines):
        if rows:
            rows.append([Spacer(1, NOTE_LINE_GAP_MM * mm)])
        rows.append([_rtl_paragraph(line, styles['note'], inner_width)])

    box = Table(rows or [['']], colWidths=[inner_width])
    box.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    holder = Table([[box]], colWidths=[width])
    holder.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor(COLOR_RULE)),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(COLOR_NOTE_BG)),
        ('LEFTPADDING', (0, 0), (-1, -1), NOTE_PAD_X_MM * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), NOTE_PAD_X_MM * mm),
        ('TOPPADDING', (0, 0), (-1, -1), NOTE_PAD_Y_MM * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), NOTE_PAD_Y_MM * mm),
    ]))
    return holder


def _rl_thin_rule(content_width):
    """خط جداکننده نازک و کوتاه بین گروه‌های عضلانی."""
    rule = Table([['']], colWidths=[content_width * 0.38], rowHeights=[0.1])
    rule.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 0.35, colors.HexColor(COLOR_RULE)),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    holder = Table([[rule]], colWidths=[content_width])
    holder.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return holder


def _rl_column_head(label, styles, box_width):
    """سربرگ رنگی کادر — «جلسه N» یا «روز N»، سرتاسری از لبه تا لبه."""
    head = _rtl_paragraph(label, styles['head'], box_width - 6)
    table = Table([[head]], colWidths=[box_width])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(COLOR_TINT)),
        ('TOPPADDING', (0, 0), (-1, -1), COLUMN_HEAD_PAD_MM * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), COLUMN_HEAD_PAD_MM * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    return table


def _rl_box(label, body_items, styles, box_width, pad_x, pad_y):
    """یک کادر کامل: سربرگ رنگی سرتاسری + بدنه با حاشیه‌ی سخاوتمندانه.

    معادل `.col` در مسیر WeasyPrint. سربرگ عمداً بدون حاشیه است تا مثل
    همان‌جا از لبه تا لبه کشیده شود و بدنه از کناره‌ها فاصله بگیرد.
    """
    body = Table([[item] for item in body_items] or [['']],
                 colWidths=[box_width - 2 * pad_x])
    body.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    box = Table(
        [[_rl_column_head(label, styles, box_width)], [body]],
        colWidths=[box_width],
    )
    box.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_RULE)),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        # سربرگ: بدون حاشیه تا تمام عرض کادر را بگیرد
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 0),
        ('TOPPADDING', (0, 0), (0, 0), 0),
        ('BOTTOMPADDING', (0, 0), (0, 0), 0),
        # بدنه: فاصله از کناره‌ها و از بالا و پایین
        ('LEFTPADDING', (0, 1), (0, 1), pad_x),
        ('RIGHTPADDING', (0, 1), (0, 1), pad_x),
        ('TOPPADDING', (0, 1), (0, 1), pad_y),
        ('BOTTOMPADDING', (0, 1), (0, 1), pad_y),
    ]))
    return box


def _rl_session_box(session, styles, box_width):
    """کادر یک جلسه‌ی تمرینی."""
    pad_x = _column_pad_x_mm(box_width) * mm
    content_width = box_width - 2 * pad_x

    items = []
    for block_index, block in enumerate(session['blocks']):
        if block_index:
            items.append(_rl_thin_rule(content_width))
        for line in block:
            normalized = _normalize_digits(line)
            match = _NUMBERED_RE.match(normalized)
            if match:
                move_text = _clean_inline(match.group(2))
                text = f"{_fa_digits(match.group(1))}. {move_text}"
                items.append(_rtl_paragraph(text, styles['move'], content_width,
                                            href=_exercise_link(move_text)))
            else:
                items.append(_rtl_paragraph(line, styles['move_plain'], content_width))

    return _rl_box(
        f"جلسه {_fa_digits(session['number'])}", items, styles, box_width,
        pad_x, COLUMN_PAD_Y_MM * mm,
    )


def _rl_day_box(day, styles, box_width):
    """کادر یک روز غذایی — سرتاسری، هر وعده یک ردیف.

    ستون راست نام وعده است و ستون چپ اقلامش؛ همان شکلی که مربی برنامه‌ی
    غذایی می‌نویسد. ردیف‌ها با یک خط نازک از هم جدا می‌شوند — نه کادر دور
    تا دور، که برگه را شلوغ می‌کند.
    """
    pad_x = MEAL_PAD_X_MM * mm
    content_width = box_width - 2 * pad_x
    label_width = MEAL_LABEL_WIDTH_MM * mm
    text_width = content_width - label_width

    table_rows = []
    for row in group_meal_rows(day['lines']):
        table_rows.append([
            _rtl_paragraph(row['text'], styles['meal'], text_width - 6),
            _rtl_paragraph(row['label'] or '', styles['meal_label'], label_width - 6),
        ])

    if not table_rows:
        table_rows = [[Paragraph('', styles['meal']), Paragraph('', styles['meal'])]]

    # ستون راست (اندیس ۱) نام وعده است — در سند راست‌به‌چپ اول خوانده می‌شود
    grid = Table(table_rows, colWidths=[text_width, label_width])
    style = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), MEAL_ROW_PAD_PT),
        ('BOTTOMPADDING', (0, 0), (-1, -1), MEAL_ROW_PAD_PT),
    ]
    for index in range(len(table_rows) - 1):
        style.append(
            ('LINEBELOW', (0, index), (-1, index), 0.3, colors.HexColor(COLOR_RULE))
        )
    grid.setStyle(TableStyle(style))

    return _rl_box(
        f"روز {_fa_digits(day['number'])}", [grid], styles, box_width,
        pad_x, MEAL_PAD_Y_MM * mm,
    )


def _rl_column_grid(boxes, box_width, gap, available_height):
    """کادرهای جلسه را کنار هم می‌چیند؛ در RTL جلسه‌ی اول سمت راست است.

    هر کادر حاشیه‌ی خودش را دارد و جدول بیرونی فقط فاصله‌ی بینشان را
    می‌سازد — دقیقاً مثل `gap` در مسیر WeasyPrint.
    """
    cells = [
        KeepInFrame(box_width, available_height, [box], mode='shrink')
        for box in boxes
    ]
    cells.reverse()  # RTL: جلسه‌ی ۱ باید راست‌ترین باشد

    cell_width = box_width + gap
    table = Table([cells], colWidths=[cell_width] * len(cells), hAlign='RIGHT')
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), gap / 2.0),
        ('RIGHTPADDING', (0, 0), (-1, -1), gap / 2.0),
    ]))
    return table


def _rl_legacy_flow(md_text, styles, title_style, max_width):
    """برنامه‌های قدیمی بدون قالب ستونی — جریان ساده مارک‌داون."""
    items = []
    for raw in (md_text or '').splitlines():
        stripped = raw.strip()
        if not stripped:
            items.append(Spacer(1, 3))
            continue
        if _RULE_RE.match(stripped):
            continue
        if stripped.startswith('#'):
            text = _clean_inline(stripped.lstrip('#').strip())
            items.append(_rtl_paragraph(text, title_style, max_width))
            continue
        if stripped.startswith(('- ', '* ')):
            items.append(
                _rtl_paragraph('• ' + _clean_inline(stripped[2:]), styles['move'], max_width)
            )
            continue
        items.append(_rtl_paragraph(_clean_inline(stripped), styles['move'], max_width))
    return items


def _build_reportlab_pdf(client_obj, section='both'):
    """Fallback: همان چیدمان ستونی با ReportLab."""
    font_name = _register_font()
    info = _header_info(client_obj, section)
    header_line = ' · '.join([info['name'], info['type'], info['days'], info['date']])

    buf = io.BytesIO()
    doc = _ColumnDoc(
        buf, header_line,
        # برنامهٔ دستی هشدارِ هوش مصنوعی نمی‌گیرد (مورد ۴ گزارشِ مالک)
        ai_generated=getattr(client_obj, 'source', 'ai') != 'manual',
        gym_logo_path=_gym_logo_path(client_obj),
        leftMargin=PAGE_MARGIN_SIDE_MM * mm, rightMargin=PAGE_MARGIN_SIDE_MM * mm,
        topMargin=PAGE_MARGIN_TOP_MM * mm, bottomMargin=PAGE_MARGIN_BOTTOM_MM * mm,
    )
    doc.app_font = font_name

    gap = COLUMN_GAP_MM * mm
    story = []

    def add_page_break():
        if story:
            story.append(PageBreak())

    # ---------------- برنامه ورزشی ----------------
    if section in ('both', 'workout'):
        raw = client_obj.generated_workout or ''
        intro, sessions = parse_workout(raw)

        if _has_structured_workout(sessions):
            scale = _adaptive_font_scale(
                sessions,
                lambda s: sum(len(b) for b in s['blocks']) + len(s['blocks']),
            )
            styles = _rl_styles(font_name, scale)
            page_groups = _chunk_columns(sessions, WORKOUT_COLS_PER_PAGE, WORKOUT_MAX_PAGES)

            for page_index, group in enumerate(page_groups):
                add_page_break()
                used_height = 0
                if page_index == 0 and intro:
                    # استراتژی و استراحت بین ست‌ها، دوتایی در یک کادر، با
                    # فاصله از بالای صفحه و از کادرهای جلسه
                    story.append(Spacer(1, NOTE_TOP_GAP_MM * mm))
                    note = _rl_note_box(intro, styles, doc.width)
                    story.append(note)
                    story.append(Spacer(1, NOTE_BOTTOM_GAP_MM * mm))
                    used_height = (
                        note.wrap(doc.width, doc.height)[1]
                        + (NOTE_TOP_GAP_MM + NOTE_BOTTOM_GAP_MM) * mm
                    )

                box_width = doc.width / len(group) - gap
                boxes = [_rl_session_box(s, styles, box_width) for s in group]
                story.append(_rl_column_grid(
                    boxes, box_width, gap, doc.height - used_height,
                ))
        elif raw.strip():
            add_page_break()
            styles = _rl_styles(font_name, 1.0)
            story.extend(_rl_legacy_flow(raw, styles, styles['note_head'], doc.width))
        else:
            add_page_break()
            styles = _rl_styles(font_name, 1.0)
            story.append(_rtl_paragraph('برنامه ورزشی تولید نشده است.', styles['empty'], doc.width))

    # ---------------- برنامه غذایی ----------------
    if section in ('both', 'meal'):
        raw = client_obj.generated_meal_plan or ''
        summary, days, supplements = parse_meal(raw)

        if _has_structured_meal(days):
            page_groups = _chunk_columns(days, MEAL_BOXES_PER_PAGE, MEAL_MAX_PAGES)
            reserved = NOTE_BOX_RESERVE_MM if (summary or supplements) else 0
            scale = _stacked_font_scale(
                page_groups, _meal_rows_line_estimate, reserved_mm=reserved,
            )
            styles = _rl_styles(font_name, scale)
            last_index = len(page_groups) - 1

            for page_index, group in enumerate(page_groups):
                add_page_break()
                used_height = 0

                if page_index == 0 and summary:
                    story.append(Spacer(1, NOTE_TOP_GAP_MM * mm))
                    note = _rl_note_box(summary, styles, doc.width)
                    story.append(note)
                    story.append(Spacer(1, NOTE_BOTTOM_GAP_MM * mm))
                    used_height += (
                        note.wrap(doc.width, doc.height)[1]
                        + (NOTE_TOP_GAP_MM + NOTE_BOTTOM_GAP_MM) * mm
                    )

                supp_box = None
                if page_index == last_index and supplements:
                    supp_box = _rl_note_box(
                        supplements, styles, doc.width, head='مکمل‌ها'
                    )
                    used_height += (
                        supp_box.wrap(doc.width, doc.height)[1]
                        + NOTE_BOTTOM_GAP_MM * mm
                    )

                # کادرهای روز: سرتاسری و زیر هم، نه ستون‌های کنار هم.
                # همه‌ی کادرهای یک صفحه با هم در یک قاب نگه داشته می‌شوند تا
                # اگر جا کم آمد کوچک شوند و از سقف صفحات نزنند بیرون.
                stacked = []
                for box_index, day in enumerate(group):
                    if box_index:
                        stacked.append(Spacer(1, MEAL_BOX_GAP_MM * mm))
                    stacked.append(_rl_day_box(day, styles, doc.width))
                story.append(KeepInFrame(
                    doc.width, max(doc.height - used_height, 1), stacked, mode='shrink',
                ))

                if supp_box is not None:
                    story.append(Spacer(1, NOTE_BOTTOM_GAP_MM * mm))
                    story.append(supp_box)
        else:
            # برنامهٔ دستی: روز ندارد، تیترِ آزاد دارد ⇒ هر تیتر یک کادر.
            # ⚠ پیش از این به _rl_legacy_flow می‌افتاد و متنِ لخت چاپ می‌شد.
            sections, supp_lines = parse_meal_sections(raw)
            if sections or supp_lines:
                add_page_break()
                styles = _rl_styles(font_name, 1.0)
                story.append(Spacer(1, NOTE_TOP_GAP_MM * mm))
                for sec in sections:
                    story.append(_rl_note_box(
                        sec['lines'], styles, doc.width, head=sec['title'] or None))
                    story.append(Spacer(1, NOTE_BOTTOM_GAP_MM * mm))
                if supp_lines:
                    story.append(_rl_note_box(
                        supp_lines, styles, doc.width, head='مکمل‌ها و ویتامین‌ها'))
            elif raw.strip():
                add_page_break()
                styles = _rl_styles(font_name, 1.0)
                story.extend(_rl_legacy_flow(raw, styles, styles['note_head'], doc.width))
            else:
                add_page_break()
                styles = _rl_styles(font_name, 1.0)
                story.append(_rtl_paragraph(
                    'برنامه غذایی تولید نشده است.', styles['empty'], doc.width))

    if not story:
        styles = _rl_styles(font_name, 1.0)
        story.append(_rtl_paragraph('برنامه‌ای برای نمایش وجود ندارد.', styles['empty'], doc.width))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# API عمومی
# ---------------------------------------------------------------------------

def generate_pdf(client_obj, section='both'):
    """
    تولید PDF حرفه‌ای.
    - section: 'both', 'workout', 'meal'
    """
    if WEASYPRINT_AVAILABLE:
        try:
            html_content = _build_html(client_obj, section)
            pdf_bytes = io.BytesIO()
            HTML(string=html_content, base_url=str(settings.BASE_DIR)).write_pdf(pdf_bytes)
            pdf_bytes.seek(0)
            return pdf_bytes.getvalue(), 'pdf'
        except Exception:
            # خطای زمان اجرا هم به ReportLab برمی‌گردد تا کاربر بدون PDF نماند
            logger.exception("WeasyPrint rendering failed; falling back to ReportLab")

    return _build_reportlab_pdf(client_obj, section), 'pdf'


def generate_workout_pdf(client_obj):
    """تولید PDF فقط برای برنامه ورزشی"""
    return generate_pdf(client_obj, section='workout')


def generate_meal_pdf(client_obj):
    """تولید PDF فقط برای برنامه غذایی"""
    return generate_pdf(client_obj, section='meal')
