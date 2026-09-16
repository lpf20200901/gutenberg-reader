"""Turn a Project Gutenberg plain-text book into structured blocks.

Why this module exists
======================

Every "convert a text file to HTML" script assumes the text has *some* regular
structure.  Gutenberg's Chinese transcriptions do not.  Across nine books from
the same archive, this project found **four different chapter-heading layouts
and three different paragraph-boundary conventions**, sometimes in the same
collection.  A parser that handles only the layout you happened to look at
first will silently produce garbage for the rest — no exception, no warning,
just a page where an entire chapter has collapsed into one paragraph.

The layouts actually observed
-----------------------------

Chapter headings (all four occur in 三言二拍 alone)::

    第一卷　蔣興哥重會珍珠衫            第 + N + 卷, title after a space
    第一卷轉運漢遇巧洞庭紅　波斯胡指破鼉龍殼   第 + N + 卷, title run together
    第一卷 / 兩縣令競義婚孤女            卷 marker and title on separate lines
    卷一 進香客莽看金剛經 出獄僧巧完法會分     no 第, title after a space
    德行第一                          世說新語: name BEFORE the ordinal
    〈考城隍〉                        聊齋志異: title in CJK angle brackets
    1.                                世說新語: bare entry numbers

Paragraph boundaries::

    blank lines   聊齋志異 (2,305 blanks for 2,291 content lines)
                  世說新語
    indentation   醒世恒言 (3,250 indented lines, only 118 blank lines)
                  喻世明言, 警世通言, 初刻拍案惊奇, 今古奇观
    hard wrapping 二刻拍案惊奇 #24162: ~28 chars per line, blank line after
                  EVERY line (10,334 blanks), which fragments each paragraph
                  into a dozen one-line blocks

The indentation convention is the one that bites hardest, because it is
invisible: the first line of a paragraph is indented (two ideographic spaces or
two ASCII spaces) and wrapped continuation lines are not.  Any implementation
that calls ``str.strip()`` on each line before deciding what to do with it has
already thrown the signal away.  That is exactly the bug this module was
written to fix — 初刻拍案惊奇 collapsed from 40 chapters into 42 paragraphs,
averaging nearly 10,000 characters each.

Design notes
------------

* **Line scanning, not blank-line splitting.**  In 世說新語 the section title,
  the entry number and the entry text are three consecutive lines with *no*
  blank line between them, so a blank-line splitter sees one opaque blob.
* **A "weak" heading heuristic that knows when it is safe.**  A short CJK line
  with no punctuation is probably a heading — but only if it genuinely stands
  alone (next physical line blank, or an entry number follows).  Inside a
  paragraph it must never fire, or wrapped lines get promoted to headings.
* **A blocklist, because prose contains short lines too.**  警世通言 produced
  four bogus headings (其一/其二/其三/其四 — enumeration words in the text)
  before the blocklist existed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

# --------------------------------------------------------------------------
# patterns
# --------------------------------------------------------------------------

#: Latin chapter headings: "CHAPTER I"
CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVXLC]+)\.?\s*$", re.IGNORECASE)
#: a bare Roman numeral on its own line
ROMAN_RE = re.compile(r"^\s*([IVXLC]+)\.?\s*$")

#: 聊齋志異 style: 〈考城隍〉 or 《考城隍》
CJK_STORY_RE = re.compile(r"^\s*[〈《]([^〉》]{1,30})[〉》]\s*$")
#: 卷一 alone, or 第一卷 alone
CJK_VOLUME_RE = re.compile(
    r"^\s*(?:卷([〇零一二三四五六七八九十百千兩两0-9]{1,4})"
    r"|第([〇零一二三四五六七八九十百千兩两0-9]{1,6})卷)\s*$"
)
#: 第一卷 + title on the same line
CJK_VOLUME_TITLE_RE = re.compile(
    r"^第([〇零一二三四五六七八九十百千兩两0-9]{1,6})卷[\s\u3000]*(.*)$"
)
#: 卷一 + title on the same line (no 第)
CJK_JUAN_TITLE_RE = re.compile(r"^卷([〇零一二三四五六七八九十百千兩两0-9]{1,4})[\s\u3000]*(.*)$")
#: 第一回 / 第三則 ...
CJK_CHAPTER_RE = re.compile(
    r"^\s*第([〇零一二三四五六七八九十百千兩两0-9]{1,6})([回則则篇章節节])\s*(.*)$"
)
#: 世說新語 style: the name comes BEFORE the ordinal — 德行第一
CJK_PIAN_RE = re.compile(r"^(\S{1,4})第([〇零一二三四五六七八九十百]{1,3})$")
#: a bare entry number on its own line — "1." "1129."
ENTRY_NUM_RE = re.compile(r"^(\d{1,4})\.$")

#: standalone short CJK block with no punctuation -> preface/section heading
CJK_SHORT_HEAD_RE = re.compile(r"^[^\s。，、：；！？「」『』（）()\[\]{}〈〉《》]{2,12}$")

#: characters that mark the start of a paragraph
INDENT_CHARS = (" ", "\t", "\u3000")

#: sentence-ending punctuation, used to detect hard wrapping
TERM_PUNCT = re.compile(r"[。！？：；…」』）)】》\"'’”]$")

#: short lines that look like headings but are in-text narration/enumeration.
#: 警世通言 yielded 其一/其二/其三/其四 as bogus headings before this existed.
WEAK_HEAD_BLOCKLIST = re.compile(
    r"^(其[〇零一二三四五六七八九十]|[又亦]|詩曰|詩云|詞曰|詞云|話說|卻說|且說"
    r"|看官|正是|但見|只見|未知|未知後事)$"
)

_CJK_RANGE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


# --------------------------------------------------------------------------
# public types
# --------------------------------------------------------------------------

@dataclass
class Block:
    """One structural unit of a book.

    ``kind`` is one of:

    ``"h1"``
        A volume / section marker (``第一卷``, ``德行第一``).
    ``"h2"``
        A chapter or story title (``〈考城隍〉``, ``兩縣令競義孤女``).
    ``"en"``
        A numbered entry; ``number`` holds the digits and ``text`` the body.
        Used by 世說新語, where 1,129 short anecdotes are numbered.
    ``"p"``
        An ordinary paragraph.
    """

    kind: str
    text: str
    number: Optional[str] = None

    def is_heading(self) -> bool:
        return self.kind in ("h1", "h2")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def is_cjk(s: str) -> bool:
    """True when a reasonable fraction of ``s`` is CJK ideographs."""
    if not s:
        return False
    return len(_CJK_RANGE.findall(s)) / max(len(s), 1) > 0.15


def join_lines(parts: Iterable[str]) -> str:
    """Join text lines, without inserting spaces inside CJK prose."""
    parts = list(parts)
    return ("" if is_cjk("".join(parts)) else " ").join(parts)


def ends_sentence(s: str) -> bool:
    """True when ``s`` ends with sentence-ending punctuation."""
    return bool(s) and bool(TERM_PUNCT.search(s.strip()))


def strip_boilerplate(text: str) -> str:
    """Remove the Project Gutenberg licence header and footer."""
    m = re.search(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*",
                  text, re.S | re.I)
    if m:
        text = text[m.end():]
    m = re.search(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*",
                  text, re.S | re.I)
    if m:
        text = text[: m.start()]
    return text


# --------------------------------------------------------------------------
# paragraph-boundary detection
# --------------------------------------------------------------------------

def detect_mode(text: str) -> str:
    """Decide how paragraph boundaries are marked in this transcription.

    Returns one of ``"indent"``, ``"unwrap"`` or ``"blank"``.

    ``"indent"``
        Paragraphs start with leading whitespace and wrapped continuation lines
        do not.  This is the dominant convention in the 三言二拍 files and is
        chosen whenever indentation is used substantially more often than blank
        lines are.
    ``"unwrap"``
        Hard-wrapped with no indentation: keep appending lines until one ends
        with sentence punctuation.
    ``"blank"``
        Paragraphs are separated by blank lines (聊齋志異, 世說新語).

    The thresholds are deliberately conservative.  ``indented > blanks + 50``
    rather than a simple ratio, because a text can have many blank lines *and*
    reliable indentation, while the reverse (many indented lines, few blanks)
    is what makes blank-line splitting fail catastrophically.
    """
    lines = text.splitlines()
    nonblank = [ln for ln in lines if ln.strip()]
    if not nonblank:
        return "blank"

    blanks = len(lines) - len(nonblank)
    indented = sum(1 for ln in nonblank if ln[:1] in INDENT_CHARS)
    if indented >= 50 and indented > blanks + 50:
        return "indent"

    if len(nonblank) >= 100:
        # bare entry numbers ("1.") never end a sentence.  Counting them would
        # skew the statistics and misclassify 世說新語 as hard-wrapped.
        prose = [ln for ln in nonblank if not ENTRY_NUM_RE.match(ln.strip())]
        if prose:
            lengths = sorted(len(ln.strip()) for ln in prose)
            if lengths[len(lengths) // 2] <= 45:
                no_end = sum(1 for ln in prose if not ends_sentence(ln)) / len(prose)
                if no_end >= 0.35:
                    return "unwrap"

    return "blank"


# --------------------------------------------------------------------------
# heading classification
# --------------------------------------------------------------------------

def classify_heading(
    line: str,
    next_phys_blank: bool = False,
    next_line: Optional[str] = None,
    allow_weak: bool = True,
) -> Optional[List[Block]]:
    """Classify a single line as heading(s), or return ``None``.

    A list is returned because ``第一卷　蔣興哥重會珍珠衫`` is *both* a volume
    marker and a chapter title on one line, and should render as ``h1`` + ``h2``.

    ``allow_weak`` gates the standalone-short-line heuristic.  It must be
    ``False`` while accumulating a paragraph, otherwise wrapped continuation
    lines get promoted to headings.
    """
    m = CJK_STORY_RE.match(line)
    if m:
        return [Block("h2", m.group(1))]

    m = CJK_VOLUME_TITLE_RE.match(line)
    if m:
        num, title = m.group(1), m.group(2).strip()
        out = [Block("h1", f"第{num}卷")]
        if title:
            out.append(Block("h2", title))
        return out

    m = CJK_JUAN_TITLE_RE.match(line)
    if m:
        num, title = m.group(1), m.group(2).strip()
        out = [Block("h1", f"卷{num}")]
        if title and len(title) > 1:
            out.append(Block("h2", title))
        return out

    if CJK_VOLUME_RE.match(line):
        return [Block("h1", line)]
    if CJK_PIAN_RE.match(line):
        return [Block("h1", line)]
    if CJK_CHAPTER_RE.match(line):
        return [Block("h2", line)]
    if CHAPTER_RE.match(line) or (ROMAN_RE.match(line) and len(line) < 8):
        return [Block("h2", line.rstrip("."))]

    if allow_weak and CJK_SHORT_HEAD_RE.match(line) and is_cjk(line):
        if not WEAK_HEAD_BLOCKLIST.match(line):
            if next_phys_blank or ENTRY_NUM_RE.match(next_line or ""):
                return [Block("h2", line)]

    return None


# --------------------------------------------------------------------------
# the parser
# --------------------------------------------------------------------------

def parse(text: str, mode: Optional[str] = None) -> List[Block]:
    """Parse book text into blocks.

    ``mode`` overrides :func:`detect_mode` when given.
    """
    mode = mode or detect_mode(text)
    indent_mode = mode == "indent"
    unwrap = mode == "unwrap"

    lines = text.splitlines()
    n = len(lines)
    blocks: List[Block] = []
    i = 0

    def next_nonblank(start: int) -> Optional[str]:
        j = start
        while j < n and not lines[j].strip():
            j += 1
        return lines[j].strip() if j < n else None

    while i < n:
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue

        phys_blank = (i + 1 >= n) or (not lines[i + 1].strip())
        headings = classify_heading(line, phys_blank, next_nonblank(i + 1), allow_weak=True)
        if headings:
            blocks.extend(headings)
            i += 1
            continue

        # a numbered entry: number on its own line, then its text
        m = ENTRY_NUM_RE.match(line)
        if m:
            k = i + 1
            buf: List[str] = []
            while k < n:
                nxt = lines[k].strip()
                if not nxt or ENTRY_NUM_RE.match(nxt):
                    break
                if classify_heading(nxt, allow_weak=False):
                    break
                buf.append(nxt)
                k += 1
            if buf:
                blocks.append(Block("en", join_lines(buf), number=m.group(1)))
            i = k
            continue

        # an ordinary paragraph
        k = i + 1
        buf = [line]
        while k < n:
            raw_next = lines[k]
            nxt = raw_next.strip()
            if not nxt:
                if indent_mode or unwrap:
                    k += 1          # blank lines carry no meaning in these modes
                    continue
                break
            if ENTRY_NUM_RE.match(nxt) or classify_heading(nxt, allow_weak=False):
                break
            if indent_mode and raw_next[:1] in INDENT_CHARS:
                break               # an indented line starts a new paragraph
            if unwrap and ends_sentence(buf[-1]):
                break               # the previous line closed a sentence
            buf.append(nxt)
            k += 1
        blocks.append(Block("p", join_lines(buf)))
        i = k

        # we may have stepped over blanks; re-align to content
        while i < n and not lines[i].strip():
            i += 1

    return blocks


def stats(blocks: Iterable[Block]) -> dict:
    """Summarise a parsed book — handy for sanity-checking a new source."""
    blocks = list(blocks)
    counts: dict = {}
    for b in blocks:
        counts[b.kind] = counts.get(b.kind, 0) + 1
    body = [b for b in blocks if b.kind in ("p", "en")]
    chars = sum(len(b.text) for b in body)
    return {
        "blocks": len(blocks),
        "counts": counts,
        "body_chars": chars,
        "avg_paragraph_chars": round(chars / len(body)) if body else 0,
    }
