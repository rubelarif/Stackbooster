"""Small text helpers shared by the analyzers.

The analyzers read source as text instead of running a real parser for each
language. These helpers keep that approach honest: comments are blanked out
(keeping offsets and line numbers intact) so commented-out code is not reported.
"""

from __future__ import annotations

import bisect
import re


class LineIndex:
    """Map character offsets to 1-based line numbers."""

    def __init__(self, text: str, first_line: int = 1) -> None:
        self._starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
        self._first = first_line

    def line(self, offset: int) -> int:
        return bisect.bisect_right(self._starts, offset) - 1 + self._first


def _blank(segment: str) -> str:
    """Replace everything but newlines with spaces so offsets stay valid."""
    return re.sub(r"[^\n]", " ", segment)


def strip_c_style_comments(text: str, hash_comments: bool = False) -> str:
    """Blank out ``//``, ``/* */`` (and optionally ``#``) comments outside string literals.

    Works for PHP and JavaScript. Template literals and regex literals in JS are
    treated like strings or code respectively, which is good enough for finding
    URLs and SQL.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(_blank(text[i:end]))
            i = end
            continue
        if text.startswith("//", i) or (hash_comments and ch == "#" and not text.startswith("#[", i)):
            end = text.find("\n", i)
            if end == -1:
                end = n
            # A PHP closing tag ends a line comment too.
            close = text.find("?>", i, end)
            if close != -1:
                end = close
            out.append(_blank(text[i:end]))
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), text, flags=re.S)


PHP_BLOCK_RE = re.compile(r"<\?(?:php\b|=)?.*?(?:\?>|\Z)", re.S | re.I)


def mask_php(text: str) -> str:
    """Blank out PHP code blocks, leaving only the HTML template around them."""
    return PHP_BLOCK_RE.sub(lambda m: _blank(m.group(0)), text)


def php_code_only(text: str) -> str:
    """Blank out the HTML outside PHP blocks, leaving only PHP code."""
    out: list[str] = []
    pos = 0
    for m in PHP_BLOCK_RE.finditer(text):
        out.append(_blank(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_blank(text[pos:]))
    return "".join(out)


STRING_RE = re.compile(r"""(?P<q>['"])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.S)


def string_literals(text: str):
    """Yield ``(offset, body)`` for each single or double quoted string literal."""
    for m in STRING_RE.finditer(text):
        yield m.start(), m.group("body")


def find_matching(text: str, open_pos: int, open_ch: str = "(", close_ch: str = ")") -> int:
    """Return the index of the bracket matching ``text[open_pos]``, or -1.

    String literals are skipped so brackets inside quotes do not count.
    """
    depth = 0
    quote: str | None = None
    i = open_pos
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on ``sep`` when not nested in brackets or quotes."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == "\\" and i + 1 < len(text):
                current.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if "".join(current).strip():
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]
