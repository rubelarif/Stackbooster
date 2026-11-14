"""Jinja-based report rendering."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from stackbooster import __version__
from stackbooster.model import SiteMap
from stackbooster.planner import MigrationPlan
from stackbooster.report.graph import mermaid_diagram

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _env(autoescape: bool) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=autoescape,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["mdcell"] = lambda v: str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")
    return env


def _context(site: SiteMap, plan: MigrationPlan) -> dict:
    return {
        "site": site,
        "plan": plan,
        "summary": site.summary(),
        "phases": plan.by_phase(),
        "effort": plan.effort_totals(),
        "mermaid": mermaid_diagram(site),
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "version": __version__,
        "project_name": Path(site.root).name,
        "risk_counts": {
            level: sum(1 for r in plan.risks if r.severity == level) for level in ("high", "medium", "low")
        },
    }


def render_markdown(site: SiteMap, plan: MigrationPlan) -> str:
    return _env(autoescape=False).get_template("report.md.j2").render(**_context(site, plan))


def render_html(site: SiteMap, plan: MigrationPlan, live: bool = False) -> str:
    """Self-contained HTML report. ``live`` adds a reload button for the dashboard."""
    return _env(autoescape=True).get_template("report.html.j2").render(live=live, **_context(site, plan))
