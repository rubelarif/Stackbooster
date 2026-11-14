"""Database analyzer for MySQL / MariaDB schema dumps.

Reads ``CREATE TABLE`` statements as produced by ``mysqldump`` and phpMyAdmin,
including the phpMyAdmin style where keys and constraints are added later with
``ALTER TABLE ... ADD PRIMARY KEY / ADD KEY / ADD CONSTRAINT``.

Many legacy databases use MyISAM and declare no foreign keys at all. After all
files are read, :func:`infer_relations` adds guessed relations from column
names such as ``customer_id`` and marks them ``inferred=True``.
"""

from __future__ import annotations

import re

from stackbooster.analyzers.base import Analyzer, FileContext
from stackbooster.analyzers.textutil import find_matching, split_top_level
from stackbooster.model import Column, ForeignKey, Index, SiteMap, Table
from stackbooster.naming import singular

_NAME = r"`?\"?([A-Za-z_][\w$]*)`?\"?"
CREATE_RE = re.compile(
    r"CREATE\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:" + _NAME + r"\s*\.\s*)?" + _NAME + r"\s*\(",
    re.I,
)
ALTER_RE = re.compile(r"ALTER\s+TABLE\s+(?:ONLY\s+)?" + _NAME + r"\s+(.*?);", re.I | re.S)
ENGINE_RE = re.compile(r"ENGINE\s*=\s*(\w+)", re.I)

COLUMN_RE = re.compile(
    r"^" + _NAME + r"\s+([A-Za-z]+(?:\s+(?:PRECISION|VARYING))?)\s*(?:\(([^)]*)\))?(.*)$",
    re.I | re.S,
)
FK_RE = re.compile(
    r"(?:CONSTRAINT\s+" + _NAME + r"\s+)?FOREIGN\s+KEY\s*(?:" + _NAME + r"\s*)?\(([^)]*)\)\s*"
    r"REFERENCES\s+" + _NAME + r"\s*\(([^)]*)\)(.*)",
    re.I | re.S,
)
PK_RE = re.compile(r"^(?:CONSTRAINT\s+\S+\s+)?PRIMARY\s+KEY\s*(?:\w+\s*)?\(([^)]*)\)", re.I)
KEY_RE = re.compile(r"^(UNIQUE\s+)?(?:KEY|INDEX)\s*(?:" + _NAME + r")?\s*(?:USING\s+\w+\s*)?\(([^)]*)\)", re.I)
UNIQUE_RE = re.compile(r"^(?:CONSTRAINT\s+" + _NAME + r"\s+)?UNIQUE\s*\(([^)]*)\)", re.I)
INLINE_REF_RE = re.compile(r"REFERENCES\s+" + _NAME + r"\s*\(([^)]*)\)", re.I)
DEFAULT_RE = re.compile(r"\bDEFAULT\s+('(?:[^']|'')*'|\"[^\"]*\"|\S+)", re.I)
ON_ACTION_RE = re.compile(r"ON\s+(DELETE|UPDATE)\s+(CASCADE|RESTRICT|SET\s+NULL|NO\s+ACTION|SET\s+DEFAULT)", re.I)

_SKIP_PREFIXES = ("FULLTEXT", "SPATIAL", "CHECK", "PERIOD")


def _names(text: str) -> list[str]:
    # "`a`(10), `b`" -> ["a", "b"]  (index prefix lengths are dropped)
    out = []
    for part in text.split(","):
        part = re.sub(r"\(\d+\)", "", part).strip().strip('`"')
        part = re.sub(r"\s+(ASC|DESC)$", "", part, flags=re.I).strip('`"')
        if part:
            out.append(part)
    return out


def _strip_sql_comments(text: str) -> str:
    text = re.sub(r"/\*(?!!).*?\*/", " ", text, flags=re.S)
    text = re.sub(r"/\*!\d*\s*(.*?)\*/", r"\1", text, flags=re.S)  # MySQL versioned comments
    return re.sub(r"(?m)(--\s|#).*$", "", text)


