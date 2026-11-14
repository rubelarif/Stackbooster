# stackbooster

stackbooster reads the source of a legacy website and maps its structure: backend
routes, frontend pages and forms, the calls between them, and the database
schema. From that map it builds a migration plan for a modern stack, so a team
can rebuild the site in a new language without losing the shape of the old one.

The default target is **FastAPI + SQLAlchemy 2.0 + React**. Targets are
pluggable (see [Adding a target stack](#adding-a-target-stack)).

This is a prototype. It reads source files as text and does not need PHP,
MySQL, Node or Docker installed.

## What it understands today

| Layer | Legacy input | What is extracted |
|---|---|---|
| Backend | PHP files (`.php`, `.inc`, `.phtml`) | One route per file; front-controller `switch ($_GET['action'])` split into one route per `case`; `$_GET`/`$_POST`/`$_REQUEST`/`$_COOKIE`/`$_FILES` parameters; HTTP methods; embedded SQL and the tables it touches; JSON / redirect / HTML responses; session use; `include`/`require`; helper functions; legacy APIs such as `mysql_*` and md5 passwords |
| Frontend | HTML pages and PHP/`.tpl` templates, jQuery and plain JS | Titles, forms and fields (type, required), links, scripts, stylesheets, element ids, `$.ajax`/`$.get`/`$.post`/`$.getJSON`/`.load`, `fetch`, `XMLHttpRequest`, `axios`, inline `onclick` handlers |
| Database | MySQL / MariaDB dumps (`mysqldump`, phpMyAdmin) | Tables, columns, types, defaults, enums, primary keys, indexes, foreign keys (inline, table-level and `ALTER TABLE`), engine; relations inferred from `<thing>_id` columns when none are declared |
| Links | All of the above | Page -> route links for forms, AJAX calls and navigation, resolved relative to the page; header/footer partials resolve against the page that includes them |

From the map, the planner produces:

- **Phase 1, database:** one SQLAlchemy model per table, ordered parents first.
- **Phase 2, backend:** one FastAPI router per legacy file, one endpoint per method or action, Pydantic request models typed from the HTML forms that post to them.
- **Phase 3, frontend:** shared layout components for included partials, one React page per legacy page, with its forms and API calls listed.
- **Risks:** SQL built from request variables, legacy PHP APIs, session dependencies, `$_REQUEST`, missing primary keys, inferred relations, broken links.
- **Leftovers:** tables no code queries, links that point at nothing.

## Install

Python 3.11 or newer (developed on 3.12).

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Runtime dependencies are only `click` and `jinja2`. The `dev` extra adds
`pytest`, plus `sqlalchemy` and `fastapi`, which the tests use to import and
check the generated starter project.

## Usage

A sample legacy shop (PHP, jQuery, MySQL dump) lives in
`tests/fixtures/legacy_shop`. Try the commands on it:

```bash
# Structure model as JSON
stackbooster analyze tests/fixtures/legacy_shop -o sitemap.json
stackbooster analyze tests/fixtures/legacy_shop --summary

# Migration plan as Markdown or a self-contained HTML page
stackbooster report tests/fixtures/legacy_shop -o MIGRATION_PLAN.md
stackbooster report tests/fixtures/legacy_shop -f html -o plan.html

# Same, from a saved map (no re-scan)
stackbooster report sitemap.json -o MIGRATION_PLAN.md

# Plan as JSON, for other tools
stackbooster plan tests/fixtures/legacy_shop

# Mermaid diagram of pages -> routes -> tables
stackbooster graph tests/fixtures/legacy_shop

# Generate a starter FastAPI + React project from the plan
stackbooster scaffold tests/fixtures/legacy_shop -o ./rebuilt

# Local dashboard on http://127.0.0.1:8765 (re-scans on every reload)
stackbooster serve tests/fixtures/legacy_shop

# Available target stacks
stackbooster targets
```

Useful options: `--exclude/-x PATTERN` skips more folders or files (vendor,
node_modules, uploads and similar are skipped by default), `--no-infer` turns
off foreign keys guessed from column names, `--target/-t` picks the target
stack.

You can also run it without installing: `PYTHONPATH=src python -m stackbooster ...`.

### What the scaffold contains

```
rebuilt/
  MIGRATION_PLAN.md
  backend/
    requirements.txt
    app/
      main.py            # FastAPI app, includes every router
      database.py        # engine, session, Base, get_db()
      models.py          # one model per legacy table, with relationships
      schemas.py         # Pydantic bodies for former POST handlers
      routers/<file>.py  # one module per legacy PHP file, endpoints stubbed
      services/<file>.py # legacy helper libraries
  frontend/src/
    App.tsx              # React Router routes, one per legacy page
    api/client.ts        # one function per endpoint
    components/*.tsx     # layout pieces from included partials
    pages/*.tsx          # one page per legacy page
```

Endpoint bodies raise `NotImplementedError` and carry the legacy queries as
ORM hints in comments. The point is to keep the structure and naming one to
one with the old site so the port can be done file by file.

## Project layout

```
src/stackbooster/
  model.py            # SiteMap and friends: the structure model, JSON (de)serialization
  scanner.py          # walks the project, runs analyzers, post-processes
  linker.py           # resolves form/AJAX/link URLs to routes and pages
  naming.py           # snake/Pascal/kebab, singular/plural
  analyzers/
    base.py           # Analyzer interface
    php.py            # backend routes from PHP
    html.py           # pages, forms, inline scripts
    javascript.py     # AJAX call extraction
    sql_schema.py     # CREATE/ALTER TABLE, inferred relations
    sqlrefs.py        # tables touched by embedded SQL
    textutil.py       # comment stripping, PHP masking, bracket matching
  planner.py          # MigrationPlan: phases, effort, risks
  targets/
    base.py           # TargetStack interface
    fastapi_react.py  # default target and its scaffold generator
    templates/        # Jinja templates for generated code
  report/             # Markdown / HTML report and Mermaid graph
  web/server.py       # stdlib http.server dashboard
  cli.py
tests/
  fixtures/legacy_shop/  # sample legacy site
```

## Tests

```bash
pytest
```

## Adding a legacy stack

Subclass `stackbooster.analyzers.base.Analyzer`, set `name` and `extensions`,
implement `analyze(ctx, site)` to append routes, pages or tables to the
`SiteMap`, and add the class to `ANALYZERS` in `stackbooster/analyzers/__init__.py`.

## Adding a target stack

Subclass `stackbooster.targets.base.TargetStack`, implement `map_table`,
`map_route` and `map_page` (each returns a `TargetMapping`), optionally
`scaffold`, and register it in `TARGETS` in `stackbooster/targets/__init__.py`.

## Known limits

- Analysis is pattern based. Calls across files are not followed: a query in a
  helper function is reported on the file that defines it, not on its callers.
- URLs built at runtime keep only their literal prefix (`'api.php?action=' + x`).
- Pretty URLs from `.htaccess` rewrite rules are not read; extensionless links
  are matched to `name.php`, `name/index.php` or `name.html`.
- Front controllers are recognised when they `switch` on a parameter named
  `action`, `act`, `op`, `do`, `task`, `cmd`, `page` or `route`.
- The SQL reader targets MySQL dialect dumps.
- Type guesses for request parameters come from names and HTML input types.

## Roadmap

- More legacy backends: classic ASP / VBScript, JSP and servlets, Perl CGI,
  ColdFusion, and PHP frameworks (CodeIgniter, Laravel 4/5 route files).
- Frontend: AngularJS 1.x and Backbone templates, server-side template engines
  (Smarty, Twig) beyond plain includes.
- Databases: PostgreSQL and SQL Server dumps, stored procedures and views.
- More targets: Django + React, FastAPI + Vue, Node/NestJS.
- Follow helper calls across files so routes get the queries of the functions
  they call.
- Diff two scans to track migration progress (legacy vs rebuilt).
