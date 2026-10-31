# -*- coding: utf-8 -*-
"""نمادهای خطیِ درون‌خطی (SVG) — بی‌وابستگی به CDN یا فونتِ نمادین؛ هم در پنل و هم در خروجی."""

ICONS = {
    'star': '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17.1 6.6 20l1-6.1L3.200 9.500l6.100-.9z"/>',
    'heart': '<path d="M20.800 5.600a5.500 5.500 0 0 0-7.800 0L12 6.700l-1-1.100a5.500 5.500 0 1 0-7.800 7.800L12 22l8.800-8.600a5.500 5.500 0 0 0 0-7.800z"/>',
    'zap': '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    'shield': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
    'check': '<path d="M20 6L9 17l-5-5"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'phone': '<path d="M22 16.900v3a2 2 0 0 1-2.200 2 19.800 19.800 0 0 1-8.600-3.100 19.500 19.500 0 0 1-6-6A19.800 19.800 0 0 1 2.100 4.200 2 2 0 0 1 4.100 2h3a2 2 0 0 1 2 1.700c.1 1 .4 1.900.7 2.800a2 2 0 0 1-.5 2.100L8.100 9.900a16 16 0 0 0 6 6l1.300-1.300a2 2 0 0 1 2.100-.4c.9.300 1.800.6 2.800.7a2 2 0 0 1 1.700 2z"/>',
    'mail': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    'map-pin': '<path d="M21 10c0 7-9 12-9 12s-9-5-9-12a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    'users': '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.900"/><path d="M16 3.100a4 4 0 0 1 0 7.800"/>',
    'cart': '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.700 13.400a2 2 0 0 0 2 1.600h9.700a2 2 0 0 0 2-1.600L23 6H6"/>',
    'gift': '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/><path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/><path d="M7.500 8a2.500 2.500 0 0 1 0-5C11 3 12 8 12 8s1-5 4.500-5a2.500 2.500 0 0 1 0 5"/>',
    'truck': '<rect x="1" y="4" width="15" height="13" rx="1"/><path d="M16 9h4l3 4v4h-7z"/><circle cx="6" cy="19" r="2"/><circle cx="19" cy="19" r="2"/>',
    'tag': '<path d="M20.600 13.400l-7.200 7.200a2 2 0 0 1-2.800 0L2 12V2h10l8.600 8.600a2 2 0 0 1 0 2.800z"/><circle cx="7" cy="7" r="1"/>',
    'award': '<circle cx="12" cy="8" r="6"/><path d="M8.200 13.200L7 22l5-3 5 3-1.200-8.800"/>',
    'book': '<path d="M4 19.500A2.500 2.500 0 0 1 6.500 17H20"/><path d="M6.500 2H20v20H6.500A2.500 2.500 0 0 1 4 19.500v-15A2.500 2.500 0 0 1 6.500 2z"/>',
    'camera': '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    'chat': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    'globe': '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20z"/>',
    'home': '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    'leaf': '<path d="M11 20A7 7 0 0 1 9.800 6.100C15.500 5 17 4.500 19 2c1 2 2 4.200 2 8 0 5.500-4.800 10-10 10z"/><path d="M2 21c0-3 1.900-5.400 5.100-6"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="M19.400 15a1.700 1.700 0 0 0 .3 1.800l.1.100a2 2 0 1 1-2.800 2.800l-.1-.1a1.700 1.700 0 0 0-2.800 1.200V21a2 2 0 0 1-4 0v-.1a1.700 1.700 0 0 0-2.900-1.200l-.1.100a2 2 0 1 1-2.800-2.800l.1-.1a1.700 1.700 0 0 0-1.200-2.900H3a2 2 0 0 1 0-4h.1a1.700 1.700 0 0 0 1.200-2.900l-.1-.1a2 2 0 1 1 2.800-2.800l.1.100a1.700 1.700 0 0 0 1.900.3h.1a1.700 1.700 0 0 0 1-1.500V3a2 2 0 0 1 4 0v.1a1.700 1.700 0 0 0 2.900 1.200l.1-.1a2 2 0 1 1 2.800 2.800l-.1.100a1.700 1.700 0 0 0-.3 1.900v.1a1.700 1.700 0 0 0 1.500 1H21a2 2 0 0 1 0 4h-.1a1.700 1.700 0 0 0-1.500 1z"/>',
    'sun': '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.200 4.200l1.400 1.400M18.400 18.400l1.400 1.400M1 12h2M21 12h2M4.200 19.800l1.400-1.400M18.400 5.600l1.400-1.400"/>',
    'smile': '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.500 2 4 2 4-2 4-2"/><path d="M9 9h.01M15 9h.01"/>',
    'instagram': '<rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="4"/><path d="M17.500 6.500h.01"/>',
    'telegram': '<path d="M21.500 3.500L2.500 11l6 2.200 2.300 6.300 3.300-4.200 5 3.700z"/><path d="M8.500 13.200L21.500 3.500 11 15.500"/>',
    'whatsapp': '<path d="M21 11.500a8.400 8.400 0 0 1-12.400 7.400L3 21l2.100-5.600A8.400 8.400 0 1 1 21 11.500z"/><path d="M9 9c0 3.500 2.500 6 6 6l1-1.500-2-1-1 .7c-.8-.4-1.500-1.100-2-2l.7-1-1-2z"/>',
    'arrow': '<path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/>',
    'layout': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18"/>',
    'columns': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
    'column': '<rect x="7" y="4" width="10" height="16" rx="2"/>',
    'heading': '<path d="M6 4v16M18 4v16M6 12h12"/>',
    'text': '<path d="M4 6h16M4 12h16M4 18h10"/>',
    'image': '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    'button': '<rect x="3" y="8" width="18" height="8" rx="4"/><path d="M9 12h6"/>',
    'video': '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="M17 10l5-3v10l-5-3"/>',
    'spacer': '<path d="M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4"/>',
    'divider': '<path d="M3 12h18"/>',
    'gallery': '<rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="8" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/>',
    'code': '<path d="M9 8l-5 4 5 4M15 8l5 4-5 4"/>',
    'hero': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10h8M9 14h6"/>',
    'cards': '<rect x="3" y="5" width="5" height="14" rx="1"/><rect x="10" y="5" width="5" height="14" rx="1"/><rect x="17" y="5" width="4" height="14" rx="1"/>',
    'price': '<path d="M12 2v20"/><path d="M17 6H9.500a3.500 3.500 0 0 0 0 7h5a3.500 3.500 0 0 1 0 7H6"/>',
    'quote': '<path d="M3 21c3 0 7-1 7-8V5H3v8h4c0 4-2 6-4 6z"/><path d="M14 21c3 0 7-1 7-8V5h-7v8h4c0 4-2 6-4 6z"/>',
    'help': '<circle cx="12" cy="12" r="10"/><path d="M9.100 9a3 3 0 0 1 5.800 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    'megaphone': '<path d="M3 11v3l14 5V6z"/><path d="M17 8a4 4 0 0 1 0 8"/><path d="M7 15v4a2 2 0 0 0 4 0v-3"/>',
    'map': '<path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4z"/><path d="M8 2v16M16 6v16"/>',
    'list': '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    'detail': '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
}
# نمادهای مخصوصِ کتابخانهٔ پنل در انتخابگرِ کاربر نمی‌آیند
PICKABLE = [k for k in ICONS if k not in {
    'layout', 'columns', 'column', 'heading', 'text', 'image', 'button', 'spacer', 'divider', 'gallery', 'code', 'hero',
    'cards', 'detail', 'list'}]


def svg(name, size=None):
    body = ICONS.get(name) or ICONS['star']
    sz = ' width="%d" height="%d"' % (size, size) if size else ''
    return ('<svg class="nb-svg" viewBox="0 0 24 24"%s fill="none" stroke="currentColor" stroke-width="1.800" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>' % (sz, body))
