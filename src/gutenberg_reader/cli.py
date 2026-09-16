"""Command line interface.

    gutenberg-reader get 51828 -o books/聊斋志异 --simplify
    gutenberg-reader build books/聊斋志异/source.txt -o books/聊斋志异 --simplify
    gutenberg-reader fetch 51828 -o books/聊斋志异
    gutenberg-reader catalog -o books/catalog.md --lang zh
    gutenberg-reader search "liao chai"

Every command writes UTF-8 files rather than relying on console output: on a
Windows console with a non-UTF-8 code page, Chinese titles are mangled on the
way to the terminal, which makes a working parser look broken.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from .catalog import BookEntry, build_catalog_markdown, list_language, search
from .fetch import download, fetch_book, gutenberg_txt_url
from .render import RenderOptions, render_html, render_markdown
from .simplify import to_simplified
from .structure import Block, detect_mode, parse, stats, strip_boilerplate
from .structure import is_cjk as text_is_cjk
from .theme import PROVIDERS, get_palette

PARSE_MODES = ("auto", "indent", "unwrap", "blank")


def _progress(done: int, total: Optional[int]) -> None:
    if not total:
        sys.stderr.write(f"\r  {done / 1048576:7.2f} MB")
    else:
        pct = done / total * 100
        sys.stderr.write(f"\r  {done / 1048576:7.2f} / {total / 1048576:.2f} MB"
                         f"  ({pct:5.1f}%)")
    sys.stderr.flush()


def _read_source(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _build(args, source_path: str, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    text = strip_boilerplate(_read_source(source_path))

    note = ""
    if args.simplify:
        conversion = to_simplified(text)
        if conversion.text != text:
            text = conversion.text
            note = (f"simplified: {conversion.total_changed:,} changed "
                    f"({conversion.patched:,} repaired, engine={conversion.engine})")

    mode = args.mode if args.mode != "auto" else detect_mode(text)
    blocks: List[Block] = parse(text, mode=mode)
    summary = stats(blocks)

    palette, theme_note = get_palette(args.theme, args.appearance)

    is_cjk = text_is_cjk(text[:20000])
    title = args.title or os.path.basename(os.path.abspath(out_dir))

    options = RenderOptions(
        title=title,
        source_label=os.path.basename(source_path),
        cjk=is_cjk,
        palette=palette,
        font_size=args.fs,
    )

    html_path = os.path.join(out_dir, "reader.html")
    md_path = os.path.join(out_dir, "reader.md")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(blocks, options))
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(blocks, title))

    print(f"source     : {source_path}")
    print(f"parse mode : {mode}")
    print(f"theme      : {theme_note}")
    if note:
        print(f"note       : {note}")
    print(f"blocks     : {summary['blocks']:,}  {summary['counts']}")
    print(f"body       : {summary['body_chars']:,} chars, "
          f"{summary['avg_paragraph_chars']} chars/paragraph average")
    print(f"wrote      : {html_path}")
    print(f"wrote      : {md_path}")
    return 0


def _resolve_source(target: str) -> str:
    """Accept a bare ebook id or a URL as well as a local path."""
    if target.isdigit():
        return gutenberg_txt_url(int(target))
    return target


def cmd_fetch(args) -> int:
    source = _resolve_source(args.target)
    dest = os.path.join(args.out, "source.txt")
    if source.startswith("http"):
        result = download(source, dest, on_progress=_progress)
    else:
        sys.stderr.write("fetch expects an ebook id or URL\n")
        return 2

    sys.stderr.write("\n")
    if not result.ok:
        print(f"FAILED after {result.attempts} attempts: {result.error}")
        return 1
    print(f"wrote      : {result.path}")
    print(f"size       : {result.human_size}"
          f"{' (verified)' if result.verified else ''}")
    if result.resumed_from:
        print(f"resumed    : from {result.resumed_from:,} bytes")
    return 0


def cmd_build(args) -> int:
    return _build(args, args.source, args.out)


def cmd_get(args) -> int:
    if args.target.isdigit():
        dest = os.path.join(args.out, "source.txt")
        sys.stderr.write("downloading...\n")
        result = fetch_book(int(args.target), args.out, on_progress=_progress)
        sys.stderr.write("\n")
        if not result.ok:
            print(f"download FAILED after {result.attempts} attempts: {result.error}")
            return 1
        print(f"downloaded : {result.human_size}"
              f"{' (verified)' if result.verified else ''}")
    else:
        dest = _resolve_source(args.target)
        if not os.path.isfile(dest):
            print(f"not found: {dest}")
            return 2
    return _build(args, dest, args.out)


def cmd_catalog(args) -> int:
    entries: List[BookEntry] = list_language(args.lang)
    if not entries:
        print("no entries parsed - the catalogue markup may have changed")
        return 1
    markdown = build_catalog_markdown(entries, f"Gutenberg {args.lang} 书目")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    print(f"books      : {len(entries):,}")
    print(f"wrote      : {args.out}")
    return 0


def cmd_search(args) -> int:
    entries = search(args.query, limit=args.limit)
    if not entries:
        print("no results")
        return 1
    for entry in entries:
        author = f"  /  {entry.author}" if entry.author else ""
        print(f"[{entry.ebook_id:>6}] {entry.title}{author}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gutenberg-reader",
        description="Build clean, offline reading pages from Project Gutenberg books.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_build_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("-o", "--out", default="books/book",
                       help="output directory (default: books/book)")
        p.add_argument("--simplify", action="store_true",
                       help="convert Traditional Chinese to Simplified")
        p.add_argument("--title", default=None, help="page title / tab label")
        p.add_argument("--fs", type=float, default=15.0,
                       help="base font size in px (default 15)")
        p.add_argument("--theme", default="plain", choices=PROVIDERS,
                       help="colour palette provider (default plain)")
        p.add_argument("--appearance", default=None, choices=["dark", "light"],
                       help="force an appearance for the dsh provider")
        p.add_argument("--mode", default="auto", choices=PARSE_MODES,
                       help="paragraph-boundary mode (default: auto-detect)")

    p_fetch = sub.add_parser("fetch", help="download a book's plain text")
    p_fetch.add_argument("target", help="ebook id or URL")
    p_fetch.add_argument("-o", "--out", default="books/book")
    p_fetch.set_defaults(func=cmd_fetch)

    p_build = sub.add_parser("build", help="build reading pages from a local text file")
    p_build.add_argument("source", help="path to a plain-text book")
    add_build_options(p_build)
    p_build.set_defaults(func=cmd_build)

    p_get = sub.add_parser("get", help="download and build in one step")
    p_get.add_argument("target", help="ebook id, URL, or local path")
    add_build_options(p_get)
    p_get.set_defaults(func=cmd_get)

    p_cat = sub.add_parser("catalog", help="write a browsable catalogue of a language")
    p_cat.add_argument("--lang", default="zh", help="language code (default zh)")
    p_cat.add_argument("-o", "--out", default="catalog.md")
    p_cat.set_defaults(func=cmd_catalog)

    p_search = sub.add_parser("search", help="search the catalogue")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=25)
    p_search.set_defaults(func=cmd_search)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
