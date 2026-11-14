"""Backend analyzer for classic PHP sites.

Each ``.php`` file becomes one route at its URL path. When a file is a front
controller (``switch ($_GET['action'])``), each ``case`` becomes its own route,
for example ``/api.php?action=add_to_cart``.

The analyzer reads code as text. It does not follow function calls across
files, so a query inside a helper function is reported on the file that defines
the helper, not on the routes that call it.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from stackbooster.analyzers.base import Analyzer, FileContext
from stackbooster.analyzers.sqlrefs import looks_like_sql, query_ref
from stackbooster.analyzers.textutil import (
    LineIndex,
    find_matching,
    mask_php,
    php_code_only,
    string_literals,
    strip_c_style_comments,
    strip_html_comments,
)
from stackbooster.model import Param, Route, SiteMap

_SUPERGLOBAL_SOURCES = {
    "GET": "query",
    "POST": "body",
    "REQUEST": "any",
    "COOKIE": "cookie",
    "FILES": "file",
}

SUPERGLOBAL_RE = re.compile(r"\$_(GET|POST|REQUEST|COOKIE|FILES)\s*\[\s*['\"]([^'\"]+)['\"]\s*\]")
FILTER_INPUT_RE = re.compile(r"filter_input\s*\(\s*INPUT_(GET|POST|COOKIE)\s*,\s*['\"]([^'\"]+)['\"]")
INCLUDE_RE = re.compile(
    r"\b(?:include|require)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?['\"]([^'\"]+\.(?:php|inc|phtml|tpl))['\"]",
    re.I,
)
FUNCTION_RE = re.compile(r"\bfunction\s+&?\s*([A-Za-z_]\w*)\s*\(")
CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
METHOD_CHECK_RE = re.compile(
    r"\$_SERVER\s*\[\s*['\"]REQUEST_METHOD['\"]\s*\]\s*[!=]==?\s*['\"](GET|POST|PUT|DELETE|PATCH)['\"]",
    re.I,
)
JSON_RE = re.compile(r"\bjson_encode\s*\(|Content-Type:\s*application/json", re.I)
REDIRECT_RE = re.compile(r"header\s*\(\s*['\"]Location\s*:", re.I)
ECHO_HTML_RE = re.compile(r"\b(?:echo|print)\s+['\"]\s*<", re.I)
SESSION_RE = re.compile(r"\bsession_start\s*\(|\$_SESSION\b")

# Legacy PHP APIs that will not survive a rebuild as-is.
LEGACY_API_PATTERNS = {
    "mysql_* functions (removed in PHP 7)": re.compile(r"\bmysql_(?:query|connect|fetch_\w+|select_db|real_escape_string)\s*\("),
    "md5/sha1 password hashing": re.compile(r"\b(?:md5|sha1)\s*\(\s*\$_(?:POST|REQUEST)\s*\[\s*['\"]pass", re.I),
    "extract() on request data": re.compile(r"\bextract\s*\(\s*\$_(?:GET|POST|REQUEST)"),
    "eval()": re.compile(r"\beval\s*\("),
    "register_globals style access": re.compile(r"\$HTTP_(?:GET|POST)_VARS\b"),
    "ereg* functions (removed in PHP 7)": re.compile(r"\beregi?(?:_replace)?\s*\("),
}

ACTION_PARAM_NAMES = ("action", "act", "op", "do", "task", "cmd", "page", "route")
# switch ($_GET['action'])
SWITCH_DIRECT_RE = re.compile(
    r"switch\s*\(\s*\$_(GET|POST|REQUEST)\s*\[\s*['\"](\w+)['\"]\s*\]\s*\)\s*\{", re.I
)
# $action = $_GET['action'] ?? '';   ...   switch ($action)
ACTION_ASSIGN_RE = re.compile(
    r"\$(\w+)\s*=\s*(?:isset\s*\(\s*)?(?:trim\s*\(\s*)?\$_(GET|POST|REQUEST)\s*\[\s*['\"](\w+)['\"]\s*\]"
)
CASE_RE = re.compile(r"\b(?:case\s+['\"]([^'\"]+)['\"]\s*:|default\s*:)")


_CONCAT_LITERAL_RE = re.compile(r"""\s*\.\s*(?P<q>['"])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.S)


@dataclass
class _Switch:
    param: str
    source: str
    body_start: int
    body_end: int


def _url_path(rel_path: str) -> str:
    return "/" + rel_path.replace("\\", "/").lstrip("/")


class PhpAnalyzer(Analyzer):
    name = "php"
    extensions = (".php", ".php3", ".php4", ".php5", ".phtml", ".inc")

    def analyze(self, ctx: FileContext, site: SiteMap) -> None:
        code = strip_c_style_comments(php_code_only(ctx.text), hash_comments=True)
        lines = LineIndex(code)

        includes = self._includes(code, ctx.rel_path)
        functions = FUNCTION_RE.findall(code) + [f"class {c}" for c in CLASS_RE.findall(code)]
        has_html = self._renders_html(ctx.text)

        switch = self._find_action_switch(code)
        if switch is None:
            route = self._build_route(ctx, code, lines, 0, len(code), has_html)
            route.includes = includes
            route.functions = functions
            if self._is_library(ctx.rel_path, route, functions, has_html):
                site.files[ctx.rel_path] = "php-library"
                if route.queries:
                    # Keep the queries visible: they are real data access, just not a page.
                    route.responses = ["library"]
                    site.routes.append(route)
                return
            site.routes.append(route)
            return

        # Front controller: shared code outside the switch applies to every action.
        outside = code[: switch.body_start] + " " * (switch.body_end - switch.body_start) + code[switch.body_end :]
        shared = self._build_route(ctx, outside, lines, 0, len(outside), has_html)

        for action, start, end in self._cases(code, switch):
            route = self._build_route(ctx, code, lines, start, end, has_html=False)
            route.action = action
            route.action_param = switch.param
            route.line = lines.line(start)
            route.includes = includes
            route.functions = functions
            known = {(p.name, p.source) for p in route.params}
            for p in shared.params:
                if p.name != switch.param and (p.name, p.source) not in known:
                    route.params.append(p)
            route.uses_session = route.uses_session or shared.uses_session
            route.flags = list(dict.fromkeys(route.flags + shared.flags))
            if not route.responses:
                route.responses = list(shared.responses) or ["html"]
            site.routes.append(route)

    # ------------------------------------------------------------------ pieces
    def _build_route(
        self, ctx: FileContext, code: str, lines: LineIndex, start: int, end: int, has_html: bool
    ) -> Route:
        segment = code[start:end]
        params: list[Param] = []
        seen: set[tuple[str, str]] = set()
        for m in SUPERGLOBAL_RE.finditer(segment):
            key = (m.group(2), _SUPERGLOBAL_SOURCES[m.group(1).upper()])
            if key not in seen:
                seen.add(key)
                params.append(Param(name=key[0], source=key[1], line=lines.line(start + m.start())))
        for m in FILTER_INPUT_RE.finditer(segment):
            key = (m.group(2), _SUPERGLOBAL_SOURCES[m.group(1).upper()])
            if key not in seen:
                seen.add(key)
                params.append(Param(name=key[0], source=key[1], line=lines.line(start + m.start())))

        methods: list[str] = []
        for m in METHOD_CHECK_RE.finditer(segment):
            method = m.group(1).upper()
            if method not in methods:
                methods.append(method)
        sources = {p.source for p in params}
        if "body" in sources or "file" in sources:
            methods.append("POST")
        if "query" in sources or not methods or has_html:
            # A page that renders HTML is always reachable with GET, even if it also handles a POST.
            methods.insert(0, "GET")
        methods = list(dict.fromkeys(methods))

        responses: list[str] = []
        if JSON_RE.search(segment):
            responses.append("json")
        if REDIRECT_RE.search(segment):
            responses.append("redirect")
        if has_html or ECHO_HTML_RE.search(segment):
            responses.append("html")

        queries = []
        for offset, body in string_literals(segment):
            if looks_like_sql(body):
                abs_offset = start + offset
                sql, literal_end = self._join_literals(code, abs_offset, body)
                stmt_end = code.find(";", literal_end)
                context = code[abs_offset : stmt_end if stmt_end != -1 else literal_end + 80]
                ref = query_ref(sql, line=lines.line(abs_offset), context=context)
                if not ref.interpolated and self._appended_with_variables(code, abs_offset, segment):
                    ref.interpolated = True
                    ref.parameterized = False
                queries.append(ref)

        flags = [label for label, pattern in LEGACY_API_PATTERNS.items() if pattern.search(segment)]

        return Route(
            path=_url_path(ctx.rel_path),
            file=ctx.rel_path,
            methods=methods,
            params=params,
            queries=queries,
            responses=responses,
            uses_session=bool(SESSION_RE.search(segment)),
            flags=flags,
            line=lines.line(start) if start else 1,
        )

    @staticmethod
    def _join_literals(code: str, offset: int, body: str) -> tuple[str, int]:
        """Join ``"SELECT ... " . "JOIN ..."`` chains of plain literals into one SQL string.

        Returns the joined SQL and the offset just past the last literal.
        """
        end = offset + len(body) + 2
        parts = [body]
        while True:
            m = _CONCAT_LITERAL_RE.match(code, end)
            if not m:
                return " ".join(parts), end
            parts.append(m.group("body"))
            end = m.end()

    @staticmethod
    def _appended_with_variables(code: str, offset: int, segment: str) -> bool:
        """True when the SQL is stored in ``$var`` and later extended with ``$var .= ... $x``."""
        m = re.search(r"\$(\w+)\s*=\s*$", code[max(0, offset - 80) : offset])
        if not m:
            return False
        for append in re.finditer(r"\$" + re.escape(m.group(1)) + r"\s*\.=\s*([^;]*);", segment):
            if "$" in append.group(1):
                return True
        return False

    @staticmethod
    def _includes(code: str, rel_path: str) -> list[str]:
        base = posixpath.dirname(rel_path.replace("\\", "/"))
        out: list[str] = []
        for target in INCLUDE_RE.findall(code):
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join(base, target)
            )
            if target not in out:
                out.append(target)
        return out

    @staticmethod
    def _renders_html(raw: str) -> bool:
        """True when the file has HTML outside its PHP blocks."""
        outside = strip_html_comments(mask_php(raw))
        return bool(re.search(r"<(html|body|div|form|table|h[1-6]|p|ul|section|main)\b", outside, re.I))

    @staticmethod
    def _is_library(rel_path: str, route: Route, functions: list[str], has_html: bool) -> bool:
        parts = rel_path.replace("\\", "/").lower().split("/")
        in_lib_dir = any(p in {"includes", "include", "inc", "lib", "libs", "classes", "config"} for p in parts[:-1])
        if rel_path.lower().endswith(".inc"):
            return True
        if route.params or has_html or "json" in route.responses or "redirect" in route.responses:
            return False
        return in_lib_dir or bool(functions)

    @staticmethod
    def _find_action_switch(code: str) -> _Switch | None:
        m = SWITCH_DIRECT_RE.search(code)
        if m:
            source, param = m.group(1).upper(), m.group(2)
            open_pos = m.end() - 1
        else:
            m = None
            for assign in ACTION_ASSIGN_RE.finditer(code):
                var, source, param = assign.group(1), assign.group(2).upper(), assign.group(3)
                sw = re.compile(r"switch\s*\(\s*\$" + re.escape(var) + r"\s*\)\s*\{").search(code, assign.end())
                if sw:
                    m = sw
                    break
            if m is None:
                return None
            open_pos = m.end() - 1
        if param.lower() not in ACTION_PARAM_NAMES:
            return None
        close = find_matching(code, open_pos, "{", "}")
        if close == -1:
            return None
        return _Switch(param=param, source=source, body_start=open_pos + 1, body_end=close)

    @staticmethod
    def _cases(code: str, switch: _Switch):
        body = code[switch.body_start : switch.body_end]
        marks = list(CASE_RE.finditer(body))
        for i, m in enumerate(marks):
            if m.group(1) is None:  # default:
                continue
            start = switch.body_start + m.end()
            end = switch.body_start + (marks[i + 1].start() if i + 1 < len(marks) else len(body))
            # "case 'a': case 'b':" share a body: give the empty one the next body.
            j = i
            while not code[start:end].strip() and j + 1 < len(marks):
                j += 1
                end = switch.body_start + (marks[j + 1].start() if j + 1 < len(marks) else len(body))
            yield m.group(1), start, end