def _fk_actions(tail: str) -> tuple[str | None, str | None]:
    on_delete = on_update = None
    for m in ON_ACTION_RE.finditer(tail):
        action = " ".join(m.group(2).upper().split())
        if m.group(1).upper() == "DELETE":
            on_delete = action
        else:
            on_update = action
    return on_delete, on_update


def parse_column(item: str) -> tuple[Column, ForeignKey | None] | None:
    m = COLUMN_RE.match(item.strip())
    if not m:
        return None
    name, ctype, args, rest = m.group(1), m.group(2).upper(), m.group(3), m.group(4) or ""
    upper = rest.upper()
    col = Column(name=name, type=ctype)
    if args is not None:
        if ctype in ("ENUM", "SET"):
            col.enum_values = [v.strip().strip("'\"") for v in split_top_level(args)]
        else:
            col.length = args.replace(" ", "")
    col.unsigned = "UNSIGNED" in upper
    col.auto_increment = "AUTO_INCREMENT" in upper or "AUTOINCREMENT" in upper or ctype in ("SERIAL", "BIGSERIAL")
    col.primary_key = "PRIMARY KEY" in upper
    col.unique = bool(re.search(r"\bUNIQUE\b", upper))
    col.nullable = "NOT NULL" not in upper and not col.primary_key
    dm = DEFAULT_RE.search(rest)
    if dm:
        value = dm.group(1)
        if value.upper() == "NULL":
            col.default = None
        else:
            col.default = value.strip("'\"")
    fk = None
    ref = INLINE_REF_RE.search(rest)
    if ref:
        on_delete, on_update = _fk_actions(rest[ref.end() :])
        fk = ForeignKey([name], ref.group(1), _names(ref.group(2)), on_delete, on_update)
    return col, fk


def parse_create_body(table: Table, body: str) -> None:
    for item in split_top_level(body):
        head = item.lstrip().upper()
        if head.startswith(_SKIP_PREFIXES):
            continue
        if m := PK_RE.match(item):
            table.primary_key = _names(m.group(1))
            continue
        if "FOREIGN KEY" in head and (m := FK_RE.match(item.strip())):
            on_delete, on_update = _fk_actions(m.group(6))
            table.foreign_keys.append(
                ForeignKey(_names(m.group(3)), m.group(4), _names(m.group(5)), on_delete, on_update, m.group(1))
            )
            continue
        if m := KEY_RE.match(item.strip()):
            cols = _names(m.group(3))
            table.indexes.append(Index(name=m.group(2) or "_".join(cols), columns=cols, unique=bool(m.group(1))))
            continue
        if m := UNIQUE_RE.match(item.strip()):
            cols = _names(m.group(2))
            table.indexes.append(Index(name=m.group(1) or "_".join(cols), columns=cols, unique=True))
            continue
        parsed = parse_column(item)
        if parsed:
            col, fk = parsed
            table.columns.append(col)
            if fk:
                table.foreign_keys.append(fk)

    if not table.primary_key:
        table.primary_key = [c.name for c in table.columns if c.primary_key]
    for col in table.columns:
        if col.name in table.primary_key:
            col.primary_key = True
            col.nullable = False


