// СГЕНЕРИРОВАНО командой `manage.py build_tokens` из static/design/tokens.json — не править вручную.
import 'package:flutter/material.dart';

@immutable
class AppColors {
  const AppColors._({
    required this.accent,
    required this.accentSoft,
    required this.onAccent,
    required this.ink,
    required this.page,
    required this.surface,
    required this.card,
    required this.onCard,
    required this.positive,
    required this.negative,
    required this.warning,
    required this.muted,
    required this.separator,
    required this.fill,
  });

  final Color accent;
  final Color accentSoft;
  final Color onAccent;
  final Color ink;
  final Color page;
  final Color surface;
  final Color card;
  final Color onCard;
  final Color positive;
  final Color negative;
  final Color warning;
  final Color muted;
  final Color separator;
  final Color fill;

  static const light = AppColors._(
    accent: Color(0xFFC6F24E),
    accentSoft: Color(0xFFEFFBD2),
    onAccent: Color(0xFF12140F),
    ink: Color(0xFF12140F),
    page: Color(0xFFF4F6F1),
    surface: Color(0xFFFFFFFF),
    card: Color(0xFF181B17),
    onCard: Color(0xFFF1F3EE),
    positive: Color(0xFF3E7A1F),
    negative: Color(0xFFD64545),
    warning: Color(0xFFB7791F),
    muted: Color(0x8C12140F),
    separator: Color(0x1712140F),
    fill: Color(0x0F12140F),
  );

  static const dark = AppColors._(
    accent: Color(0xFFC6F24E),
    accentSoft: Color(0xFF2A3314),
    onAccent: Color(0xFF12140F),
    ink: Color(0xFFF1F3EE),
    page: Color(0xFF0D0E0C),
    surface: Color(0xFF191B17),
    card: Color(0xFF1F221C),
    onCard: Color(0xFFF1F3EE),
    positive: Color(0xFFA6E36B),
    negative: Color(0xFFFF6B6B),
    warning: Color(0xFFF2C14E),
    muted: Color(0x8CF1F3EE),
    separator: Color(0x17F1F3EE),
    fill: Color(0x0FF1F3EE),
  );

  static AppColors of(Brightness b) => b == Brightness.dark ? dark : light;
}

abstract final class AppRadius {
  static const double card = 18.0;
  static const double photo = 20.0;
  static const double sheet = 28.0;
  static const double chip = 12.0;
  static const double pill = 999.0;
}

abstract final class AppSpacing {
  static const double xs = 4.0;
  static const double s = 8.0;
  static const double m = 14.0;
  static const double l = 18.0;
  static const double xl = 24.0;
}

abstract final class AppMotion {
  static const Duration fast = Duration(milliseconds: 120);
  static const Duration base = Duration(milliseconds: 220);
  static const Duration slow = Duration(milliseconds: 380);
}

abstract final class AppTierGradients {
  static const LinearGradient bronze = LinearGradient(
    begin: Alignment.topLeft, end: Alignment.bottomRight,
    colors: [Color(0xFF4A220F), Color(0xFF99562C), Color(0xFFD9976A)],
  );
  static const LinearGradient silver = LinearGradient(
    begin: Alignment.topLeft, end: Alignment.bottomRight,
    colors: [Color(0xFF3F4A56), Color(0xFF7D8B99), Color(0xFFC3CCD6)],
  );
  static const LinearGradient gold = LinearGradient(
    begin: Alignment.topLeft, end: Alignment.bottomRight,
    colors: [Color(0xFF5E4206), Color(0xFFAE7E17), Color(0xFFE6BF58)],
  );
  static const LinearGradient platinum = LinearGradient(
    begin: Alignment.topLeft, end: Alignment.bottomRight,
    colors: [Color(0xFF232C38), Color(0xFF627488), Color(0xFFB4C2D3)],
  );
  static const LinearGradient diamond = LinearGradient(
    begin: Alignment.topLeft, end: Alignment.bottomRight,
    colors: [Color(0xFF140F3A), Color(0xFF4B3DB0), Color(0xFF8FD8FF)],
  );
}
