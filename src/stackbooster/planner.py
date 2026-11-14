"""Turn a SiteMap into a migration plan for a chosen target stack.

The plan keeps the legacy structure visible: every table, route and page in the
scan appears as one plan item that names its legacy source and its new home.
Risks that need a human decision are collected separately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from stackbooster.model import Route, SiteMap, Table
from stackbooster.targets import DEFAULT_TARGET, TargetStack, get_target

PHASES = [
    ("database", "Database models", "Recreate the schema as ORM models, parents before children."),
    ("backend", "Backend services and endpoints", "Port shared helpers, then one router per legacy file."),
    ("frontend", "Frontend layout and pages", "Shared layout first, then one page component per legacy page."),
]
_PHASE_OF_KIND = {"model": "database", "service": "backend", "endpoint": "backend", "layout": "frontend", "page": "frontend"}


@dataclass
class PlanItem:
    kind: str
    legacy_id: str
    legacy_file: str
    target_name: str
    target_file: str
    summary: str
    effort: str  # "S", "M" or "L"
    phase: str
    details: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class Risk:
    severity: str  # "high", "medium", "low"
    category: str
    where: str
    message: str


@dataclass
class MigrationPlan:
    target: dict[str, str]
    items: list[PlanItem] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    unused_tables: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def by_phase(self) -> list[tuple[str, str, str, list[PlanItem]]]:
        return [(key, title, blurb, [i for i in self.items if i.phase == key]) for key, title, blurb in PHASES]

    def effort_totals(self) -> dict[str, int]:
        totals = {"S": 0, "M": 0, "L": 0}
        for item in self.items:
            totals[item.effort] += 1
        return totals

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["effort_totals"] = self.effort_totals()
        return data


# ---------------------------------------------------------------- ordering
def table_order(tables: list[Table]) -> list[Table]:
    """Topological order: referenced tables come before the tables that point at them."""
    by_name = {t.name.lower(): t for t in tables}
    ordered: list[Table] = []
    state: dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(t: Table) -> None:
        key = t.name.lower()
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            return  # cycle: break it here, the FK will need a deferred constraint
        state[key] = 1
        for fk in t.foreign_keys:
            parent = by_name.get(fk.ref_table.lower())
            if parent is not None and parent is not t:
                visit(parent)
        state[key] = 2
        ordered.append(t)

    for t in tables:
        visit(t)
    return ordered


# ------------------------------------------------------------------ effort
def _route_effort(route: Route) -> str:
    score = len(route.queries) + len(route.params) / 3
    score += 1 if route.uses_session else 0
    score += 2 * len(route.flags)
    if score <= 2:
        return "S"
    return "M" if score <= 5 else "L"


def _table_effort(table: Table, notes: list[str]) -> str:
    score = len(table.columns) / 6 + len(table.foreign_keys) / 2 + len(notes) / 2
    if score <= 2:
        return "S"
    return "M" if score <= 4 else "L"


def _page_effort(details: dict[str, Any], partial: bool) -> str:
    if partial:
        return "S"
    score = len(details.get("forms", [])) + len(details.get("api_calls", []))
    if score <= 1:
        return "S"
    return "M" if score <= 3 else "L"


# ------------------------------------------------------------------- risks
def find_risks(site: SiteMap) -> list[Risk]:
    risks: list[Risk] = []
    session_files: set[str] = set()
    for route in site.routes:
        unsafe = [q for q in route.queries if q.interpolated]
        if unsafe:
            lines = ", ".join(str(q.line) for q in unsafe if q.line)
            risks.append(
                Risk(
                    "high",
                    "sql-injection",
                    route.id,
                    f"{len(unsafe)} query(ies) built from PHP variables (line {lines}). "
                    "Use bound parameters in the new code; do not port the string building.",
                )
            )
        for flag in route.flags:
            severity = "high" if "password" in flag or "eval" in flag or "extract" in flag else "medium"
            risks.append(Risk(severity, "legacy-api", route.id, f"Uses {flag}."))
        if route.uses_session and "library" not in route.responses and route.file not in session_files:
            session_files.add(route.file)
            risks.append(
                Risk("medium", "session", "/" + route.file, "Depends on PHP session state; plan the new auth/session design first.")
            )
        if any(p.source == "any" for p in route.params if p.name != route.action_param):
            risks.append(Risk("low", "request-params", route.id, "Reads $_REQUEST: parameter source is ambiguous."))

    for table in site.tables:
        if not table.primary_key:
            risks.append(Risk("medium", "schema", table.name, "Table has no primary key."))
        for fk in table.foreign_keys:
            if fk.inferred:
                risks.append(
                    Risk(
                        "low",
                        "schema",
                        table.name,
                        f"Relation {fk.columns[0]} -> {fk.ref_table} is inferred; check for orphan rows.",
                    )
                )
    for name in site.unknown_tables():
        risks.append(Risk("medium", "schema", name, "Queried by code but missing from the schema dump."))
    for link in site.links:
        if not link.resolved:
            risks.append(
                Risk("low", "broken-link", link.source, f"{link.kind} to '{link.target}' has no matching backend code.")
            )
    order = {"high": 0, "medium": 1, "low": 2}
    risks.sort(key=lambda r: (order[r.severity], r.category, r.where))
    return risks


# -------------------------------------------------------------------- plan
def build_plan(site: SiteMap, target: TargetStack | str = DEFAULT_TARGET) -> MigrationPlan:
    stack = get_target(target) if isinstance(target, str) else target
    plan = MigrationPlan(target=stack.describe())

    for table in table_order(site.tables):
        m = stack.map_table(table, site)
        plan.items.append(
            PlanItem("model", table.name, table.file, m.name, m.file, m.summary,
                     _table_effort(table, m.notes), "database", m.details, m.notes)
        )

    routes = [r for r in site.routes if "partial" not in r.responses]
    # Services first: endpoints depend on them.
    routes.sort(key=lambda r: (0 if "library" in r.responses else 1, r.file, r.action or ""))
    grouped: dict[str, PlanItem] = {}
    for route in routes:
        m = stack.map_route(route, site)
        if m.kind == "endpoint" and m.file in grouped:
            # Front-controller actions share one router module.
            item = grouped[m.file]
            item.details["endpoints"].extend(m.details["endpoints"])
            item.details["models"] = list(dict.fromkeys(item.details["models"] + m.details["models"]))
            item.details["uses_upload"] = item.details["uses_upload"] or m.details["uses_upload"]
            item.notes = list(dict.fromkeys(item.notes + m.notes))
            item.summary += ", " + m.summary
            item.legacy_id += f", {route.id}"
            if "SML".index(_route_effort(route)) > "SML".index(item.effort):
                item.effort = _route_effort(route)
            continue
        item = PlanItem(m.kind, route.id, route.file, m.name, m.file, m.summary,
                        _route_effort(route), "backend", m.details, m.notes)
        plan.items.append(item)
        if m.kind == "endpoint":
            grouped[m.file] = item

    pages = sorted(site.pages, key=lambda p: (not p.partial, p.file))
    for page in pages:
        m = stack.map_page(page, site)
        plan.items.append(
            PlanItem(m.kind, page.id, page.file, m.name, m.file, m.summary,
                     _page_effort(m.details, page.partial), "frontend", m.details, m.notes)
        )

    plan.risks = find_risks(site)
    plan.unused_tables = site.unused_tables()
    plan.unresolved = [f"{link.source} -> {link.target} ({link.kind})" for link in site.links if not link.resolved]
    for item in plan.items:
        item.phase = _PHASE_OF_KIND.get(item.kind, item.phase)
    return plan