def apply_alter(table: Table, clause_text: str) -> None:
    """Apply the ADD / MODIFY clauses of an ALTER TABLE statement."""
    for clause in split_top_level(clause_text):
        text = clause.strip()
        upper = text.upper()
        if upper.startswith("ADD PRIMARY KEY") or (upper.startswith("ADD CONSTRAINT") and "PRIMARY KEY" in upper):
            pk = re.search(r"PRIMARY\s+KEY\s*\(([^)]*)\)", text, re.I)
            if pk:
                table.primary_key = _names(pk.group(1))
                for col in table.columns:
                    if col.name in table.primary_key:
                        col.primary_key, col.nullable = True, False
        elif "FOREIGN KEY" in upper:
            m = FK_RE.search(text)
            if m:
                on_delete, on_update = _fk_actions(m.group(6))
                table.foreign_keys.append(
                    ForeignKey(_names(m.group(3)), m.group(4), _names(m.group(5)), on_delete, on_update, m.group(1))
                )
        elif upper.startswith(("ADD KEY", "ADD INDEX", "ADD UNIQUE")):
            m = re.match(r"ADD\s+(UNIQUE\s+)?(?:KEY|INDEX)?\s*(?:" + _NAME + r")?\s*\(([^)]*)\)", text, re.I)
            if m:
                cols = _names(m.group(3))
                table.indexes.append(Index(m.group(2) or "_".join(cols), cols, unique=bool(m.group(1))))
        elif upper.startswith("MODIFY") or upper.startswith("CHANGE"):
            # MODIFY col def...   |   CHANGE old_name new_name def...
            skip_old = r"\S+\s+" if upper.startswith("CHANGE") else ""
            m = re.match(r"(?:MODIFY|CHANGE)\s+(?:COLUMN\s+)?" + skip_old + r"(.*)", text, re.I | re.S)
            parsed = parse_column(m.group(1)) if m else None
            if parsed:
                new_col = parsed[0]
                for i, col in enumerate(table.columns):
                    if col.name == new_col.name:
                        new_col.primary_key = new_col.primary_key or col.primary_key
                        if new_col.primary_key:
                            new_col.nullable = False
                        table.columns[i] = new_col
        elif upper.startswith("ADD") and not upper.startswith("ADD FULLTEXT"):
            parsed = parse_column(re.sub(r"^ADD\s+(?:COLUMN\s+)?", "", text, flags=re.I))
            if parsed:
                table.columns.append(parsed[0])
                if parsed[1]:
                    table.foreign_keys.append(parsed[1])


class SqlSchemaAnalyzer(Analyzer):
    name = "sql-schema"
    extensions = (".sql",)

    def analyze(self, ctx: FileContext, site: SiteMap) -> None:
        text = _strip_sql_comments(ctx.text)
        found = 0
        for m in CREATE_RE.finditer(text):
            open_pos = m.end() - 1
            close = find_matching(text, open_pos)
            if close == -1:
                site.warnings.append(f"{ctx.rel_path}: unterminated CREATE TABLE {m.group(2)}")
                continue
            name = m.group(2)
            table = Table(name=name, file=ctx.rel_path)
            parse_create_body(table, text[open_pos + 1 : close])
            tail = text[close : text.find(";", close) if ";" in text[close:] else len(text)]
            if em := ENGINE_RE.search(tail):
                table.engine = em.group(1)
            existing = site.table(name)
            if existing:
                site.warnings.append(f"{ctx.rel_path}: table {name} defined again (first in {existing.file})")
                continue
            site.tables.append(table)
            found += 1

        for m in ALTER_RE.finditer(text):
            table = site.table(m.group(1))
            if table is None:
                site.warnings.append(f"{ctx.rel_path}: ALTER TABLE for unknown table {m.group(1)}")
                continue
            apply_alter(table, m.group(2))

        if found:
            site.files[ctx.rel_path] = "sql-schema"
        else:
            site.files[ctx.rel_path] = "sql-data"


def infer_relations(site: SiteMap) -> int:
    """Guess foreign keys from ``<thing>_id`` columns that have none declared.

    Returns the number of relations added.
    """
    by_singular: dict[str, Table] = {}
    for t in site.tables:
        by_singular.setdefault(singular(t.name), t)
        by_singular.setdefault(t.name.lower(), t)

    added = 0
    for table in site.tables:
        declared = {c.lower() for fk in table.foreign_keys for c in fk.columns}
        for col in table.columns:
            lowered = col.name.lower()
            sole_pk = col.name in table.primary_key and len(table.primary_key) == 1
            if lowered in declared or not lowered.endswith("_id") or sole_pk:
                continue
            stem = lowered[:-3]
            target = by_singular.get(stem) or by_singular.get(singular(stem))
            if target is None or not target.primary_key:
                continue
            table.foreign_keys.append(
                ForeignKey([col.name], target.name, [target.primary_key[0]], inferred=True)
            )
            added += 1
    return added
