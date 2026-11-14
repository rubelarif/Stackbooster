"""Find client-side calls to backend endpoints in JavaScript.

Recognised call shapes:

* ``$.ajax({ url: '...', type: 'POST' })`` and ``jQuery.ajax(...)``
* ``$.get``, ``$.post``, ``$.getJSON`` and ``$(sel).load``
* ``fetch('...', { method: 'POST' })``
* ``xhr.open('POST', '...')``
* ``axios.get/post/put/delete('...')``

URLs built by string concatenation keep their literal prefix, for example
``'api.php?action=' + name`` is recorded as ``api.php?action=``.
"""

from __future__ import annotations

import re

from stackbooster.analyzers.base import Analyzer, FileContext
from stackbooster.analyzers.textutil import LineIndex, find_matching, strip_c_style_comments
from stackbooster.model import AjaxCall, SiteMap

_Q = r"""(?P<q>['"`])(?P<url>(?:\\.|(?!(?P=q)).)*)(?P=q)"""

AJAX_RE = re.compile(r"(?:\$|jQuery)\s*\.\s*ajax\s*\(")
SHORTHAND_RE = re.compile(r"(?:\$|jQuery)\s*\.\s*(get|post|getJSON)\s*\(\s*" + _Q)
LOAD_RE = re.compile(r"\.\s*load\s*\(\s*" + _Q)
FETCH_RE = re.compile(r"\bfetch\s*\(\s*" + _Q)
XHR_RE = re.compile(r"\.\s*open\s*\(\s*(['\"])(GET|POST|PUT|DELETE|PATCH)\1\s*,\s*" + _Q, re.I)
AXIOS_RE = re.compile(r"\baxios\s*\.\s*(get|post|put|delete|patch)\s*\(\s*" + _Q)

URL_KEY_RE = re.compile(r"\burl\s*:\s*" + _Q)
METHOD_KEY_RE = re.compile(r"\b(?:type|method)\s*:\s*(['\"])(\w+)\1")


def _clean_url(url: str) -> str:
    # Template literal: keep text before the first ${...}
    return url.split("${", 1)[0].strip()


def find_calls(js: str, first_line: int = 1, file: str | None = None) -> list[AjaxCall]:
    """Return every backend call found in a block of JavaScript."""
    code = strip_c_style_comments(js)
    lines = LineIndex(code, first_line)
    calls: list[AjaxCall] = []

    for m in AJAX_RE.finditer(code):
        open_pos = m.end() - 1
        close = find_matching(code, open_pos)
        args = code[open_pos + 1 : close if close != -1 else len(code)]
        url_m = URL_KEY_RE.search(args)
        if not url_m:
            # $.ajax('url', {...}) form
            url_m = re.match(r"\s*" + _Q, args)
        if not url_m:
            continue
        method_m = METHOD_KEY_RE.search(args)
        calls.append(
            AjaxCall(
                url=_clean_url(url_m.group("url")),
                method=(method_m.group(2).upper() if method_m else "GET"),
                library="jquery",
                line=lines.line(m.start()),
                file=file,
            )
        )

    for m in SHORTHAND_RE.finditer(code):
        method = "POST" if m.group(1) == "post" else "GET"
        calls.append(AjaxCall(_clean_url(m.group("url")), method, "jquery", lines.line(m.start()), file))

    for m in LOAD_RE.finditer(code):
        calls.append(AjaxCall(_clean_url(m.group("url")), "GET", "jquery", lines.line(m.start()), file))

    for m in FETCH_RE.finditer(code):
        open_pos = code.find("(", m.start())
        close = find_matching(code, open_pos)
        args = code[m.end() : close if close != -1 else len(code)]
        method_m = METHOD_KEY_RE.search(args)
        method = method_m.group(2).upper() if method_m else "GET"
        calls.append(AjaxCall(_clean_url(m.group("url")), method, "fetch", lines.line(m.start()), file))

    for m in XHR_RE.finditer(code):
        calls.append(AjaxCall(_clean_url(m.group("url")), m.group(2).upper(), "xhr", lines.line(m.start()), file))

    for m in AXIOS_RE.finditer(code):
        calls.append(AjaxCall(_clean_url(m.group("url")), m.group(1).upper(), "axios", lines.line(m.start()), file))

    calls.sort(key=lambda c: (c.line or 0))
    return [c for c in calls if c.url]


class JavaScriptAnalyzer(Analyzer):
    """Standalone ``.js`` files. Inline ``<script>`` blocks are handled by the HTML analyzer."""

    name = "javascript"
    extensions = (".js",)

    def accepts(self, rel_path: str) -> bool:
        lowered = rel_path.lower()
        if not lowered.endswith(".js") or lowered.endswith(".min.js"):
            return False
        # Vendored libraries are noise, not site code.
        return not any(part in lowered for part in ("jquery", "vendor/", "node_modules/", "bootstrap"))

    def analyze(self, ctx: FileContext, site: SiteMap) -> None:
        site.script_calls.extend(find_calls(ctx.text, file=ctx.rel_path))
