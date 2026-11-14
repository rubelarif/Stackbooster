"""Connect frontend pages to the backend routes they call.

After every file is analyzed, the linker turns form actions, AJAX URLs and
links into :class:`~stackbooster.model.Link` objects, resolving relative URLs
against the page's own directory.
"""

from __future__ import annotations

import posixpath
from urllib.parse import parse_qs, urlsplit

from stackbooster.model import Link, Route, SiteMap


def normalize_url(url: str, source_file: str) -> tuple[str, dict[str, list[str]]] | None:
    """Turn a URL found in ``source_file`` into a site-absolute path and its query.

    Returns ``None`` for URLs that point off-site or are not requests
    (``mailto:``, ``javascript:``, ``#anchor``).
    """
    url = url.strip()
    if not url or url.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
        return None
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") or url.startswith("//"):
        return None  # absolute URLs usually point to other hosts (CDNs, partners)
    path = parts.path
    if not path:
        path = "/" + source_file
    elif not path.startswith("/"):
        base = posixpath.dirname("/" + source_file)
        path = posixpath.join(base, path)
    trailing_slash = path.endswith("/")
    path = posixpath.normpath(path)
    if trailing_slash or path == "/":
        # Directory URL: assume the default document
        path = path.rstrip("/") + "/index.php"
    query = parse_qs(parts.query, keep_blank_values=True)
    return path, query


class _RouteIndex:
    def __init__(self, routes: list[Route]) -> None:
        self.by_path: dict[str, list[Route]] = {}
        for r in routes:
            self.by_path.setdefault(r.path.lower(), []).append(r)

    def resolve(self, path: str, query: dict[str, list[str]]) -> Route | None:
        candidates = None
        for option in _path_options(path.lower()):
            candidates = self.by_path.get(option)
            if candidates:
                break
        if not candidates:
            return None
        plain = [r for r in candidates if r.action is None]
        actions = [r for r in candidates if r.action is not None]
        for r in actions:
            values = query.get(r.action_param or "", [])
            if r.action in values:
                return r
        return plain[0] if plain else (actions[0] if len(actions) == 1 else None)


def _path_options(path: str) -> list[str]:
    """``/products`` may be served by ``/products.php`` or ``/products/index.php``."""
    options = [path]
    if posixpath.splitext(path)[1] == "":
        options += [path + ".php", path + "/index.php", path + ".html"]
    if path.endswith("/index.php"):
        options.append(path[: -len("index.php")] + "index.html")
    return options


def link_site(site: SiteMap) -> None:
    """Fill ``site.links`` from the pages and script calls already in ``site``."""
    index = _RouteIndex(site.routes)
    page_paths = {p.path.lower(): p.path for p in site.pages}
    links: list[Link] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(source: str, source_file: str, url: str, kind: str, method: str) -> None:
        norm = normalize_url(url, source_file)
        if norm is None:
            return
        path, query = norm
        route = index.resolve(path, query)
        if route is not None:
            target, resolved = route.id, True
        elif any(o in page_paths for o in _path_options(path.lower())):
            option = next(o for o in _path_options(path.lower()) if o in page_paths)
            target, resolved = page_paths[option], True
        else:
            target, resolved = url, False
        key = (source, target, kind, method)
        if key in seen:
            return
        seen.add(key)
        links.append(Link(source=source, target=target, kind=kind, method=method, resolved=resolved))

    # A partial (header.php) is rendered inside the page that includes it, so its
    # relative URLs resolve against that page's folder, not the partial's own.
    includer: dict[str, str] = {}
    for route in site.routes:
        for inc in route.includes:
            includer.setdefault(inc.lower(), route.file)

    def base_file(page) -> str:
        return includer.get(page.file.lower(), page.file) if page.partial else page.file

    for page in site.pages:
        base = base_file(page)
        for form in page.forms:
            add(page.id, base, form.action or page.file.rsplit("/", 1)[-1], "form", form.method)
        for call in page.ajax_calls:
            add(page.id, base, call.url, "ajax", call.method)
        for href in page.links:
            if _is_static_asset(href):
                continue
            add(page.id, base, href, "link", "GET")

    # Calls in standalone JS files: attribute them to every page that loads the file.
    loaders: dict[str, list[tuple[str, str]]] = {}
    for page in site.pages:
        for src in page.scripts:
            norm = normalize_url(src, base_file(page))
            if norm:
                loaders.setdefault(norm[0].lstrip("/").lower(), []).append((page.id, base_file(page)))
    for call in site.script_calls:
        js_file = (call.file or "").lower()
        pages = loaders.get(js_file)
        if pages:
            # Relative URLs in a script resolve against the page that loads it.
            for page_id, base in pages:
                add(page_id, base, call.url, "script-ajax", call.method)
        else:
            add("/" + (call.file or "unknown.js"), call.file or "", call.url, "script-ajax", call.method)

    site.links = links


_STATIC_EXT = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip",
    ".woff", ".woff2", ".ttf", ".mp4", ".webp",
}


def _is_static_asset(href: str) -> bool:
    path = urlsplit(href).path
    return posixpath.splitext(path)[1].lower() in _STATIC_EXT
