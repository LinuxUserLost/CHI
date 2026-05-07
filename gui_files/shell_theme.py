"""
shell_theme.py — Guichi Shell Theme Loader
Startup-only theme resolution. Called once at module level in shell_gui.py.
Never raises. Falls back to dark_neutral on any failure.
"""

import os
import json
import logging

_log = logging.getLogger(__name__)

# ── Hardcoded fallback — always available, no file required ─────────────────
# This is the last-resort dict. It must never reference any external file.
# Values match the original hardcoded shell_gui constants exactly.

_FALLBACK_DARK_NEUTRAL = {
    # Surfaces
    "app_bg":          "#1e1e1e",
    "topbar_bg":       "#333333",
    "sidebar_bg":      "#2a2a2a",
    "content_bg":      "#1e1e1e",
    "panel_bg":        "#2e2e2e",
    # Text
    "text_main":       "#c0c0c0",
    "text_muted":      "#909090",
    "text_active":     "#d0d0d0",
    "text_on_accent":  "#ffffff",
    "text_error":      "#e05050",
    "text_warn":       "#e8a838",
    "text_code":       "#40c0c0",
    # Buttons / states
    "button_bg":       "#333333",
    "button_hover":    "#444444",
    "button_active":   "#ffffff",
    "button_disabled": "#555555",
    "accent":          "#40c0c0",
    "accent_hover":    "#55d5d5",
    # Structure
    "border":          "#444444",
    "divider":         "#3a3a3a",
    "focus_ring":      "#40c0c0",
    # Sizing
    "sidebar_width":   240,
    "topbar_height":   32,
    "button_height":   28,
    "pad_x":           6,
    "pad_y":           3,
    "font_size_main":  10,
    "font_size_small": 8,
}

DEFAULT_THEME = "dark_neutral"

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_THEMES_PATH = os.path.join(_THIS_DIR, "themes", "themes.json")

_themes_cache = None


def invalidate_themes_cache():
    """Clear the cached themes.json data so the next call re-reads from disk."""
    global _themes_cache
    _themes_cache = None


def _load_themes_file():
    """Load master themes dict from themes.json. Returns dict or None on any failure. Result is cached."""
    global _themes_cache
    if _themes_cache is not None:
        return _themes_cache
    if not os.path.isfile(_THEMES_PATH):
        _log.warning("themes.json not found: %s — using fallback", _THEMES_PATH)
        return None
    try:
        with open(_THEMES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _themes_cache = data
            return _themes_cache
        _log.warning("themes.json has unexpected format — using fallback")
        return None
    except (json.JSONDecodeError, OSError) as e:
        _log.warning("failed to load themes.json: %s — using fallback", e)
        return None


def _load_config_theme_name():
    """Read current_theme from guichi config. Returns string or None on any failure."""
    try:
        import guichi
        config = guichi.load_config()
        name = config.get("current_theme")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    except Exception as e:
        _log.warning("could not read config: %s — using default theme name", e)
        return None


def list_themes():
    """
    Return list of available theme names from themes.json.
    Falls back to [DEFAULT_THEME] on any failure — never raises.
    """
    themes = _load_themes_file()
    if themes:
        return list(themes.keys())
    return [DEFAULT_THEME]


def get_theme():
    """
    Resolve and return a flat token dict for the current theme.

    Resolution order:
      1. Read theme name from guichi config (current_theme key).
      2. Load themes.json from guichi_files/themes/.
      3. Look up named theme in loaded dict.
      4. Fill any missing tokens from hardcoded dark_neutral fallback.

    Never raises. Any failure at any step falls back gracefully.
    """
    theme_name = _load_config_theme_name() or DEFAULT_THEME
    return get_named_theme(theme_name)


def get_named_theme(theme_name=None):
    """
    Resolve and return a flat token dict for a specific theme name.
    Falls back gracefully to DEFAULT_THEME, then the hardcoded fallback.
    Never raises.
    """
    theme_name = theme_name or DEFAULT_THEME
    themes = _load_themes_file()

    theme = None
    if themes is not None:
        theme = themes.get(theme_name)
        if theme is None:
            _log.warning("theme '%s' not found — using dark_neutral fallback", theme_name)
            theme = themes.get(DEFAULT_THEME)
        if theme is None:
            _log.warning("dark_neutral also missing from themes.json — using hardcoded fallback")

    if theme is None:
        return dict(_FALLBACK_DARK_NEUTRAL)

    # Start from fallback so any missing token is covered
    resolved = dict(_FALLBACK_DARK_NEUTRAL)
    resolved.update(theme)

    # Warn about tokens the theme file did not define
    missing = [k for k in _FALLBACK_DARK_NEUTRAL if k not in theme]
    if missing:
        _log.warning("theme '%s' missing tokens (fallback used): %s", theme_name, missing)

    # Validate token types match the fallback schema
    for key, fallback_val in _FALLBACK_DARK_NEUTRAL.items():
        resolved_val = resolved.get(key)
        if isinstance(fallback_val, str) and not (isinstance(resolved_val, str) and resolved_val.startswith("#")):
            _log.warning("theme '%s' token '%s' expected a hex color string, got: %r", theme_name, key, resolved_val)
        elif isinstance(fallback_val, int) and not isinstance(resolved_val, int):
            _log.warning("theme '%s' token '%s' expected int, got: %r", theme_name, key, resolved_val)

    return resolved
