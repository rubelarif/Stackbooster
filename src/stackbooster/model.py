"""The unified structure model.

Every analyzer writes into a :class:`SiteMap`. The model is plain dataclasses so
it serializes to JSON without extra dependencies, and it can be loaded back
with :meth:`SiteMap.from_dict` for reporting or diffing later.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class Param:
    """A request parameter read by a backend route."""

    name: str
    source: str  # "query", "body", "any", "cookie", "file", "path"
    line: int | None = None


@dataclass
class QueryRef:
    """A SQL statement found in backend code."""

    kind: str  # SELECT / INSERT / UPDATE / DELETE / OTHER
    tables: list[str] = field(default_factory=list)
    line: int | None = None
    snippet: str = ""
    parameterized: bool = False  # uses ? or :name placeholders
    interpolated: bool = False  # built from PHP variables (possible SQL injection)


@dataclass
class Route:
    """A backend endpoint, for example ``/cart.php`` or ``/api.php?action=add``."""

    path: str
    file: str
    methods: list[str] = field(default_factory=lambda: ["GET"])
    action: str | None = None  # front-controller sub-action, if any
    action_param: str | None = None  # request parameter that selects the action
    params: list[Param] = field(default_factory=list)
    queries: list[QueryRef] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    responses: list[str] = field(default_factory=list)  # "html", "json", "redirect"
    uses_session: bool = False
    flags: list[str] = field(default_factory=list)  # legacy API usage worth flagging, e.g. "mysql_*"
    line: int | None = None

    @property
    def id(self) -> str:
        return f"{self.path}?action={self.action}" if self.action else self.path

    @property
    def tables(self) -> list[str]:
        seen: dict[str, None] = {}
        for q in self.queries:
            for t in q.tables:
                seen.setdefault(t, None)
        return list(seen)


@dataclass
class FormField:
    name: str
    type: str = "text"
    required: bool = False


@dataclass
class Form:
    action: str
    method: str = "GET"
    fields: list[FormField] = field(default_factory=list)
    line: int | None = None


@dataclass
class AjaxCall:
    """A client-side request to a backend endpoint."""

    url: str
    method: str = "GET"
    library: str = "jquery"  # "jquery", "fetch", "xhr"
    line: int | None = None
    file: str | None = None


@dataclass
class Page:
    """A user-facing page (an HTML file, a template, or a PHP file that renders HTML)."""

    path: str
    file: str
    title: str | None = None
    forms: list[Form] = field(default_factory=list)
    ajax_calls: list[AjaxCall] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    element_ids: list[str] = field(default_factory=list)
    partial: bool = False  # included by other files (header, footer, layout)

    @property
    def id(self) -> str:
        return self.path


@dataclass
class Column:
    name: str
    type: str
    length: str | None = None
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False
    auto_increment: bool = False
    unique: bool = False
    unsigned: bool = False
    enum_values: list[str] = field(default_factory=list)


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None = None
    on_update: str | None = None
    name: str | None = None
    inferred: bool = False  # True when guessed from naming, not declared in the schema


@dataclass
class Index:
    name: str
    columns: list[str]
    unique: bool = False


@dataclass
class Table:
    name: str
    file: str
    columns: list[Column] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    engine: str | None = None

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name.lower() == name.lower():
                return c
        return None


@dataclass
class Link:
    """A connection from a page (or JS file) to a backend route."""

    source: str  # page id or JS file
    target: str  # route id, or the raw URL if unresolved
    kind: str  # "form", "ajax", "link", "script-ajax"
    method: str = "GET"
    resolved: bool = True


@dataclass
class SiteMap:
    root: str
    routes: list[Route] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    script_calls: list[AjaxCall] = field(default_factory=list)  # calls found in standalone .js files
    links: list[Link] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # relative path -> detected kind
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ lookup
    def route(self, route_id: str) -> Route | None:
        return next((r for r in self.routes if r.id == route_id), None)

    def page(self, page_id: str) -> Page | None:
        return next((p for p in self.pages if p.id == page_id), None)

    def table(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name.lower() == name.lower()), None)

    def links_from(self, source: str) -> list[Link]:
        return [link for link in self.links if link.source == source]

    def links_to(self, target: str) -> list[Link]:
        return [link for link in self.links if link.target == target]

    # --------------------------------------------------------------- summaries
    def summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for kind in self.files.values():
            kinds[kind] = kinds.get(kind, 0) + 1
        return {
            "files": len(self.files),
            "files_by_kind": dict(sorted(kinds.items())),
            "routes": len(self.routes),
            "pages": len(self.pages),
            "forms": sum(len(p.forms) for p in self.pages),
            "ajax_calls": sum(len(p.ajax_calls) for p in self.pages) + len(self.script_calls),
            "tables": len(self.tables),
            "foreign_keys": sum(len(t.foreign_keys) for t in self.tables),
            "links": len(self.links),
            "unresolved_links": sum(1 for link in self.links if not link.resolved),
            "warnings": len(self.warnings),
        }

    def unused_tables(self) -> list[str]:
        """Tables defined in the schema that no route queries."""
        used = {t.lower() for r in self.routes for t in r.tables}
        return [t.name for t in self.tables if t.name.lower() not in used]

    def unknown_tables(self) -> list[str]:
        """Tables queried by routes that the schema does not define."""
        defined = {t.name.lower() for t in self.tables}
        found: dict[str, None] = {}
        for r in self.routes:
            for t in r.tables:
                if t.lower() not in defined:
                    found.setdefault(t, None)
        return list(found)

    # ------------------------------------------------------------ (de)serialize
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = SCHEMA_VERSION
        data["summary"] = self.summary()
        return data

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> SiteMap:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiteMap:
        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {version!r}, expected {SCHEMA_VERSION}")

        def route(d: dict[str, Any]) -> Route:
            d = dict(d)
            d["params"] = [Param(**p) for p in d.get("params", [])]
            d["queries"] = [QueryRef(**q) for q in d.get("queries", [])]
            return Route(**d)

        def page(d: dict[str, Any]) -> Page:
            d = dict(d)
            d["forms"] = [
                Form(**{**f, "fields": [FormField(**x) for x in f.get("fields", [])]})
                for f in d.get("forms", [])
            ]
            d["ajax_calls"] = [AjaxCall(**a) for a in d.get("ajax_calls", [])]
            return Page(**d)

        def table(d: dict[str, Any]) -> Table:
            d = dict(d)
            d["columns"] = [Column(**c) for c in d.get("columns", [])]
            d["foreign_keys"] = [ForeignKey(**f) for f in d.get("foreign_keys", [])]
            d["indexes"] = [Index(**i) for i in d.get("indexes", [])]
            return Table(**d)

        return cls(
            root=data["root"],
            routes=[route(r) for r in data.get("routes", [])],
            pages=[page(p) for p in data.get("pages", [])],
            tables=[table(t) for t in data.get("tables", [])],
            script_calls=[AjaxCall(**a) for a in data.get("script_calls", [])],
            links=[Link(**link) for link in data.get("links", [])],
            files=dict(data.get("files", {})),
            warnings=list(data.get("warnings", [])),
        )
