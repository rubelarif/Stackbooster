"""Frontend analyzer for HTML pages and server-rendered templates.

Handles plain ``.html`` files and the HTML part of ``.php``/``.phtml``/``.tpl``
templates (PHP blocks are blanked out first). For each page it records the
title, forms and their fields, links, script and stylesheet references, element
ids, and backend calls made from inline ``<script>`` blocks.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from stackbooster.analyzers.base import Analyzer, FileContext
from stackbooster.analyzers.javascript import find_calls
from stackbooster.analyzers.textutil import LineIndex, mask_php, strip_html_comments
from stackbooster.model import Form, FormField, Page, SiteMap

_FIELD_TAGS = {"input", "select", "textarea", "button"}
_SKIP_INPUT_TYPES = {"submit", "button", "reset", "image"}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.forms: list[Form] = []
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []
        self.element_ids: list[str] = []
        self.inline_scripts: list[tuple[int, str]] = []  # (line, code)
        self.tag_count = 0
        self._form_stack: list[Form] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._script_start: int | None = None
        self._script_parts: list[str] = []

    # HTMLParser callbacks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_count += 1
        a = {k.lower(): (v or "") for k, v in attrs}
        line = self.getpos()[0]
        if a.get("id"):
            self.element_ids.append(a["id"])

        if tag == "title":
            self._in_title = True
        elif tag == "form":
            form = Form(action=a.get("action", "").strip(), method=(a.get("method") or "GET").upper(), line=line)
            self.forms.append(form)
            self._form_stack.append(form)
        elif tag in _FIELD_TAGS and self._form_stack:
            name = a.get("name")
            ftype = a.get("type", "text" if tag == "input" else tag).lower()
            if name and ftype not in _SKIP_INPUT_TYPES and tag != "button":
                form = self._form_stack[-1]
                if not any(f.name == name for f in form.fields):
                    form.fields.append(FormField(name=name, type=ftype, required="required" in a))
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())
        elif tag == "script":
            if a.get("src"):
                self.scripts.append(a["src"].strip())
            else:
                self._script_start = line
                self._script_parts = []
        elif tag == "link" and "stylesheet" in a.get("rel", "").lower() and a.get("href"):
            self.stylesheets.append(a["href"].strip())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            text = " ".join("".join(self._title_parts).split())
            self.title = text or self.title
        elif tag == "form" and self._form_stack:
            self._form_stack.pop()
        elif tag == "script" and self._script_start is not None:
            self.inline_scripts.append((self._script_start, "".join(self._script_parts)))
            self._script_start = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._script_start is not None:
            self._script_parts.append(data)


_PHP_TITLE_RE = re.compile(r"""\$(?:page_title|pageTitle|title)\s*=\s*['"]([^'"]+)['"]""")
_TEMPLATE_INCLUDE_RE = re.compile(
    r"""\b(?:include|require)(?:_once)?\s*\(?\s*['"]([^'"]+)['"]|\{%\s*include\s+['"]([^'"]+)['"]""",
    re.I,
)


class HtmlAnalyzer(Analyzer):
    name = "html"
    extensions = (".html", ".htm", ".php", ".phtml", ".tpl", ".twig")

    def analyze(self, ctx: FileContext, site: SiteMap) -> None:
        markup = strip_html_comments(mask_php(ctx.text))
        parser = _PageParser()
        try:
            parser.feed(markup)
            parser.close()
        except Exception as exc:  # html.parser is lenient, but be safe on odd input
            site.warnings.append(f"{ctx.rel_path}: could not parse HTML ({exc})")
            return

        is_template = not ctx.rel_path.lower().endswith((".html", ".htm"))
        if is_template and not self._looks_like_page(parser):
            return

        page = Page(
            path="/" + ctx.rel_path,
            file=ctx.rel_path,
            title=parser.title or _php_title(ctx.text),
            forms=parser.forms,
            links=_dedupe(parser.links),
            scripts=_dedupe(parser.scripts),
            stylesheets=_dedupe(parser.stylesheets),
            element_ids=_dedupe(parser.element_ids),
            includes=_dedupe(m.group(1) or m.group(2) for m in _TEMPLATE_INCLUDE_RE.finditer(ctx.text)),
        )

        lines = LineIndex(ctx.text)
        for start_line, code in parser.inline_scripts:
            page.ajax_calls.extend(find_calls(code, first_line=start_line, file=ctx.rel_path))
        # Inline event handlers such as onclick="$.post('cart.php', ...)"
        for m in re.finditer(r"""\bon\w+\s*=\s*(["'])(.*?)\1""", markup, re.S):
            page.ajax_calls.extend(find_calls(m.group(2), first_line=lines.line(m.start()), file=ctx.rel_path))

        site.pages.append(page)

    @staticmethod
    def _looks_like_page(parser: _PageParser) -> bool:
        """Templates that are only a fragment of markup (a header include) still count
        as pages if they hold something a user interacts with."""
        return parser.tag_count >= 3 or bool(parser.forms) or bool(parser.inline_scripts)


def _php_title(text: str) -> str | None:
    """Server-rendered pages often set the title in a variable the header prints."""
    m = _PHP_TITLE_RE.search(text)
    return m.group(1) if m else None


def _dedupe(items) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))
