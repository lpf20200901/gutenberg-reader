"""Render parsed blocks to a self-contained HTML page or Markdown.

The HTML output is deliberately **one file with no external references** — no
CSS file, no script file, no fonts, no images.  The book text is embedded
directly.  That has three consequences worth stating:

* it works from ``file://`` with no server, and inside sandboxed iframes;
* it cannot break because a sibling file moved, which is what makes renaming or
  reorganising a library directory harmless;
* a host application integration can simply *open the file* instead of
  registering a renderer plugin against a young, pre-1.0 API.

The generated page also carries its own reading state: scroll position and font
size are kept in ``localStorage`` keyed by document path, and every storage
access is wrapped because sandboxed frames may deny it outright.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass
from typing import Iterable, List, Optional

from .structure import Block
from .theme import CJK_FONT_STACK, LATIN_FONT_STACK, Palette

__all__ = ["RenderOptions", "render_html", "render_markdown", "default_output_name"]


@dataclass
class RenderOptions:
    """Everything the renderer needs beyond the blocks themselves."""

    title: str = "Reading"
    source_label: str = "book.txt"
    cjk: bool = False
    palette: Optional[Palette] = None
    font_size: float = 15.0
    show_status_bar: bool = True


def default_output_name(cjk: bool) -> str:
    return "reader.html" if not cjk else "reader.html"


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

# Placeholders rather than str.format(): the stylesheet and script are full of
# braces, and Python's %-formatting would collide with CSS percentages.
_TEMPLATE = """<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --fs: __FS__px;
    --bg: __BG__;
    --bg2: __BG2__;
    --fg: __FG__;
    --muted: __MUTED__;
    --rule: __RULE__;
    --bar-bg: __BAR_BG__;
    --bar-fg: __BAR_FG__;
    --accent: __ACCENT__;
    --sel-bg: __SEL_BG__;
    --sel-fg: __SEL_FG__;
    --dot: __DOT__;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); }
  body {
    font: var(--fs)/__LH__ __FONT__;
    -webkit-font-smoothing: antialiased;
  }
  #bar {
    position: sticky; top: 0; z-index: 9;
    display: flex; align-items: center; gap: 10px;
    padding: 7px 14px; background: var(--bar-bg);
    border-bottom: 1px solid var(--rule);
    font-size: 12px; color: var(--bar-fg);
    font-family: ui-monospace, Consolas, "Cascadia Mono", monospace;
  }
  #bar .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--dot); }
  #bar .path { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #bar .pg { font-variant-numeric: tabular-nums; }
  main { max-width: __WIDTH__px; margin: 0 auto; padding: 26px 26px 60vh; }
  h1 {
    font-size: 1.14em; font-weight: 600; color: var(--fg);
    margin: 2.4em 0 1.1em; padding-bottom: .4em;
    border-bottom: 1px solid var(--rule);
  }
  h2 {
    font-size: 1.02em; font-weight: 600; color: var(--muted);
    margin: 2.2em 0 .9em; padding-bottom: .35em;
    border-bottom: 1px solid var(--rule);
  }
  p { margin: 0 0 1.05em; __PARA__ }
  p.en { padding-left: 2.1em; text-indent: 0; position: relative; }
  p.en .num {
    position: absolute; left: 0; top: 0;
    color: var(--muted); font-size: .82em;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, Consolas, monospace;
  }
  a { color: var(--accent); }
  ::selection { background: var(--sel-bg); color: var(--sel-fg); }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 5px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--accent); }
  .toast {
    position: fixed; right: 14px; bottom: 14px; z-index: 20;
    background: var(--bg2); color: var(--fg);
    border: 1px solid var(--rule);
    padding: 6px 11px; border-radius: 6px;
    font-size: 12px; font-family: ui-monospace, Consolas, monospace;
    opacity: 0; transition: opacity .18s;
  }
  .toast.on { opacity: .95; }
