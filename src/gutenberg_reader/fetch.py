"""Download a file over HTTPS, verifying that what arrives is complete.

Why this module exists
======================

The obvious download loop is::

    with urlopen(url) as r, open(dest, "wb") as f:
        while chunk := r.read(65536):
            f.write(chunk)

It has a failure mode that is worse than crashing.  When the connection drops
mid-transfer, ``read()`` simply returns empty, the loop ends *normally*, and the
truncated file is published as if it were complete.  No exception, no warning.

Measured on a slow link (~0.02 MB/s), six book downloads produced four silently
truncated files:

===============  ==========  ==========
book             expected    received
===============  ==========  ==========
警世通言         1,176,833   1,176,833   ok
喻世明言         1,130,409   1,119,627   short
醒世恒言         1,651,633   1,168,587   short (71%)
初刻拍案惊奇     1,213,458   1,091,067   short
二刻拍案惊奇     968,635     813,628     short
今古奇观         2,896,630   724,887     short (25%)
===============  ==========  ==========

A quarter of a book, published as a success.  So this module:

* **verifies** the byte count against ``Content-Length`` and refuses to publish
  a short file;
* **resumes** with a ``Range`` request instead of restarting from zero, which
  matters a great deal when the link drops every few hundred kilobytes;
* **retries** with backoff.

The resume path is not theoretical.  In practice 今古奇观 needed four attempts
(failing at 17%, 37% and 99.6%), 醒世恒言 three (62.8%, 99.0%), and the
alternate edition of 二刻拍案惊奇 two.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

__all__ = ["DownloadResult", "download", "gutenberg_txt_url", "fetch_book"]

CHUNK = 256 * 1024
USER_AGENT = "gutenberg-reader/0.1 (+https://gitee.com/xingluzhe/gutenberg-reader)"


@dataclass
class DownloadResult:
    """Outcome of a download."""

    path: str
    ok: bool
    bytes_written: int
    expected_bytes: Optional[int] = None
    attempts: int = 1
    resumed_from: int = 0
    error: Optional[str] = None

    @property
    def verified(self) -> bool:
        """True when the size was checked against ``Content-Length``."""
        return self.ok and self.expected_bytes is not None

    @property
    def human_size(self) -> str:
        n = self.bytes_written
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
            n /= 1024
        return f"{n:.1f} GB"


def gutenberg_txt_url(ebook_id: int) -> str:
    """The canonical Project Gutenberg plain-text URL for an ebook id."""
    return f"https://www.gutenberg.org/cache/epub/{int(ebook_id)}/pg{int(ebook_id)}.txt"


def download(
    url: str,
    dest: str,
    attempts: int = 5,
    timeout: int = 60,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> DownloadResult:
    """Download ``url`` to ``dest``, never publishing a short file.

    A ``.part`` file holds partial data between attempts so a retry can resume.
    ``dest`` is only written once the transfer is complete and verified.
    """
    part = dest + ".part"
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)

    last_error: Optional[str] = None
    resumed_from = 0

    for attempt in range(1, attempts + 1):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if attempt == 1:
            resumed_from = have

        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                total = _expected_size(resp, have)
                if resp.status != 206 and have:
                    # the server ignored Range: start over rather than corrupt
                    have = 0

                done = have
                with open(part, "ab" if have else "wb") as fh:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total)

            if total and done != total:
                raise IOError(
                    f"incomplete download: {done:,} of {total:,} bytes "
                    f"({done / total * 100:.1f}%)"
                )

            os.replace(part, dest)
            return DownloadResult(
                path=dest, ok=True, bytes_written=done, expected_bytes=total,
                attempts=attempt, resumed_from=resumed_from,
            )

        except Exception as exc:                       # noqa: BLE001 - reported
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(min(2 * attempt, 8))

    return DownloadResult(
        path=dest, ok=False,
        bytes_written=os.path.getsize(part) if os.path.exists(part) else 0,
        attempts=attempts, resumed_from=resumed_from, error=last_error,
    )


def _expected_size(resp, already_have: int) -> Optional[int]:
    """Total size of the resource, from Content-Length or Content-Range."""
    if resp.status == 206:
        content_range = resp.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                return int(content_range.rsplit("/", 1)[1])
            except ValueError:
                pass
        length = int(resp.headers.get("Content-Length") or 0)
        return already_have + length if length else None
    length = int(resp.headers.get("Content-Length") or 0)
    return length or None


def fetch_book(
    ebook_id: int,
    dest_dir: str,
    filename: str = "source.txt",
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> DownloadResult:
    """Fetch a Gutenberg book's plain text into ``dest_dir``."""
    return download(
        gutenberg_txt_url(ebook_id),
        os.path.join(dest_dir, filename),
        on_progress=on_progress,
    )
