"""
Линейные иконки в стиле Hugeicons (как в приложении): сетка 24, линия 1.8, скруглённые концы.
Инлайн-SVG — без внешних шрифтов и скриптов. Здесь же — соответствие FeatureIcon / PerkIcon мобилки.
"""
from django.utils.html import format_html
from django.utils.safestring import mark_safe

P = {
    # навигация
    'home': '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
    'chart': '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="m7 15 4-4 3 3 6-6"/>',
    'bars': '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>',
    'queue': '<rect x="3" y="4" width="18" height="5" rx="2"/><rect x="3" y="12" width="18" height="5" rx="2"/><path d="M7 21h10"/>',
    'receipt': '<path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z"/><path d="M9 8h6"/><path d="M9 12h6"/>',
    'card': '<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M2.5 10h19"/><path d="M6.5 15h3"/>',
    'users': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18.5 14.5a6.5 6.5 0 0 1 3 5.5"/>',
    'user': '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    'grid': '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>',
    'medal': '<circle cx="12" cy="15" r="6"/><path d="M8.5 10 5 3h4l3 6"/><path d="M15.5 10 19 3h-4l-3 6"/><path d="m12 12.5.9 1.8 2 .3-1.45 1.4.35 2-1.8-.95-1.8.95.35-2L9.1 14.6l2-.3z"/>',
    'news': '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 8h10"/><path d="M7 12h6"/><path d="M7 16h8"/>',
    'megaphone': '<path d="M3 10v4a1 1 0 0 0 1 1h3l8 5V4L7 9H4a1 1 0 0 0-1 1z"/><path d="M19 9a4 4 0 0 1 0 6"/>',
    'chat': '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/><path d="M8.5 11h7"/><path d="M8.5 14.5h4"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    'shield': '<path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    'history': '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    'logout': '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l5-5-5-5"/><path d="M15 12H4"/>',
    'bell': '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    # действия
    'check': '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    'close': '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    'edit': '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    'qr': '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14 14h3v3h-3z"/><path d="M20 14v.01"/><path d="M20 20h-3"/><path d="M14 20v.01"/>',
    'camera': '<path d="M3 8a2 2 0 0 1 2-2h2l2-2.5h6L17 6h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="4"/>',
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.9 4.9 1.4 1.4"/><path d="m17.7 17.7 1.4 1.4"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m4.9 19.1 1.4-1.4"/><path d="m17.7 6.3 1.4-1.4"/>',
    'moon': '<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z"/>',
    'plus': '<path d="M12 5v14"/><path d="M5 12h14"/>',
    'minus': '<path d="M5 12h14"/>',
    'trash': '<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4h6v3"/>',
    'eye': '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    'eye-off': '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1"/><path d="M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    'drag': '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
    'upload': '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    'download': '<path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    'send': '<path d="M21 3 10 14"/><path d="m21 3-7 18-4-7-7-4z"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'calendar': '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18"/><path d="M8 3v4"/><path d="M16 3v4"/>',
    'arrow-left': '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
    'arrow-right': '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    'chevron-right': '<path d="m9 6 6 6-6 6"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'filter': '<path d="M4 5h16l-6 7.5V19l-4 2v-8.5z"/>',
    'lock': '<rect x="4" y="10" width="16" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    'unlock': '<rect x="4" y="10" width="16" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 7.7-1.5"/>',
    'cash': '<rect x="2.5" y="6" width="19" height="12" rx="3"/><circle cx="12" cy="12" r="2.5"/><path d="M6 9.5v5"/><path d="M18 9.5v5"/>',
    'phone': '<path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    'star': '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
    'warning': '<path d="M12 3 2 20h20z"/><path d="M12 10v4"/><path d="M12 17.5v.01"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5v.01"/>',
    'note': '<path d="M5 3h10l4 4v14H5z"/><path d="M15 3v4h4"/><path d="M8.5 12h7"/><path d="M8.5 16h5"/>',
    'image': '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    'globe': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18"/><path d="M12 3a14 14 0 0 0 0 18"/>',
    'link': '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    'story': '<rect x="6" y="3" width="12" height="18" rx="3"/><path d="M3 6v12"/><path d="M21 6v12"/>',
    'sparkle': '<path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/><path d="m12 8 1.5 2.5L16 12l-2.5 1.5L12 16l-1.5-2.5L8 12l2.5-1.5z"/>',
    'location': '<path d="M12 21s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    'key': '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9"/><path d="m17 6 3 3"/><path d="m15 8 2 2"/>',
    'refresh': '<path d="M20 11a8 8 0 0 0-14.6-4.5L3 9"/><path d="M3 4v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.5L21 15"/><path d="M21 20v-5h-5"/>',
    'undo': '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    'menu': '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/>',
    # FeatureIcon (что входит)
    'view': '<path d="m2 19 6-8 4 5 3-3 7 6"/><circle cx="17" cy="6" r="2"/>',
    'bed': '<path d="M3 18V6"/><path d="M3 14h18v4"/><path d="M21 14v-3a3 3 0 0 0-3-3h-7v6"/><circle cx="7" cy="10.5" r="1.8"/>',
    'people': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18.5 14.5a6.5 6.5 0 0 1 3 5.5"/>',
    'area': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 9h3"/><path d="M4 14h3"/><path d="M9 4v3"/><path d="M14 4v3"/>',
    'wifi': '<path d="M2 8.5a15 15 0 0 1 20 0"/><path d="M5.5 12a10 10 0 0 1 13 0"/><path d="M9 15.5a5 5 0 0 1 6 0"/><path d="M12 19v.01"/>',
    'breakfast': '<path d="M4 10h13v4a6 6 0 0 1-6 6h-1a6 6 0 0 1-6-6z"/><path d="M17 11h1.5a2.5 2.5 0 0 1 0 5H16"/><path d="M8 3v3"/><path d="M12 3v3"/>',
    'terrace': '<path d="M3 21V11l9-7 9 7v10"/><path d="M3 15h18"/><path d="M8 15v6"/><path d="M16 15v6"/>',
    'pool': '<path d="M2 18c2 1.3 3.5 1.3 5 0s3.5-1.3 5 0 3.5 1.3 5 0 3-1.3 5 0"/><path d="M8 15V5a2 2 0 0 1 4 0"/><path d="M16 15V5a2 2 0 0 0-4 0"/><path d="M8 9h8"/>',
    'time': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'towel': '<path d="M5 4h14v16H5z"/><path d="M5 8h14"/><path d="M9 14h6"/>',
    'tea': '<path d="M4 9h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M16 10h1.5a2.5 2.5 0 0 1 0 5H16"/><path d="M3 21h14"/><path d="M9 3c-1 1 1 2 0 3"/>',
    'music': '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    'fire': '<path d="M12 21a7 7 0 0 0 7-7c0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-4-2 2-5 5-5 8a7 7 0 0 0 7 7z"/>',
    'chef': '<path d="M7 14a4 4 0 0 1-.8-7.9A5 5 0 0 1 12 3a5 5 0 0 1 5.8 3.1A4 4 0 0 1 17 14"/><path d="M7 14v6h10v-6"/><path d="M7 17h10"/>',
    'drink': '<path d="M5 4h14l-7 8z"/><path d="M12 12v8"/><path d="M8 20h8"/>',
    'water': '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    'gym': '<path d="M6 7v10"/><path d="M18 7v10"/><path d="M3 10v4"/><path d="M21 10v4"/><path d="M6 12h12"/>',
    'trainer': '<circle cx="12" cy="5" r="2"/><path d="M8 21l2-7-3-3 5-3 3 3 3 1"/><path d="M14 14l2 7"/>',
    'bath': '<path d="M3 12h18v3a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5z"/><path d="M6 12V5a2 2 0 0 1 4 0"/><path d="M7 20l-1 2"/><path d="M17 20l1 2"/>',
    'nature': '<path d="M12 21v-8"/><path d="M12 13c-4 0-7-3-7-8 4 0 7 3 7 8z"/><path d="M12 15c3 0 6-2.5 6-7-3.5 0-6 2.5-6 7z"/>',
    'cold': '<path d="M12 2v20"/><path d="m4 7 16 10"/><path d="M20 7 4 17"/><path d="m9 4 3 3 3-3"/><path d="m9 20 3-3 3 3"/>',
    'warm': '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 11v6"/>',
    'tv': '<rect x="3" y="5" width="18" height="12" rx="2.5"/><path d="M8 21h8"/><path d="M12 17v4"/>',
    'flower': '<circle cx="12" cy="10" r="2.5"/><path d="M12 7.5a2.5 2.5 0 1 1 2.4-3.2A2.5 2.5 0 1 1 16.5 9a2.5 2.5 0 1 1-1.6 4 2.5 2.5 0 1 1-5.8 0 2.5 2.5 0 1 1-1.6-4 2.5 2.5 0 1 1 2.1-4.7A2.5 2.5 0 0 1 12 7.5z"/><path d="M12 15v7"/>',
    # PerkIcon (привилегии)
    'cashback': '<circle cx="12" cy="12" r="9"/><path d="M15 9.5a3 3 0 0 0-3-1.5c-1.7 0-3 .9-3 2s1.3 1.7 3 2 3 .9 3 2-1.3 2-3 2a3 3 0 0 1-3-1.5"/><path d="M12 6v2"/><path d="M12 16v2"/>',
    'birthday': '<path d="M4 21h16"/><path d="M5 21v-7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v7"/><path d="M5 16c1.5 1 3 1 4.5 0s3-1 4.5 0 3 1 5 0"/><path d="M12 12V8"/><path d="M12 5.5c-.8-.8-.8-2 0-2.5.8.5.8 1.7 0 2.5z"/>',
    'earlyCheckIn': '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l-2 2"/><path d="M5 3 2 6"/><path d="m19 3 3 3"/>',
    'beach': '<path d="M3 20c3-1.5 6-1.5 9 0s6 1.5 9 0"/><path d="M13 16 9 4"/><path d="M4 8a9 9 0 0 1 13-3.5z"/>',
    'parking': '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/>',
    'lateCheckOut': '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2"/><path d="M16 3h5v5"/>',
    'upgrade': '<path d="M12 20V6"/><path d="m6 11 6-6 6 6"/><path d="M5 20h14"/>',
    'spa': '<path d="M12 20c-4.5 0-8-3-8-7 3 0 6 1.5 8 4 2-2.5 5-4 8-4 0 4-3.5 7-8 7z"/><path d="M12 17c-2-2.5-2-6 0-10 2 4 2 7.5 0 10z"/>',
    'transfer': '<path d="M4 16V8a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v8"/><path d="M3 16h18v2H3z"/><circle cx="7.5" cy="19" r="1.5"/><circle cx="16.5" cy="19" r="1.5"/><path d="M4 11h16"/>',
    'concierge': '<path d="M4 17h16"/><path d="M5 17a7 7 0 0 1 14 0"/><path d="M12 10V8"/><path d="M10 8h4"/><path d="M3 20h18"/>',
    'villa': '<path d="M3 21V10l9-6 9 6v11"/><path d="M9 21v-6h6v6"/><path d="M3 21h18"/>',
    'events': '<path d="m4 20 5-14 9 9z"/><path d="M14 4v2"/><path d="M19 9h2"/><path d="m17 5 1.5-1.5"/><path d="M9 11l4 4"/>',
    'gift': '<rect x="3" y="8" width="18" height="5" rx="1.5"/><path d="M5 13v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7"/><path d="M12 8v13"/><path d="M12 8c-2-4-6-4-6-1.5S9.5 8 12 8c2.5 0 6 1 6-1.5S14 4 12 8z"/>',
}

# FeatureIcon / PerkIcon, которые рисуются общим контуром
ALIASES = {'sun': 'sun'}


def svg(name, size=20, cls='ic'):
    body = P.get(ALIASES.get(name, name)) or P['sparkle']
    return mark_safe(
        f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')


def bubble(name, size=20, tone=''):
    """Иконка в круглой подложке accentSoft — как в приложении."""
    return format_html('<span class="ic-bubble {}">{}</span>', tone, svg(name, size))