</style>
</head>
<body>
__BAR__
<main id="doc">
__BODY__
</main>
<div class="toast" id="toast"></div>
<script>
(function () {
  var KEY = "reader-pos:" + location.pathname;
  var KEY_FS = "reader-fs:" + location.pathname;
  var pg = document.getElementById("pg");
  var toastEl = document.getElementById("toast");

  // storage can be denied outright inside a sandboxed frame - never let it throw
  function save(v) { try { localStorage.setItem(KEY, String(v)); } catch (e) {} }
  function load() { try { return parseFloat(localStorage.getItem(KEY)) || 0; } catch (e) { return 0; } }
  function saveFs(v) { try { localStorage.setItem(KEY_FS, String(v)); } catch (e) {} }
  function loadFs() { try { return parseFloat(localStorage.getItem(KEY_FS)) || 0; } catch (e) { return 0; } }

  // font size: honour the reader's own adjustment, else the generated default
  var fs = loadFs() || __FS__;
  document.documentElement.style.setProperty("--fs", fs + "px");

  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("on");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { toastEl.classList.remove("on"); }, 900);
  }

  function pct() {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    return h > 0 ? Math.min(100, Math.round(window.scrollY / h * 100)) : 0;
  }
  function tick() { if (pg) pg.textContent = pct() + "%"; }

  window.addEventListener("scroll", function () { tick(); save(window.scrollY); }, { passive: true });
  tick();

  var target = load();
  if (target > 0) { setTimeout(function () { window.scrollTo(0, target); tick(); }, 60); }

  function setFs(delta) {
    fs = Math.min(30, Math.max(11, fs + delta));
    document.documentElement.style.setProperty("--fs", fs + "px");
    saveFs(fs);
    toast("font " + fs + "px");
  }

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    var h = window.innerHeight;
    switch (e.key) {
      case " ":        window.scrollBy(0, e.shiftKey ? -h * 0.9 : h * 0.9); e.preventDefault(); break;
      case "PageDown": window.scrollBy(0, h * 0.9); e.preventDefault(); break;
      case "PageUp":   window.scrollBy(0, -h * 0.9); e.preventDefault(); break;
      case "j": window.scrollBy(0, 90); break;
      case "k": window.scrollBy(0, -90); break;
      case "d": window.scrollBy(0, h * 0.5); break;
      case "u": window.scrollBy(0, -h * 0.5); break;
      case "g": window.scrollTo(0, 0); break;
      case "G": window.scrollTo(0, document.body.scrollHeight); break;
      case "+": case "=": setFs(1); break;
      case "-": case "_": setFs(-1); break;
    }
  });
})();
</script>
</body>
</html>
"""


def render_html(blocks: Iterable[Block], options: RenderOptions) -> str:
    """Render blocks as one self-contained HTML document."""
    palette = options.palette or Palette(
        bg="#ffffff", bg2="#f6f8fa", fg="#24292f", muted="#6e7781", rule="#d8dee4",
        bar_bg="#f6f8fa", bar_fg="#6e7781", accent="#0969da",
        sel_bg="#0969da", sel_fg="#ffffff", dot="#d0d7de",
    )

    parts: List[str] = []
    for block in blocks:
        if block.kind == "en":
            number = _html.escape(block.number or "")
            parts.append(f'<p class="en"><span class="num">{number}</span>'
                         f'{_html.escape(block.text)}</p>')
        elif block.kind == "h1":
            parts.append(f"<h1>{_html.escape(block.text)}</h1>")
        elif block.kind == "h2":
            parts.append(f"<h2>{_html.escape(block.text)}</h2>")
        else:
            parts.append(f"<p>{_html.escape(block.text)}</p>")

    if options.show_status_bar:
        bar = ('<div id="bar">\n'
               '  <span class="dot"></span>\n'
               f'  <span class="path">{_html.escape(options.source_label)}</span>\n'
               '  <span class="pg" id="pg">--</span>\n'
               '</div>')
    else:
        bar = ""

    cjk = options.cjk
    values = {
        "__LANG__": "zh-Hans" if cjk else "en",
        "__TITLE__": _html.escape(options.title),
        "__FS__": f"{options.font_size:g}",
        "__LH__": "1.9" if cjk else "1.72",
        "__WIDTH__": "740" if cjk else "760",
        "__FONT__": CJK_FONT_STACK if cjk else LATIN_FONT_STACK,
        "__PARA__": ("text-indent: 2em; text-align: justify;"
                     if cjk else "text-align: justify; hyphens: auto;"),
        "__BAR__": bar,
        "__BODY__": "\n".join(parts),
        "__BG__": palette.bg, "__BG2__": palette.bg2, "__FG__": palette.fg,
        "__MUTED__": palette.muted, "__RULE__": palette.rule,
        "__BAR_BG__": palette.bar_bg, "__BAR_FG__": palette.bar_fg,
        "__ACCENT__": palette.accent, "__SEL_BG__": palette.sel_bg,
        "__SEL_FG__": palette.sel_fg, "__DOT__": palette.dot,
    }

    out = _TEMPLATE
    for placeholder, value in values.items():
        out = out.replace(placeholder, value)
    return out


def render_markdown(blocks: Iterable[Block], title: str) -> str:
    """Render blocks as Markdown — a fallback for hosts that show HTML source."""
    lines: List[str] = [f"# {title}", ""]
    for block in blocks:
        if block.kind == "en":
            lines.append(f"**{block.number}.** {block.text}")
        elif block.kind == "h1":
            lines.append(f"## {block.text}")
        elif block.kind == "h2":
            lines.append(f"### {block.text}")
        else:
            lines.append(block.text)
        lines.append("")
    return "\n".join(lines)
