# -*- coding: utf-8 -*-
"""نگاشتِ «جفتِ قلمِ لاتین» (۷۴ جفتِ ui-ux-pro-max) به «جفتِ قلمِ فارسیِ مجوزدار».

قلم‌های لاتین (Inter، Playfair…) حروفِ فارسی ندارند؛ برای هر قلمِ لاتین نزدیک‌ترین قلمِ فارسی‌پذیرِ OFL را از قلم‌های همراهِ سایت‌ساز برمی‌داریم
(نقشِ آن‌ها را از دستهٔ قلم در گوگل‌فونتس و خوی‌وخوی‌شان می‌فهمیم: بی‌سریف، سریف، تزئینی، دست‌نویس، تک‌فاصله).
هر جفت = (قلمِ تیتر، قلمِ متن)؛ اگر قلمِ متن تزئینی بود به یک قلمِ خوانا برمی‌گردد، چون متنِ بلند با قلمِ تزئینی خوانا نیست.
آزمون می‌سنجد: هر قلمِ لاتینِ هر جفت نگاشت دارد، هر نگاشت در FONTS هست، و همهٔ آن‌ها پ چ ژ گ و رقم‌های فارسی را دارند.
"""

# قلمِ لاتین ⇒ کلیدِ قلمِ فارسی در theme.FONTS
PERSIAN_OF = {
    'Inter': 'vazirmatn', 'Public Sans': 'vazirmatn', 'Lato': 'vazirmatn', 'Atkinson Hyperlegible': 'vazirmatn',
    'Space Grotesk': 'alexandria', 'Outfit': 'alexandria', 'Lexend': 'alexandria', 'Lexend Mega': 'alexandria',
    'Plus Jakarta Sans': 'estedad', 'Raleway': 'estedad', 'Manrope': 'estedad', 'Epilogue': 'estedad', 'Be Vietnam Pro': 'estedad',
    'DM Sans': 'mada', 'Work Sans': 'mada', 'Figtree': 'mada', 'Karla': 'mada', 'Cabin': 'mada',
    'Poppins': 'cairo', 'Montserrat': 'cairo', 'Jost': 'cairo',
    'Roboto': 'notosans', 'Open Sans': 'notosans', 'Source Sans 3': 'notosans', 'Noto Sans': 'notosans', 'Noto Sans Arabic': 'notosans', 'Fira Sans': 'notosans',
    'Noto Sans KR': 'notosans', 'Noto Sans SC': 'notosans', 'Noto Sans TC': 'notosans', 'Noto Sans JP': 'notosans', 'Noto Sans Thai': 'notosans',
    'Noto Sans Hebrew': 'notosans',
    'IBM Plex Sans': 'plex', 'JetBrains Mono': 'plexmono', 'Space Mono': 'plexmono', 'Fira Code': 'plexmono', 'Roboto Mono': 'plexmono', 'Share Tech Mono': 'plexmono', 'VT323': 'plexmono',
    'Nunito': 'rubik', 'Nunito Sans': 'rubik', 'Rubik': 'rubik', 'Varela Round': 'rubik',
    'Quicksand': 'lemonada', 'Fredoka': 'baloo', 'Baloo 2': 'baloo', 'Comic Neue': 'marhey', 'Patrick Hand': 'marhey',
    'Orbitron': 'changa', 'Exo': 'changa', 'Exo 2': 'changa', 'Russo One': 'changa', 'Chakra Petch': 'changa', 'Syne': 'changa', 'Syncopate': 'changa',
    'Press Start 2P': 'pixelfa',
    'Josefin Sans': 'zain', 'Poiret One': 'zain', 'Didact Gothic': 'almarai', 'Archivo': 'almarai', 'Barlow': 'almarai',
    'Playfair Display': 'markazi', 'Playfair Display SC': 'markazi', 'Lora': 'markazi', 'Libre Bodoni': 'markazi', 'Bodoni Moda': 'markazi',
    'Cormorant Garamond': 'mirza', 'Cormorant': 'mirza', 'Cormorant Infant': 'mirza', 'Cinzel': 'mirza',
    'Libre Baskerville': 'amiri', 'Crimson Pro': 'amiri', 'Crimson Text': 'amiri', 'Newsreader': 'amiri',
    'EB Garamond': 'scheherazade', 'Noto Naskh Arabic': 'naskh', 'Merriweather': 'naskh', 'Source Serif 4': 'naskh', 'Noto Serif JP': 'naskh', 'Noto Serif TC': 'naskh',
    'Abril Fatface': 'rakkas', 'Righteous': 'rakkas', 'Calistoga': 'rakkas',
    'Bebas Neue': 'jomhuria', 'Anton': 'jomhuria', 'Barlow Condensed': 'jomhuria',
    'Caveat': 'aref', 'Kalam': 'aref', 'Amatic SC': 'katibeh', 'Great Vibes': 'vibes',
}

# قلم‌های تزئینی/دست‌نویس که برای متنِ بلند نیستند
DECORATIVE = {'pixelfa', 'lalezar', 'rakkas', 'jomhuria', 'katibeh', 'aref', 'vibes', 'marhey', 'lemonada', 'baloo', 'changa', 'reem', 'kufam', 'messiri', 'scheherazade', 'lateef', 'mirza'}
BODY_FALLBACK = 'vazirmatn'

# اگر قلمِ تازه‌ای در دادهٔ مخزن آمد که این‌جا نیست: از دستهٔ گوگل‌فونتس حدس بزن
CATEGORY_GUESS = {'sans serif': 'vazirmatn', 'serif': 'markazi', 'display': 'rakkas', 'handwriting': 'aref', 'monospace': 'plexmono'}


def persian_font(latin: str, category: str = '') -> str:
    """کلیدِ قلمِ فارسی برای یک قلمِ لاتین؛ ناشناخته ⇒ از دستهٔ گوگل‌فونتس، وگرنه وزیرمتن."""
    key = PERSIAN_OF.get((latin or '').strip())
    if key:
        return key
    return CATEGORY_GUESS.get((category or '').strip().lower(), 'vazirmatn')


def persian_pair(heading: str, body: str, category: str = '') -> tuple[str, str]:
    """(قلمِ تیتر، قلمِ متن) فارسی؛ قلمِ متنِ تزئینی با یک قلمِ خوانا عوض می‌شود."""
    h = persian_font(heading, category)
    b = persian_font(body, category)
    if b in DECORATIVE:
        b = BODY_FALLBACK
    return h, b


def label(key: str) -> str:
    from .. import theme
    return theme.FONTS.get(key, {}).get('label', key)
