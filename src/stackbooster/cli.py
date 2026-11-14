"""Command line interface.

    stackbooster analyze ./legacy-site -o sitemap.json
    stackbooster report  ./legacy-site -f html -o plan.html
    stackbooster scaffold ./legacy-site -o ./rebuilt
    stackbooster serve   ./legacy-site

Every command that takes SOURCE accepts either a legacy project folder (it is
scanned) or a sitemap JSON file saved earlier by ``stackbooster analyze``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from stackbooster import __version__
from stackbooster.model import SiteMap
from stackbooster.planner import build_plan
from stackbooster.report import mermaid_diagram, render_html, render_markdown
from stackbooster.scanner import DEFAULT_EXCLUDES, scan
from stackbooster.targets import DEFAULT_TARGET, TARGETS, get_target

source_arg = click.argument("source", type=click.Path(exists=True, path_type=Path))
target_opt = click.option(
    "--target", "-t", type=click.Choice(sorted(TARGETS)), default=DEFAULT_TARGET, show_default=True,
    help="Target stack to map onto.",
)
exclude_opt = click.option(
    "--exclude", "-x", multiple=True, metavar="PATTERN",
    help="Extra file or folder name pattern to skip (repeatable).",
)
no_infer_opt = click.option(
    "--no-infer", is_flag=True, help="Do not guess foreign keys from column names.",
)


def load_site(source: Path, exclude: tuple[str, ...] = (), no_infer: bool = False) -> SiteMap:
    if source.is_file():
        if source.suffix.lower() != ".json":
            raise click.BadParameter("SOURCE must be a folder or a sitemap .json file", param_hint="SOURCE")
        try:
            return SiteMap.load(source)
        except (ValueError, KeyError, TypeError) as exc:
            raise click.ClickException(f"could not read {source}: {exc}") from exc
    return scan(source, excludes=DEFAULT_EXCLUDES + tuple(exclude), infer=not no_infer)


def _write(text: str, output: Path | None) -> None:
    if output is None:
        click.echo(text, nl=not text.endswith("\n"))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    click.echo(f"wrote {output}", err=True)


@click.group()
@click.version_option(__version__, prog_name="stackbooster")
def main() -> None:
    """Map a legacy website's structure and plan its rebuild on a modern stack."""


@main.command()
@source_arg
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path), help="Write JSON here.")
@click.option("--summary", "summary_only", is_flag=True, help="Print only the summary counts.")
@exclude_opt
@no_infer_opt
def analyze(source: Path, output: Path | None, summary_only: bool, exclude, no_infer: bool) -> None:
    """Scan SOURCE and print (or save) the structure model as JSON."""
    site = load_site(source, exclude, no_infer)
    if summary_only:
        _write(json.dumps(site.summary(), indent=2) + "\n", output)
        return
    _write(site.to_json() + "\n", output)
    if output is not None:
        s = site.summary()
        click.echo(
            f"{s['routes']} routes, {s['pages']} pages, {s['tables']} tables, "
            f"{s['links']} links ({s['unresolved_links']} unresolved), {s['warnings']} warnings",
            err=True,
        )


@main.command()
@source_arg
@target_opt
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path))
@exclude_opt
@no_infer_opt
def plan(source: Path, target: str, output: Path | None, exclude, no_infer: bool) -> None:
    """Print the migration plan as JSON."""
    site = load_site(source, exclude, no_infer)
    _write(json.dumps(build_plan(site, target).to_dict(), indent=2) + "\n", output)


@main.command()
@source_arg
@target_opt
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "html"]), default="md", show_default=True)
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path))
@exclude_opt
@no_infer_opt
def report(source: Path, target: str, fmt: str, output: Path | None, exclude, no_infer: bool) -> None:
    """Render the migration plan as a Markdown or HTML report."""
    site = load_site(source, exclude, no_infer)
    migration = build_plan(site, target)
    text = render_html(site, migration) if fmt == "html" else render_markdown(site, migration)
    _write(text, output)


@main.command()
@source_arg
@click.option("--links", is_flag=True, help="Include page-to-page navigation links.")
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path))
@exclude_opt
def graph(source: Path, links: bool, output: Path | None, exclude) -> None:
    """Print a Mermaid diagram of pages, routes and tables."""
    _write(mermaid_diagram(load_site(source, exclude), include_links=links), output)


@main.command()
@source_arg
@target_opt
@click.option("--output", "-o", type=click.Path(file_okay=False, path_type=Path), required=True,
              help="Folder for the generated starter project.")
@click.option("--force", is_flag=True, help="Overwrite files that already exist.")
@exclude_opt
@no_infer_opt
def scaffold(source: Path, target: str, output: Path, force: bool, exclude, no_infer: bool) -> None:
    """Generate a starter project for the target stack."""
    site = load_site(source, exclude, no_infer)
    stack = get_target(target)
    migration = build_plan(site, stack)
    files = stack.scaffold(site, migration)
    if not files:
        raise click.ClickException(f"target {target} cannot generate code yet")
    existing = [p for p in files if (output / p).exists()]
    if existing and not force:
        raise click.ClickException(
            f"{len(existing)} file(s) already exist in {output} (first: {existing[0]}); use --force to overwrite"
        )
    for rel, content in files.items():
        path = output / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (output / "MIGRATION_PLAN.md").write_text(render_markdown(site, migration), encoding="utf-8")
    click.echo(f"wrote {len(files) + 1} files to {output}")


@main.command()
@source_arg
@target_opt
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", "-p", default=8765, show_default=True, type=int)
def serve(source: Path, target: str, host: str, port: int) -> None:
    """Run the local dashboard. It re-scans SOURCE on every page load."""
    from stackbooster.web import serve as run

    if not source.is_dir():
        raise click.BadParameter("serve needs a project folder", param_hint="SOURCE")
    run(source, target, host, port)


@main.command()
def targets() -> None:
    """List the available target stacks."""
    for key in sorted(TARGETS):
        info = TARGETS[key]().describe()
        click.echo(f"{key:16} {info['label']}  (backend: {info['backend']}; frontend: {info['frontend']})")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
