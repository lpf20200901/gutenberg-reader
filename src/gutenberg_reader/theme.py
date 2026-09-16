"""Colour palettes for the generated reading pages.

Providers
---------

``plain``
    A neutral, GitHub-ish light palette.  The default, and the only one that
    needs nothing from the environment.
``dark`` / ``light``
    The same palette, forced to one appearance.

``dsh``
    Reads the *host application's* live theme, so a reading page can match the
    panel it is displayed in.  Included as an example of the provider pattern
    rather than as something the library depends on: it reads DeepSeek Harness
    settings and the active skin stylesheet from disk, and it degrades to
    ``plain`` when those are absent.

The last one is also a cautionary tale.  Reading the host theme from disk works,
but it is **not** what the original implementation did, and the difference
matters: the reader page originally followed ``prefers-color-scheme`` — the
*operating system* — while the host application had its own explicit setting.
On a light-mode OS with a dark host, the page rendered white inside a dark
panel.  If a host can tell you its theme, ask it; do not infer it from the OS.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Dict, Optional, Tuple

__all__ = ["Palette", "PROVIDERS", "get_palette", "CJK_FONT_STACK", "LATIN_FONT_STACK"]

LATIN_FONT_STACK = '-apple-system, "Segoe UI", "Microsoft YaHei", Roboto, sans-serif'
CJK_FONT_STACK = ('"Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", '
                  '"Noto Sans CJK SC", "Source Han Sans SC", '
                  '-apple-system, "Segoe UI", sans-serif')


@dataclass
class Palette:
    """The colours a reading page needs."""

    bg: str
    bg2: str
    fg: str
    muted: str
    rule: str
    bar_bg: str
    bar_fg: str
    accent: str
    sel_bg: str
    sel_fg: str
    dot: str

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


PLAIN_LIGHT = Palette(
    bg="#ffffff", bg2="#f6f8fa", fg="#24292f", muted="#6e7781", rule="#d8dee4",
    bar_bg="#f6f8fa", bar_fg="#6e7781", accent="#0969da",
    sel_bg="#0969da", sel_fg="#ffffff", dot="#d0d7de",
)

PLAIN_DARK = Palette(
    bg="#0d1117", bg2="#161b22", fg="#c9d1d9", muted="#8b949e", rule="#21262d",
    bar_bg="#161b22", bar_fg="#8b949e", accent="#58a6ff",
    sel_bg="#1f6feb", sel_fg="#ffffff", dot="#30363d",
)

PROVIDERS = ("plain", "dark", "light", "dsh")


def get_palette(name: str = "plain", appearance: Optional[str] = None) -> Tuple[Palette, str]:
    """Return ``(palette, description)`` for a provider name.

    ``appearance`` may be ``"dark"`` or ``"light"`` to override auto-detection.
    Unknown names fall back to ``plain`` rather than raising, so a bad config
    value cannot stop a book from being built.
    """
    name = (name or "plain").lower()

    if name == "dark":
        return PLAIN_DARK, "built-in dark palette"
    if name == "light":
        return PLAIN_LIGHT, "built-in light palette"
    if name == "dsh":
        palette, why = _from_dsh(appearance)
        if palette is not None:
            return palette, why
        return PLAIN_LIGHT, f"plain light (dsh theme unavailable: {why})"

    return PLAIN_LIGHT, "built-in plain palette"


# --------------------------------------------------------------------------
# host-theme provider
# --------------------------------------------------------------------------

def _dsh_home() -> Optional[str]:
    home = os.environ.get("DSH_HOME")
    if home and os.path.isdir(home):
        return home
    guess = os.path.join(os.environ.get("APPDATA", ""), "dsh-desktop", "harness")
    return guess if os.path.isdir(guess) else None


def _read_appearance(home: str) -> Optional[str]:
    """``ui-theme.preference`` from settings.yaml (dark | light | system)."""
    try:
        text = open(os.path.join(home, "settings.yaml"), encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    block = re.search(r"^ui-theme:\s*$(.*?)(?=^\S|\Z)", text, re.S | re.M)
    if not block:
        return None
    found = re.search(r"preference:\s*(\w+)", block.group(1))
    return found.group(1) if found else None


def _active_skin(home: str) -> Optional[str]:
    try:
        with open(os.path.join(home, "skin-center-active.json"), encoding="utf-8") as fh:
            return json.load(fh).get("active")
    except Exception:
        return None


def _skin_css(home: str, skin_id: str) -> Optional[str]:
    candidates = [
        os.path.join(home, "profiles", "web", "node_modules", "@linxin666",
                     "dsh-client-ui-skin-center", "skins", skin_id, "skin.css"),
        os.path.join(home, "profiles", "node_modules", "@linxin666",
                     "dsh-client-ui-skin-center", "skins", skin_id, "skin.css"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _skin_tokens(css: str) -> Dict[str, Dict[str, str]]:
    """``{'base': {...}, 'dark': {...}}`` of ``--dsw-alias-*`` values."""
    out: Dict[str, Dict[str, str]] = {"base": {}, "dark": {}}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = match.group(1), match.group(2)
        key = "dark" if "data-ds-dark-theme" in selector else "base"
        for prop, value in re.findall(r"(--dsw-[a-zA-Z0-9_-]+)\s*:\s*([^;]+)", body):
            out[key][prop] = value.strip()
    return out


def _flatten(value: str, scrim: float = 0.0) -> str:
    """Resolve the skin's ``calc(var(--dsw-skin-scrim) * x)`` rgba() to a colour.

    Skin surfaces are written as
    ``rgba(26, 34, 56, calc(1 - var(--dsw-skin-scrim, 0) * .45))``, so the
    literal value depends on a runtime variable.  Substituting ``scrim=0``
    yields the fully opaque intended surface.  (With a wallpaper background
    enabled the real scrim is non-zero and the actual surface is semi-
    transparent over the image; the flat colour is slightly more solid.)
    """
    match = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([^)]+))?\)",
                     value)
    if not match:
        return value
    r, g, b = (int(round(float(match.group(i)))) for i in (1, 2, 3))
    alpha_expr = (match.group(4) or "").strip()
    alpha = 1.0
    if alpha_expr:
        if "calc" in alpha_expr:
            one_minus = re.search(r"1\s*-\s*var\(--dsw-skin-scrim[^)]*\)\s*\*\s*([\d.]+)",
                                  alpha_expr)
            if one_minus:
                alpha = 1.0 - scrim * float(one_minus.group(1))
            else:
                only_scrim = re.search(r"var\(--dsw-skin-scrim[^)]*\)\s*\*\s*([\d.]+)",
                                       alpha_expr)
                alpha = scrim * float(only_scrim.group(1)) if only_scrim else 1.0
        else:
            try:
                alpha = float(alpha_expr)
            except ValueError:
                alpha = 1.0
    if alpha >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def _from_dsh(appearance: Optional[str]) -> Tuple[Optional[Palette], str]:
    home = _dsh_home()
    if not home:
        return None, "DSH_HOME not found"

    preference = appearance or _read_appearance(home)
    use_dark = {"dark": True, "light": False}.get(preference or "", True)

    skin = _active_skin(home)
    css_path = _skin_css(home, skin) if skin else None
    if not css_path:
        return None, f"skin stylesheet not found (skin={skin})"

    tokens = _skin_tokens(open(css_path, encoding="utf-8", errors="replace").read())
    layer = tokens["dark"] if use_dark else tokens["base"]
    if not layer:
        return None, "no skin tokens parsed"

    def token(prop: str, default: str) -> str:
        return _flatten(layer[prop]) if prop in layer else default

    palette = Palette(
        bg=token("--dsw-alias-bg-layer-1", PLAIN_DARK.bg),
        bg2=token("--dsw-alias-bg-layer-2", PLAIN_DARK.bg2),
        fg=token("--dsw-alias-label-primary", PLAIN_DARK.fg),
        muted=token("--dsw-alias-label-tertiary", PLAIN_DARK.muted),
        rule=token("--dsw-alias-border-l2", PLAIN_DARK.rule),
        bar_bg=token("--dsw-alias-bg-layer-2", PLAIN_DARK.bar_bg),
        bar_fg=token("--dsw-alias-label-caption", PLAIN_DARK.bar_fg),
        accent=token("--dsw-alias-brand-primary", PLAIN_DARK.accent),
        sel_bg=token("--dsw-alias-brand-primary", PLAIN_DARK.sel_bg),
        sel_fg="#10141f" if use_dark else "#ffffff",
        dot=token("--dsw-alias-border-l3", PLAIN_DARK.dot),
    )
    return palette, f"host theme ({'dark' if use_dark else 'light'}, skin '{skin}')"
