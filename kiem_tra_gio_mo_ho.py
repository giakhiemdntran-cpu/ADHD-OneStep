"""Check missing AM/PM before creating one-time reminders.
Only checks raw text; does not infer user intention or modify SQLite.
"""
import re
import unicodedata


def _unaccent(s):
    s = unicodedata.normalize('NFD', str(s or '').lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').replace('đ', 'd')


def gio_mo_ho(text):
    """Return hour 1..12 if user supplied a clock time without explicit AM/PM."""
    t = _unaccent(text)
    if re.search(r'\b(sáng|chiều|tối|đêm|trưa|am|pm)\b', str(text or '').lower()):
        return None
    # A true unqualified clock hour, not a date such as 7/11 or an age.
    pats = [r'(?<!\d)(\d{1,2})\s*(?:gio|h)(?:\s*\d{1,2})?\b',
            r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)']
    for pat in pats:
        for match in re.finditer(pat, t):
            hh = int(match.group(1))
            if 1 <= hh <= 12:
                return hh
    return None


def can_hoi_lai_buoi(text, cmd):
    """Guard reminder creation only; do not interfere with delete or chat intents."""
    if not isinstance(cmd, dict):
        return None
    if cmd.get('intent') not in ('create_task', 'coach_task'):
        return None
    if not (cmd.get('scheduled_at') or cmd.get('scheduled_time')):
        return None
    hour = gio_mo_ho(text)
    if hour is None:
        return None
    return (f'Mình nghe bạn nói {hour} giờ nhưng chưa rõ sáng hay tối. '
            f'Bạn hãy nói lại đầy đủ, ví dụ: nhắc làm bài Toán lúc {hour} giờ sáng ngày mai '
            f'hoặc {hour} giờ tối ngày mai. Mình chưa lưu nhiệm vụ nhé.')
