"""A small local web dashboard built on the standard library.

It needs no extra dependencies: ``http.server`` serves the HTML report and the
JSON model. Each request to ``/`` re-scans the project, so editing a legacy
file and reloading the page shows the change. It binds to 127.0.0.1 by
default and is meant for local use only.
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from stackbooster.planner import build_plan
from stackbooster.report import mermaid_diagram, render_html, render_markdown
from stackbooster.scanner import scan


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "stackbooster-dashboard"

    def __init__(self, *args, root: Path, target: str, **kwargs) -> None:
        self.root = root
        self.target = target
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - signature from the base class
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def _send(self, body: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        routes = {
            "/": self._report,
            "/report.md": self._markdown,
            "/api/sitemap.json": self._sitemap,
            "/api/plan.json": self._plan,
            "/api/graph.mmd": self._graph,
        }
        handler = routes.get(path)
        if handler is None:
            self._send(json.dumps({"error": "not found", "paths": sorted(routes)}), "application/json", HTTPStatus.NOT_FOUND)
            return
        try:
            handler()
        except Exception as exc:  # show the failure instead of dropping the connection
            self._send(json.dumps({"error": str(exc)}), "application/json", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _analyze(self):
        site = scan(self.root)
        return site, build_plan(site, self.target)

    def _report(self) -> None:
        site, plan = self._analyze()
        self._send(render_html(site, plan, live=True), "text/html")

    def _markdown(self) -> None:
        site, plan = self._analyze()
        self._send(render_markdown(site, plan), "text/markdown")

    def _sitemap(self) -> None:
        site, _ = self._analyze()
        self._send(site.to_json(), "application/json")

    def _plan(self) -> None:
        _, plan = self._analyze()
        self._send(json.dumps(plan.to_dict(), indent=2), "application/json")

    def _graph(self) -> None:
        site, _ = self._analyze()
        self._send(mermaid_diagram(site), "text/plain")


def make_server(root: str | Path, target: str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    handler = partial(DashboardHandler, root=root, target=target)
    return ThreadingHTTPServer((host, port), handler)


def serve(root: str | Path, target: str, host: str = "127.0.0.1", port: int = 8765, quiet: bool = False) -> None:
    server = make_server(root, target, host, port)
    server.quiet = quiet  # type: ignore[attr-defined]
    print(f"stackbooster dashboard on http://{host}:{server.server_address[1]}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def serve_in_thread(root: str | Path, target: str, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Start the dashboard on a background thread. Used by tests; port 0 picks a free port."""
    server = make_server(root, target, host, port)
    server.quiet = True  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
