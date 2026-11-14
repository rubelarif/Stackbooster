"""Default target: FastAPI + SQLAlchemy 2.0 on the backend, React on the frontend.

Mapping rules, in short:

* each table becomes a SQLAlchemy declarative model in ``backend/app/models.py``;
* each legacy PHP file becomes a FastAPI router module, and each HTTP method
  (or front-controller action) becomes one endpoint under ``/api``;
* pages that rendered HTML on the server get a JSON endpoint for their data
  and a React page component that renders it;
* included header/footer templates become shared React layout components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from stackbooster.model import Column, FormField, Page, Route, SiteMap, Table
from stackbooster.naming import kebab, model_class_name, pascal, singular, snake, words
from stackbooster.targets.base import TargetMapping, TargetStack

TEMPLATE_DIR = Path(__file__).parent / "templates" / "fastapi_react"

_INT_TYPES = {"INT", "INTEGER", "MEDIUMINT"}
_TEXT_TYPES = {"TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT", "CLOB"}
_BLOB_TYPES = {"BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB", "BINARY", "VARBINARY"}


@dataclass
class ColumnSpec:
    name: str
    attr: str
    sa_type: str
    py_type: str
    nullable: bool
    primary_key: bool
    autoincrement: bool
    unique: bool
    server_default: str | None
    foreign_key: str | None
    added: bool = False  # not in the legacy schema

    def mapped_column_args(self) -> str:
        args: list[str] = []
        if self.attr != self.name:
            args.append(repr(self.name))
        args.append(self.sa_type)
        if self.foreign_key:
            args.append(f'ForeignKey("{self.foreign_key}")')
        if self.primary_key:
            args.append("primary_key=True")
        if self.autoincrement:
            args.append("autoincrement=True")
        if self.unique:
            args.append("unique=True")
        if not self.primary_key:
            args.append(f"nullable={self.nullable}")
        if self.server_default:
            args.append(f"server_default={self.server_default}")
        return ", ".join(args)


def sqlalchemy_type(col: Column, table_name: str = "") -> tuple[str, str]:
    """Return ``(SQLAlchemy type expression, Python annotation)`` for a MySQL column."""
    t = col.type.upper()
    length = col.length
    if t in _INT_TYPES:
        return "Integer", "int"
    if t == "BIGINT" or t in ("SERIAL", "BIGSERIAL"):
        return "BigInteger", "int"
    if t == "SMALLINT" or t == "YEAR":
        return "SmallInteger", "int"
    if t in ("TINYINT", "BIT", "BOOL", "BOOLEAN"):
        if t != "TINYINT" or length == "1":
            return "Boolean", "bool"
        return "SmallInteger", "int"
    if t in ("DECIMAL", "NUMERIC", "DEC", "FIXED"):
        if length and "," in length:
            p, s = length.split(",", 1)
            return f"Numeric({p}, {s})", "Decimal"
        return "Numeric", "Decimal"
    if t in ("FLOAT", "DOUBLE", "REAL", "DOUBLE PRECISION"):
        return "Float", "float"
    if t in ("VARCHAR", "CHAR", "CHARACTER", "NVARCHAR", "NCHAR", "CHARACTER VARYING"):
        return (f"String({length})" if length else "String"), "str"
    if t in _TEXT_TYPES:
        return "Text", "str"
    if t == "DATE":
        return "Date", "date"
    if t in ("DATETIME", "TIMESTAMP"):
        return "DateTime", "datetime"
    if t == "TIME":
        return "Time", "time"
    if t in _BLOB_TYPES:
        return "LargeBinary", "bytes"
    if t == "JSON":
        return "JSON", "dict"
    if t == "ENUM":
        values = ", ".join(repr(v) for v in col.enum_values)
        enum_name = snake(f"{table_name}_{col.name}") if table_name else snake(col.name)
        return f'Enum({values}, name="{enum_name}")', "str"
    if t == "SET":
        return "String(255)", "str"
    return "String", "str"


def _server_default(col: Column) -> str | None:
    if col.default is None:
        return None
    if col.default.upper() in ("CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()", "NOW()"):
        return "func.now()"
    return repr(col.default)


def guess_param_type(name: str, field: FormField | None = None) -> str:
    """Pick a Python type for a request parameter from its name and the HTML form field."""
    if field is not None:
        if field.type == "number":
            return "int"
        if field.type == "checkbox":
            return "bool"
        if field.type == "file":
            return "UploadFile"
    lowered = name.lower()
    if lowered in ("id", "page", "limit", "offset", "qty", "quantity", "count") or lowered.endswith("_id"):
        return "int"
    if lowered.startswith(("is_", "has_")):
        return "bool"
    return "str"


class FastApiReactTarget(TargetStack):
    key = "fastapi-react"
    label = "FastAPI + SQLAlchemy + React"
    backend = "FastAPI (Python 3.12)"
    frontend = "React 18 + React Router + TypeScript"
    orm = "SQLAlchemy 2.0"

    # ----------------------------------------------------------------- tables
    def model_columns(self, table: Table) -> list[ColumnSpec]:
        fk_by_col = {fk.columns[0]: fk for fk in table.foreign_keys if len(fk.columns) == 1}
        specs: list[ColumnSpec] = []
        if not table.primary_key:
            specs.append(ColumnSpec("id", "id", "Integer", "int", False, True, True, False, None, None, added=True))
        for col in table.columns:
            sa_type, py_type = sqlalchemy_type(col, table.name)
            fk = fk_by_col.get(col.name)
            attr = snake(col.name)
            if attr in ("metadata", "registry"):  # reserved on declarative models
                attr += "_"
            specs.append(
                ColumnSpec(
                    name=col.name,
                    attr=attr,
                    sa_type=sa_type,
                    py_type=py_type,
                    nullable=col.nullable and not col.primary_key,
                    primary_key=col.primary_key,
                    autoincrement=col.auto_increment,
                    unique=col.unique or any(ix.unique and ix.columns == [col.name] for ix in table.indexes),
                    server_default=_server_default(col),
                    foreign_key=f"{fk.ref_table}.{fk.ref_columns[0]}" if fk and fk.ref_columns else None,
                )
            )
        return specs

    def relationships(self, table: Table, site: SiteMap) -> list[dict[str, str]]:
        """Both sides of every single-column foreign key that touches ``table``."""
        rels: list[dict[str, str]] = []

        # Many-to-one: this table holds the foreign key.
        for fk in table.foreign_keys:
            if len(fk.columns) != 1 or site.table(fk.ref_table) is None:
                continue
            col = fk.columns[0]
            parent_cls = model_class_name(fk.ref_table)
            nullable = next((c.nullable for c in table.columns if c.name == col), True)
            rels.append(
                {
                    "attr": self._forward_name(table, col, fk.ref_table),
                    "target": parent_cls,
                    "kind": "many-to-one",
                    "annotation": f'Mapped["{parent_cls}{" | None" if nullable else ""}"]',
                    "foreign_key_attr": snake(col),
                    "back_populates": self._reverse_name(table.name, fk.ref_table, col, site),
                    "inferred": "yes" if fk.inferred else "",
                }
            )

        # One-to-many: other tables point at this one.
        for other in site.tables:
            for fk in other.foreign_keys:
                if len(fk.columns) != 1 or fk.ref_table.lower() != table.name.lower():
                    continue
                col = fk.columns[0]
                child_cls = model_class_name(other.name)
                rels.append(
                    {
                        "attr": self._reverse_name(other.name, table.name, col, site),
                        "target": child_cls,
                        "kind": "one-to-many",
                        "annotation": f'Mapped[list["{child_cls}"]]',
                        "foreign_key_attr": "",
                        "back_populates": self._forward_name(other, col, table.name),
                        "inferred": "yes" if fk.inferred else "",
                    }
                )
        return rels

    @staticmethod
    def _forward_name(child: Table, column: str, parent: str) -> str:
        """``category`` for ``products.category_id``; ``category_ref`` if a column is already called that."""
        stem = column[:-3] if column.lower().endswith("_id") else singular(parent)
        name = snake(stem)
        if any(snake(c.name) == name for c in child.columns):
            name += "_ref"
        return name

    @staticmethod
    def _reverse_name(child: str, parent: str, column: str, site: SiteMap) -> str:
        """``products`` for one FK from products to categories; ``orders_by_buyer`` when there are several."""
        child_table = site.table(child)
        count = sum(
            1 for fk in (child_table.foreign_keys if child_table else []) if fk.ref_table.lower() == parent.lower()
        )
        name = snake(child)
        if count > 1:
            stem = column[:-3] if column.lower().endswith("_id") else column
            name = f"{name}_by_{snake(stem)}"
        return name

    def map_table(self, table: Table, site: SiteMap) -> TargetMapping:
        cls = model_class_name(table.name)
        columns = self.model_columns(table)
        notes: list[str] = []
        if table.engine and table.engine.upper() == "MYISAM":
            notes.append("Legacy table is MyISAM (no transactions, no enforced foreign keys). Create it with real constraints.")
        if not table.primary_key:
            notes.append("No primary key in the legacy schema: the model adds a surrogate `id` column.")
        for fk in table.foreign_keys:
            if fk.inferred:
                notes.append(
                    f"Relation {table.name}.{fk.columns[0]} -> {fk.ref_table}.{fk.ref_columns[0]} is inferred from the "
                    "column name. Check the data for orphans before adding the constraint."
                )
            ref = site.table(fk.ref_table)
            if ref is None:
                notes.append(f"Foreign key to unknown table {fk.ref_table}: the model leaves it as a plain column.")
                continue
            for local, remote in zip(fk.columns, fk.ref_columns, strict=False):
                lc, rc = table.column(local), ref.column(remote)
                if lc and rc and (lc.type != rc.type or lc.unsigned != rc.unsigned):
                    notes.append(
                        f"{table.name}.{local} ({lc.type}{' unsigned' if lc.unsigned else ''}) does not match "
                        f"{ref.name}.{remote} ({rc.type}{' unsigned' if rc.unsigned else ''}); align the types."
                    )
        for col in table.columns:
            if col.type.upper() == "SET":
                notes.append(f"Column {col.name} is a MySQL SET; stored as a string. Consider a join table.")
        return TargetMapping(
            kind="model",
            name=cls,
            file="backend/app/models.py",
            summary=f"class {cls}(Base)  ->  table {table.name}",
            details={
                "table": table.name,
                "columns": [{**c.__dict__, "args": c.mapped_column_args()} for c in columns],
                "relationships": self.relationships(table, site),
            },
            notes=notes,
        )

    # ----------------------------------------------------------------- routes
    @staticmethod
    def _legacy_stem(file: str) -> str:
        return re.sub(r"\.\w+$", "", file.replace("\\", "/"))

    def api_path(self, route: Route) -> str:
        stem = self._legacy_stem(route.file)
        parts = [kebab(p) for p in stem.split("/") if p]
        if parts and parts[-1] == "index":
            parts = parts[:-1] or ["home"]
        path = "/" + "/".join(parts)
        if not path.startswith("/api"):
            path = "/api" + path
        if route.action:
            path += "/" + kebab(route.action)
        return path

    def page_path(self, file: str) -> str:
        parts = [kebab(p) for p in self._legacy_stem(file).split("/") if p]
        if parts and parts[-1] == "index":
            parts = parts[:-1]
        return "/" + "/".join(parts)

    def router_module(self, route: Route) -> str:
        return snake(self._legacy_stem(route.file).replace("/", "_"))

    def _form_fields_for(self, route: Route, site: SiteMap) -> dict[str, FormField]:
        """Form fields from pages that submit to this route, keyed by name."""
        fields: dict[str, FormField] = {}
        for page in site.pages:
            for form in page.forms:
                for link in site.links_from(page.id):
                    if link.kind == "form" and link.target == route.id and link.method == form.method:
                        for f in form.fields:
                            fields.setdefault(f.name, f)
        return fields

    def endpoints(self, route: Route, site: SiteMap) -> list[dict]:
        """One endpoint description per HTTP method of the route."""
        fields = self._form_fields_for(route, site)
        path = self.api_path(route)
        stem = self._legacy_stem(route.file)
        if stem.split("/")[-1] == "index":
            stem = stem[: -len("index")] + "home"
        base_name = snake(route.action) if route.action else snake(stem.replace("/", "_"))
        out = []
        for method in route.methods:
            if method == "GET":
                sources = {"query", "any", "cookie"}
            else:
                sources = {"body", "any", "file"}
            params = []
            for p in route.params:
                if p.source not in sources or p.name == route.action_param:
                    continue
                field = fields.get(p.name)
                params.append(
                    {
                        "name": snake(p.name),
                        "legacy_name": p.name,
                        "type": "UploadFile" if p.source == "file" else guess_param_type(p.name, field),
                        "required": bool(field and field.required),
                        "source": p.source,
                    }
                )
            fn = base_name if len(route.methods) == 1 and route.action else f"{method.lower()}_{base_name}"
            body_model = (
                pascal(f"{route.action or self._legacy_stem(route.file).replace('/', '_')}_{method.lower()}_request")
                if method != "GET" and any(p["type"] != "UploadFile" for p in params)
                else None
            )
            out.append({"method": method, "path": path, "function": fn, "params": params, "body_model": body_model})
        return out

    def map_route(self, route: Route, site: SiteMap) -> TargetMapping:
        module = self.router_module(route)
        if "library" in route.responses:
            return TargetMapping(
                kind="service",
                name=module,
                file=f"backend/app/services/{module}.py",
                summary=f"service module {module} (helpers: {', '.join(route.functions) or 'none'})",
                details={"functions": route.functions, "tables": route.tables},
                notes=["Shared helper code: port the functions as service functions that take a SQLAlchemy Session."],
            )
        endpoints = self.endpoints(route, site)
        notes: list[str] = []
        if route.uses_session:
            notes.append("Reads the PHP session: replace with a signed-cookie session or token auth dependency.")
        if any(p.source == "any" for p in route.params):
            notes.append("Uses $_REQUEST, which mixes query and body values; decide per parameter where it belongs.")
        if "html" in route.responses:
            notes.append("Rendered HTML on the server: the endpoint returns the page data as JSON for the React page.")
        if "redirect" in route.responses:
            notes.append("Sends a Location redirect: return a JSON result and let the React page navigate.")
        hints = [self.orm_hint(q.kind, q.tables) for q in route.queries]
        for e in endpoints:
            e["orm_hints"] = hints
        model_names = [model_class_name(t) for t in route.tables if site.table(t)]
        summary = ", ".join(f"{e['method']} {e['path']}" for e in endpoints)
        return TargetMapping(
            kind="endpoint",
            name=module,
            file=f"backend/app/routers/{module}.py",
            summary=summary,
            details={
                "endpoints": endpoints,
                "uses_upload": any(p["type"] == "UploadFile" for e in endpoints for p in e["params"]),
                "models": model_names,
            },
            notes=notes,
        )

    @staticmethod
    def orm_hint(kind: str, tables: list[str]) -> str:
        models = [model_class_name(t) for t in tables] or ["Model"]
        first = models[0]
        if kind == "SELECT":
            joins = "".join(f".join({m})" for m in models[1:])
            return f"db.scalars(select({first}){joins}.where(...)).all()"
        if kind == "INSERT":
            return f"db.add({first}(...)); db.commit()"
        if kind == "UPDATE":
            return f"db.execute(update({first}).where(...).values(...)); db.commit()"
        if kind == "DELETE":
            return f"db.execute(delete({first}).where(...)); db.commit()"
        return "db.execute(text(...))  # review by hand"

    # ------------------------------------------------------------------ pages
    def map_page(self, page: Page, site: SiteMap) -> TargetMapping:
        stem = self._legacy_stem(page.file)
        if page.partial:
            name = pascal(stem.split("/")[-1])
            return TargetMapping(
                kind="layout",
                name=name,
                file=f"frontend/src/components/{name}.tsx",
                summary=f"<{name} /> shared layout component",
                details={"element_ids": page.element_ids, "links": page.links},
                notes=["Included by other pages: render it once in the app layout instead of in every page."],
            )

        name = pascal(stem.replace("/", "_")) + "Page"
        if name == "IndexPage":
            name = "HomePage"
        own_route = next(
            (r for r in site.routes if r.file == page.file and r.action is None and "GET" in r.methods), None
        )
        data_endpoint = f"GET {self.api_path(own_route)}" if own_route and own_route.tables else None
        route_path = self.page_path(page.file)
        if own_route and any(p.name == "id" and p.source == "query" for p in own_route.params):
            route_path = route_path.rstrip("/") + "/:id"  # product.php?id=5 -> /product/5
        path_params = ["id"] if route_path.endswith("/:id") else []

        forms = []
        for i, form in enumerate(page.forms):
            target = next(
                (
                    link.target
                    for link in site.links_from(page.id)
                    if link.kind == "form" and link.method == form.method
                    and (not form.action or link.target.endswith(form.action.split("?")[0]))
                ),
                None,
            )
            route = site.route(target) if target else None
            if route is None:
                submits_to = f"unresolved: {form.action or '(self)'}"
            else:
                method = form.method if form.method in route.methods else route.methods[0]
                submits_to = f"{method} {self.api_path(route)}"
            forms.append(
                {
                    "component": f"{name[:-4]}Form{i + 1 if len(page.forms) > 1 else ''}",
                    "method": form.method,
                    "submits_to": submits_to,
                    "fields": [f.__dict__ for f in form.fields],
                }
            )

        api_calls = []
        for link in site.links_from(page.id):
            if link.kind not in ("ajax", "script-ajax"):
                continue
            route = site.route(link.target)
            api_calls.append(
                {
                    "legacy": link.target,
                    "endpoint": f"{link.method} {self.api_path(route)}" if route else "unresolved",
                    "client_function": _camel(route.action or self._legacy_stem(route.file)) if route else None,
                }
            )

        notes = []
        if page.element_ids:
            notes.append("Keep the legacy element ids (" + ", ".join(page.element_ids[:6]) + ") so CSS and tests carry over.")
        if any(f["submits_to"].startswith("unresolved") for f in forms):
            notes.append("A form posts to a URL with no backend code in the scan: confirm whether it is still needed.")
        return TargetMapping(
            kind="page",
            name=name,
            file=f"frontend/src/pages/{name}.tsx",
            summary=f"<{name} /> at {route_path}",
            details={
                "route_path": route_path,
                "path_params": path_params,
                "title": page.title,
                "data_endpoint": data_endpoint,
                "forms": forms,
                "api_calls": api_calls,
            },
            notes=notes,
        )

    # --------------------------------------------------------------- scaffold
    def scaffold(self, site: SiteMap, plan) -> dict[str, str]:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        models = [i for i in plan.items if i.kind == "model"]
        endpoints = [i for i in plan.items if i.kind == "endpoint"]
        services = [i for i in plan.items if i.kind == "service"]
        pages = [i for i in plan.items if i.kind == "page"]
        layouts = [i for i in plan.items if i.kind == "layout"]

        files: dict[str, str] = {}
        files["backend/app/__init__.py"] = ""
        files["backend/app/database.py"] = env.get_template("database.py.j2").render()
        files["backend/app/models.py"] = env.get_template("models.py.j2").render(models=models)
        files["backend/app/schemas.py"] = env.get_template("schemas.py.j2").render(endpoints=endpoints)
        files["backend/app/routers/__init__.py"] = ""
        router_tpl = env.get_template("router.py.j2")
        for item in endpoints:
            files[item.target_file] = router_tpl.render(item=item)
        if services:
            files["backend/app/services/__init__.py"] = ""
            for item in services:
                files[item.target_file] = env.get_template("service.py.j2").render(item=item)
        files["backend/app/main.py"] = env.get_template("main.py.j2").render(endpoints=endpoints)
        files["backend/requirements.txt"] = env.get_template("requirements.txt.j2").render()

        all_endpoints = [e for item in endpoints for e in item.details["endpoints"]]
        files["frontend/src/api/client.ts"] = env.get_template("client.ts.j2").render(
            endpoints=all_endpoints, camel=_camel
        )
        page_tpl = env.get_template("page.tsx.j2")
        for item in pages:
            files[item.target_file] = page_tpl.render(item=item, camel=_camel)
        layout_tpl = env.get_template("layout.tsx.j2")
        for item in layouts:
            files[item.target_file] = layout_tpl.render(item=item)
        files["frontend/src/App.tsx"] = env.get_template("App.tsx.j2").render(pages=pages, layouts=layouts)
        return files


def _camel(name: str) -> str:
    parts = words(name.replace("/", "_"))
    if not parts:
        return "call"
    return parts[0] + "".join(p.capitalize() for p in parts[1:])
