"""Walk a legacy project folder and build its :class:`~stackbooster.model.SiteMap`."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable
from pathlib import Path

from stackbooster.analyzers import ANALYZERS, Analyzer, FileContext
from stackbooster.analyzers.sql_schema import infer_relations
from stackbooster.linker import link_site
from stackbooster.model import SiteMap

DEFAULT_EXCLUDES = (
    ".git", ".svn", ".hg", "node_modules", "vendor", "bower_components", ".venv", "venv",
    "__pycache__", "cache", "tmp", "logs", "uploads",
)
MAX_FILE_BYTES = 2_000_000
ENCODINGS = ("utf-8", "cp1252", "latin-1")  # latin-1 never fails, so it is the last resort


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")  # pragma: no cover - latin-1 decodes anything


def iter_files(root: Path, excludes: Iterable[str] = DEFAULT_EXCLUDES) -> Iterable[Path]:
    patterns = list(excludes)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not any(fnmatch.fnmatch(d, pat) for pat in patterns)
        )
        for name in sorted(filenames):
            if any(fnmatch.fnmatch(name, pat) for pat in patterns):
                continue
            yield Path(dirpath) / name


def scan(
    root: str | Path,
    analyzers: list[Analyzer] | None = None,
    excludes: Iterable[str] = DEFAULT_EXCLUDES,
    infer: bool = True,
) -> SiteMap:
    """Analyze every supported file under ``root``.

    ``infer`` controls whether foreign keys are guessed from column names when
    the schema does not declare them.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    analyzers = analyzers if analyzers is not None else [cls() for cls in ANALYZERS]
    site = SiteMap(root=str(root))

    for path in iter_files(root, excludes):
        rel = path.relative_to(root).as_posix()
        wanted = [a for a in analyzers if a.accepts(rel)]
        if not wanted:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            site.warnings.append(f"{rel}: skipped, larger than {MAX_FILE_BYTES} bytes")
            continue
        ctx = FileContext(path=path, rel_path=rel, text=read_text(path))
        site.files.setdefault(rel, wanted[0].name)
        for analyzer in wanted:
            try:
                analyzer.analyze(ctx, site)
            except Exception as exc:  # keep going: one odd file should not stop the scan
                site.warnings.append(f"{rel}: {analyzer.name} analyzer failed: {exc!r}")

    _mark_partials(site)
    if infer:
        infer_relations(site)
    link_site(site)
    _check_consistency(site)
    return site


def _mark_partials(site: SiteMap) -> None:
    """Files pulled in with include/require are layout pieces, not standalone pages."""
    included: set[str] = set()
    for route in site.routes:
        included.update(i.lower() for i in route.includes)
    for page in site.pages:
        included.update(i.lstrip("./").lower() for i in page.includes)

    for page in site.pages:
        if page.file.lower() in included:
            page.partial = True
            site.files[page.file] = "partial"
    for route in site.routes:
        if route.file.lower() in included and not route.params and route.responses in ([], ["html"]):
            route.responses = ["partial"]
            site.files[route.file] = "partial"


def _check_consistency(site: SiteMap) -> None:
    for name in site.unknown_tables():
        site.warnings.append(f"queries use table '{name}' which is not in any schema file")
    for table in site.tables:
        if not table.primary_key:
            site.warnings.append(f"table '{table.name}' has no primary key")
    for link in site.links:
        if not link.resolved:
            site.warnings.append(f"{link.source}: {link.kind} to '{link.target}' does not match any route or page")
