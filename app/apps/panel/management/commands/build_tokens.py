"""
Генерация токенов дизайна из static/design/tokens.json (ТЗ §7.4 «Технически»):
  - static/panel/tokens.css      — CSS-переменные админки (светлая/тёмная тема);
  - static/design/app_colors.dart — AppColors / AppRadius / AppSpacing / AppMotion / AppTierGradients для мобилки.

    python manage.py build_tokens          # записать файлы
    python manage.py build_tokens --check  # проверить, что сгенерированные файлы актуальны (CI)
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

HEADER = 'СГЕНЕРИРОВАНО командой `manage.py build_tokens` из static/design/tokens.json — не править вручную.'


def static_root():
    return Path(settings.BASE_DIR) / 'static'


def load_tokens(path=None):
    path = path or static_root() / 'design' / 'tokens.json'
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _kebab(name):
    out = ''
    for ch in name:
        out += ('-' + ch.lower()) if ch.isupper() else ch
    return out


def _theme_vars(colors, alpha):
    lines = []
    for name, value in colors.items():
        lines.append(f'  --{_kebab(name)}: {value};')
        r, g, b = _rgb(value)
        lines.append(f'  --{_kebab(name)}-rgb: {r}, {g}, {b};')
    for name, a in alpha.items():
        lines.append(f'  --{name}: rgba(var(--ink-rgb), {a});')
    return lines


def render_css(t):
    c = t['colors']
    alpha = c.get('inkAlpha', {})
    font = t['font']
    out = [f'/* {HEADER} */', ':root {', '  color-scheme: light;']
    out += _theme_vars(c['light'], alpha)
    for i, col in enumerate(c['chart']['light'], 1):
        out.append(f'  --series-{i}: {col};')
    out.append(f"  --font: '{font['family']}', {font['fallback']};")
    for name, s in font['scale'].items():
        k = _kebab(name)
        out.append(f'  --fs-{k}: {s["size"]}px;')
        out.append(f'  --fw-{k}: {s["weight"]};')
        out.append(f'  --ls-{k}: {s["letterSpacing"]}px;')
    for name, v in t['spacing'].items():
        out.append(f'  --sp-{name}: {v}px;')
    for name, v in t['radius'].items():
        out.append(f'  --r-{name}: {v}px;')
    for name, v in t['motion'].items():
        out.append(f'  --motion-{name}: {v if name == "easing" else str(v) + "ms"};')
    for name, v in t['size'].items():
        out.append(f'  --size-{_kebab(name)}: {v}px;')
    for tier, stops in t['tiers'].items():
        out.append(f'  --tier-{tier}: linear-gradient(135deg, {stops[0]} 0%, {stops[1]} 55%, {stops[2]} 100%);')
        for i, s in enumerate(stops):
            out.append(f'  --tier-{tier}-{i}: {s};')
    out.append('}')

    dark = _theme_vars(c['dark'], alpha) + [f'  --series-{i}: {col};' for i, col in enumerate(c['chart']['dark'], 1)]
    out.append('@media (prefers-color-scheme: dark) {')
    out.append('  :root:not([data-theme="light"]) {')
    out.append('    color-scheme: dark;')
    out += ['  ' + line for line in dark]
    out.append('  }')
    out.append('}')
    out.append(':root[data-theme="dark"] {')
    out.append('  color-scheme: dark;')
    out += dark
    out.append('}')
    # Явные темы для фрагментов (рамка телефона «как в приложении» переключается независимо от админки)
    light = _theme_vars(c['light'], alpha)
    out.append('.theme-light {')
    out.append('  color-scheme: light;')
    out += light
    out.append('}')
    out.append('.theme-dark {')
    out.append('  color-scheme: dark;')
    out += dark
    out.append('}')
    out.append('@media (prefers-reduced-motion: reduce) {')
    out.append('  :root { --motion-fast: 0ms; --motion-base: 0ms; --motion-slow: 0ms; }')
    out.append('}')
    return '\n'.join(out) + '\n'


def _dart_color(hex_color, alpha=1.0):
    a = round(alpha * 255)
    return f'Color(0x{a:02X}{hex_color.lstrip("#").upper()})'


def _dart_num(v):
    return f'{v}' if isinstance(v, float) else f'{v}.0' if isinstance(v, int) else str(v)


def render_dart(t):
    c = t['colors']
    names = list(c['light'].keys())
    alpha = c.get('inkAlpha', {})
    out = [f'// {HEADER}', "import 'package:flutter/material.dart';", '']
    out.append('@immutable')
    out.append('class AppColors {')
    out.append('  const AppColors._({')
    for n in names:
        out.append(f'    required this.{n},')
    for n in alpha:
        out.append(f'    required this.{n},')
    out.append('  });')
    out.append('')
    for n in names:
        out.append(f'  final Color {n};')
    for n in alpha:
        out.append(f'  final Color {n};')
    out.append('')
    for theme in ('light', 'dark'):
        out.append(f'  static const {theme} = AppColors._(')
        for n in names:
            out.append(f'    {n}: {_dart_color(c[theme][n])},')
        for n, a in alpha.items():
            out.append(f'    {n}: {_dart_color(c[theme]["ink"], a)},')
        out.append('  );')
        out.append('')
    out.append('  static AppColors of(Brightness b) => b == Brightness.dark ? dark : light;')
    out.append('}')
    out.append('')
    out.append('abstract final class AppRadius {')
    for n, v in t['radius'].items():
        out.append(f'  static const double {n} = {_dart_num(v)};')
    out.append('}')
    out.append('')
    out.append('abstract final class AppSpacing {')
    for n, v in t['spacing'].items():
        out.append(f'  static const double {n} = {_dart_num(v)};')
    out.append('}')
    out.append('')
    out.append('abstract final class AppMotion {')
    for n, v in t['motion'].items():
        if n == 'easing':
            continue
        out.append(f'  static const Duration {n} = Duration(milliseconds: {v});')
    out.append('}')
    out.append('')
    out.append('abstract final class AppTierGradients {')
    for tier, stops in t['tiers'].items():
        cols = ', '.join(_dart_color(s) for s in stops)
        out.append(f'  static const LinearGradient {tier} = LinearGradient(')
        out.append('    begin: Alignment.topLeft, end: Alignment.bottomRight,')
        out.append(f'    colors: [{cols}],')
        out.append('  );')
    out.append('}')
    return '\n'.join(out) + '\n'


def outputs(tokens):
    root = static_root()
    return {
        root / 'panel' / 'tokens.css': render_css(tokens),
        root / 'design' / 'app_colors.dart': render_dart(tokens),
    }


class Command(BaseCommand):
    help = 'Генерирует tokens.css (админка) и app_colors.dart (мобилка) из static/design/tokens.json'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true', help='Только проверить актуальность файлов')

    def handle(self, *args, **opts):
        files = outputs(load_tokens())
        stale = []
        for path, content in files.items():
            current = path.read_text(encoding='utf-8') if path.exists() else None
            if current == content:
                continue
            if opts['check']:
                stale.append(str(path))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            self.stdout.write(f'записан {path}')
        if stale:
            raise CommandError('Токены устарели, запустите build_tokens: ' + ', '.join(stale))
        self.stdout.write(self.style.SUCCESS('Токены актуальны'))
