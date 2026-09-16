"""Browse and search the Project Gutenberg catalogue.

Two lessons are baked into this module
======================================

**1. The two page types use different markup.**

``/browse/languages/<lang>`` (a complete listing) marks entries with
``<li class="pgdbetext">`` and groups them under ``<h2>`` author headings.
``/ebooks/search/?query=`` (search) marks them with ``<li class="booklink">``.

A scraper written against one silently returns *zero* results against the
other — no error, just an empty list.  Both shapes are handled here, and
:func:`list_language` reports the raw count it saw so a mismatch is visible
rather than silent.

**2. Write non-ASCII output to a file, not to stdout.**

On a Windows console with a non-UTF-8 code page, Chinese book titles are
mangled on the way out.  That is a *display* problem — the data is fine — but it
makes debugging impossible and can look like a parsing bug.  The CLI writes
UTF-8 files; keep it that way.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

__all__ = [
    "BookEntry",
    "get_page",
    "list_language",
    "search",
    "build_catalog_markdown",
    "CATEGORY_ORDER",
]

USER_AGENT = "gutenberg-reader/0.1 (+https://gitee.com/xingluzhe/gutenberg-reader)"
BROWSE_URL = "https://www.gutenberg.org/browse/languages/{lang}"
SEARCH_URL = "https://www.gutenberg.org/ebooks/search/?query={q}"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

#: author-grouped listing, e.g. browse/languages/zh
_BROWSE_ENTRY = re.compile(
    r'<h2><a id="a\d+"></a><a href="/browse/authors/[^"]*">(.*?)</a></h2>'
    r'|<li class="pgdbetext"><a href="/ebooks/(\d+)">(.*?)</a>',
    re.S,
)
#: search results listing
_SEARCH_ENTRY = re.compile(
    r'<li class="booklink">.*?href="/ebooks/(\d+)".*?'
    r'<span class="title">(.*?)</span>.*?'
    r'<span class="subtitle">(.*?)</span>',
    re.S,
)


@dataclass
class BookEntry:
    """One catalogue row."""

    ebook_id: int
    title: str
    author: str = ""

    @property
    def url(self) -> str:
        return f"https://www.gutenberg.org/ebooks/{self.ebook_id}"

    @property
    def txt_url(self) -> str:
        return f"https://www.gutenberg.org/cache/epub/{self.ebook_id}/pg{self.ebook_id}.txt"


def _clean(fragment: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub("", fragment))).strip()


def get_page(url: str, timeout: int = 45) -> str:
    """Fetch a URL as text, following redirects."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def list_language(lang: str = "zh", timeout: int = 45) -> List[BookEntry]:
    """Every book Gutenberg lists for a language code, grouped by author.

    Duplicate (id, title) pairs are collapsed; the raw page repeats entries.
    """
    page = get_page(BROWSE_URL.format(lang=lang), timeout=timeout)
    entries: List[BookEntry] = []
    seen = set()
    author = ""

    for match in _BROWSE_ENTRY.finditer(page):
        if match.group(1) is not None:
            author = _clean(match.group(1))
        else:
            ebook_id, title = int(match.group(2)), _clean(match.group(3))
            key = (ebook_id, title)
            if key in seen:
                continue
            seen.add(key)
            entries.append(BookEntry(ebook_id, title, author))
    return entries


def search(query: str, limit: int = 25, timeout: int = 45) -> List[BookEntry]:
    """Search the catalogue.  Note: a different page shape from
    :func:`list_language`, see the module docstring."""
    page = get_page(SEARCH_URL.format(q=urllib.parse.quote(query)), timeout=timeout)
    entries: List[BookEntry] = []
    for match in _SEARCH_ENTRY.finditer(page):
        entries.append(BookEntry(int(match.group(1)), _clean(match.group(2)),
                                 _clean(match.group(3))))
        if len(entries) >= limit:
            break
    return entries


# --------------------------------------------------------------------------
# catalogue rendering
# --------------------------------------------------------------------------

CATEGORY_ORDER = [
    "短篇志怪", "笔记清谈", "公案探案", "传奇单篇",
    "长篇小说", "戏曲话本", "诗词", "经史子部", "蒙学", "其他",
]

