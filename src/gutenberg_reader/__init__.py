"""gutenberg-reader — build clean, offline reading pages from Project Gutenberg texts.

The two modules worth reading are :mod:`gutenberg_reader.structure` (finding
paragraph and chapter boundaries in transcriptions that disagree with each
other) and :mod:`gutenberg_reader.simplify` (Traditional -> Simplified, and the
4,800-character gap that a "98% working" OS API silently leaves behind).

Typical use::

    from gutenberg_reader import parse, strip_boilerplate, to_simplified

    raw = open("pg51828.txt", encoding="utf-8").read()
    body = strip_boilerplate(raw)
    conv = to_simplified(body)
    blocks = parse(conv.text)
"""

from .simplify import (
    SIMPLIFY_PATCH,
    SIMPLIFY_PATCH_EXCLUDED,
    SIMPLIFY_PATCH_UNCHANGED,
    SIMPLIFY_PATCH_WRONG_VARIANT,
    Conversion,
    audit_gaps,
    residual_traditional,
    to_simplified,
)
from .structure import (
    Block,
    classify_heading,
    detect_mode,
    ends_sentence,
    is_cjk,
    parse,
    stats,
    strip_boilerplate,
)

__version__ = "0.1.0"

__all__ = [
    "Block",
    "Conversion",
    "SIMPLIFY_PATCH",
    "SIMPLIFY_PATCH_EXCLUDED",
    "SIMPLIFY_PATCH_UNCHANGED",
    "SIMPLIFY_PATCH_WRONG_VARIANT",
    "audit_gaps",
    "classify_heading",
    "detect_mode",
    "ends_sentence",
    "is_cjk",
    "parse",
    "residual_traditional",
    "stats",
    "strip_boilerplate",
    "to_simplified",
    "__version__",
]
