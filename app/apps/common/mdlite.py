"""
Минимальный Markdown → HTML для своих страниц (ТЗ на контент): заголовки #–###, абзацы, **жирный**,
списки «- » / «1. » / «- [ ] », таблицы с «|». Источник — наши файлы в репозитории, не ввод пользователей,
но текст всё равно экранируется.
"""
import re

from django.utils.html import escape

_BOLD = re.compile(r'\*\*(.+?)\*\*')


def _inline(text):
    return _BOLD.sub(r'<strong>\1</strong>', escape(text))


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def render(md):
    """→ (title, html). title — первый заголовок «# …»."""
    title, out, i = '', [], 0
    lines = md.splitlines()
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith('# '):
            title = title or line[2:].strip()
            i += 1
            continue
        m = re.match(r'(#{2,3}) (.+)', line)
        if m:
            tag = 'h2' if len(m.group(1)) == 2 else 'h3'
            out.append(f'<{tag}>{_inline(m.group(2))}</{tag}>')
            i += 1
            continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                rows.append(_cells(lines[i]))
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(set(c) <= set('-: ') for c in r)]
            html = '<div class="table"><table><thead><tr>' + ''.join(f'<th>{_inline(c)}</th>' for c in head)
            html += '</tr></thead><tbody>' + ''.join(
                '<tr>' + ''.join(f'<td>{_inline(c)}</td>' for c in r) + '</tr>' for r in body)
            out.append(html + '</tbody></table></div>')
            continue
        if re.match(r'(- |\d+\. )', line):
            ordered = bool(re.match(r'\d+\. ', line))
            items = []
            while i < len(lines) and re.match(r'(- |\d+\. )', lines[i]):
                text = re.sub(r'^(- |\d+\. )', '', lines[i].rstrip())
                if text.startswith('[ ] '):
                    items.append(f'<li class="check"><label><input type="checkbox"> {_inline(text[4:])}</label></li>')
                else:
                    items.append(f'<li>{_inline(text)}</li>')
                i += 1
            tag = 'ol' if ordered else 'ul'
            out.append(f'<{tag}>' + ''.join(items) + f'</{tag}>')
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r'(#|\||- |\d+\. )', lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f'<p>{_inline(" ".join(para))}</p>')
    return title, ''.join(out)