#: ebook id -> (category, note).  Curated pointers, not generated.
CURATED: Dict[int, tuple] = {
    51828: ("短篇志怪", "493 篇独立短故事，三五分钟一篇"),
    23817: ("短篇志怪", "纪昀著，与聊斋齐名的笔记小说"),
    25362: ("短篇志怪", "干宝辑录，中国志怪小说的源头"),
    24047: ("笔记清谈", "魏晋名士段子集，每条一两句，随时能放下"),
    25192: ("笔记清谈", "沈复自传体散文，写夫妻日常与漂泊"),
    27686: ("公案探案", "狄公案，中国公案小说，想读推理选这个"),
    25393: ("公案探案", "施公案，清代公案小说代表作"),
    54494: ("公案探案", "海公案，海瑞断案故事"),
    24051: ("传奇单篇", "李娃傳，唐传奇名篇"),
    24068: ("传奇单篇", "燕丹子，荆轲刺秦的早期版本"),
    23950: ("长篇小说", "三國演義，章回体开山之作"),
    23962: ("长篇小说", "西遊記，单元剧结构，随便翻一难都能读"),
    23863: ("长篇小说", "水滸傳，前七十回最好看"),
    24264: ("长篇小说", "紅樓夢，最耐读也最费神"),
    23818: ("长篇小说", "鏡花緣，海外奇国游记，想象力极野"),
    24032: ("长篇小说", "儒林外史，讽刺小说巅峰，段子式结构"),
    25124: ("长篇小说", "老殘遊記，晚清游记体，篇幅不长"),
    52323: ("诗词", "唐诗三百首，一首一分钟"),
    23873: ("诗词", "詩經，中国最早的诗歌总集"),
    25501: ("经史子部", "易經"),
    24048: ("经史子部", "禮記"),
    25288: ("经史子部", "山海經，上古地理与神怪"),
    25606: ("经史子部", "三國志，正史，和演义对照读很有意思"),
    12479: ("蒙学", "三字經"),
    25196: ("蒙学", "百家姓"),
}


def build_catalog_markdown(entries: List[BookEntry], title: str = "Gutenberg 书目") -> str:
    """Render catalogue entries as a browsable Markdown document."""
    by_id = {e.ebook_id: e for e in entries}

    out: List[str] = [f"# {title}", "",
                      f"共 **{len(entries)}** 本可下载的公版书。", "",
                      "看中哪本，记下编号即可：", "",
                      "```", "gutenberg-reader get <编号> -o books/", "```", ""]

    curated = [(eid, by_id[eid]) for eid, (_, _) in CURATED.items() if eid in by_id]
    if curated:
        out += ["---", "", "## 推荐", "",
                "| 书名 | 编号 | 类别 | 备注 |", "| --- | --- | --- | --- |"]
        for eid, entry in curated:
            category, note = CURATED[eid]
            out.append(f"| **{entry.title}** | `{eid}` | {category} | {note} |")
        out.append("")

        out += ["---", "", "## 按类别", ""]
        buckets: Dict[str, List[tuple]] = {}
        for eid, entry in curated:
            buckets.setdefault(CURATED[eid][0], []).append((eid, entry, CURATED[eid][1]))
        for category in CATEGORY_ORDER:
            rows = buckets.get(category)
            if not rows:
                continue
            out += [f"### {category}", "", "| 书名 | 编号 | 备注 |", "| --- | --- | --- |"]
            for eid, entry, note in sorted(rows, key=lambda r: r[1].title):
                out.append(f"| {entry.title} | `{eid}` | {note} |")
            out.append("")

    out += ["---", "", f"## 全部 {len(entries)} 本（按作者）", ""]
    grouped: Dict[str, List[BookEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.author or "?", []).append(entry)
    for author in sorted(grouped):
        out += [f"**{author}**", ""]
        for entry in sorted(grouped[author], key=lambda e: e.title):
            star = " ⭐" if entry.ebook_id in CURATED else ""
            out.append(f"- {entry.title} — `{entry.ebook_id}`{star}")
        out.append("")

    return "\n".join(out)
