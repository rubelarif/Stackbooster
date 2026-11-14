"""Find the tables a SQL statement touches.

Used on SQL embedded in backend code (PHP strings). This is a keyword-based
reader, not a SQL parser: it handles the shapes legacy code usually has
(``SELECT ... FROM a JOIN b``, ``INSERT INTO``, ``UPDATE``, ``DELETE FROM``).
"""

from __future__ import annotations

import re

from stackbooster.model import QueryRef

STATEMENT_RE = re.compile(r"^\s*\(?\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE)\b", re.I)

_IDENT = r"`?([A-Za-z_][A-Za-z0-9_]*)`?(?:\s*\.\s*`?([A-Za-z_][A-Za-z0-9_]*)`?)?"
_TABLE_AFTER = re.compile(
    r"\b(?:FROM|JOIN|INTO|(?<!KEY\s)UPDATE)\s+" + _IDENT,
    re.I,
)
# "FROM a, b" style comma joins
_COMMA_JOIN = re.compile(r"\bFROM\s+([A-Za-z0-9_`.,\s]+?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|\bJOIN\b|$)", re.I | re.S)

_SQL_WORDS = {
    "select", "where", "set", "values", "on", "as", "left", "right", "inner", "outer",
    "group", "order", "limit", "dual",
}

_PARAM_MARKERS = re.compile(r"\?|:[A-Za-z_]\w*")
_INTERPOLATION = re.compile(r"\$[A-Za-z_]|\{\$|\"\s*\.\s*\$|'\s*\.\s*\$")


def looks_like_sql(text: str) -> bool:
    return bool(STATEMENT_RE.match(text)) and bool(
        re.search(r"\b(FROM|INTO|SET|VALUES)\b", text, re.I)
        or re.match(r"^\s*UPDATE\s+\S+", text, re.I)
    )


def statement_kind(text: str) -> str:
    m = STATEMENT_RE.match(text)
    if not m:
        return "OTHER"
    kind = m.group(1).upper()
    return "INSERT" if kind == "REPLACE" else kind


def tables_in(sql: str) -> list[str]:
    found: dict[str, None] = {}

    def add(name: str | None) -> None:
        if name and name.lower() not in _SQL_WORDS:
            found.setdefault(name, None)

    for m in _TABLE_AFTER.finditer(sql):
        # "db.table" -> table
        add(m.group(2) or m.group(1))

    for m in _COMMA_JOIN.finditer(sql):
        chunk = m.group(1)
        if "," not in chunk:
            continue
        for part in chunk.split(","):
            words = part.strip().split()
            if words:
                add(words[0].strip("`").split(".")[-1])
    return list(found)


def query_ref(sql: str, line: int | None = None, context: str = "") -> QueryRef:
    """Build a :class:`QueryRef` from a SQL string.

    ``context`` is the surrounding source (for example the PHP statement the
    string sits in). It is used to tell prepared statements apart from string
    building with request variables.
    """
    compact = " ".join(sql.split())
    interpolated = bool(_INTERPOLATION.search(sql)) or bool(re.search(r"['\"]\s*\.\s*\$", context))
    parameterized = bool(_PARAM_MARKERS.search(sql)) and not interpolated
    return QueryRef(
        kind=statement_kind(sql),
        tables=tables_in(sql),
        line=line,
        snippet=compact[:160],
        parameterized=parameterized,
        interpolated=interpolated,
    )
