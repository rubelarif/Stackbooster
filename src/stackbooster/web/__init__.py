"""Local dashboard that re-scans the legacy project on every page load."""

from stackbooster.web.server import DashboardHandler, make_server, serve

__all__ = ["DashboardHandler", "make_server", "serve"]
