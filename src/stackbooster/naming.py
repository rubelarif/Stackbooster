"""Name conversions used when mapping legacy names onto a new stack."""

from __future__ import annotations

import keyword
import re

_IRREGULAR = {"people": "person", "children": "child", "statuses": "status", "addresses": "address"}


def words(name: str) -> list[str]:
    """Split ``order_items``, ``OrderItems``, ``order-items.php`` into ``["order", "items"]``."""
    name = re.sub(r"\.\w+$", "", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", name) if w]


def snake(name: str) -> str:
    out = "_".join(words(name)) or "item"
    if out[0].isdigit():
        out = "_" + out
    return out + "_" if keyword.iskeyword(out) else out


def pascal(name: str) -> str:
    out = "".join(w.capitalize() for w in words(name)) or "Item"
    return "_" + out if out[0].isdigit() else out


def kebab(name: str) -> str:
    return "-".join(words(name))


def singular(word: str) -> str:
    lowered = word.lower()
    if lowered in _IRREGULAR:
        return _IRREGULAR[lowered]
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith(("sses", "xes", "ches", "shes", "zes")):
        return lowered[:-2]
    if lowered.endswith("s") and not lowered.endswith(("ss", "us", "is")):
        return lowered[:-1]
    return lowered


def plural(word: str) -> str:
    lowered = word.lower()
    if lowered.endswith("s"):
        return lowered
    if lowered.endswith("y") and lowered[-2:-1] not in "aeiou":
        return lowered[:-1] + "ies"
    if lowered.endswith(("x", "ch", "sh")):
        return lowered + "es"
    return lowered + "s"


def model_class_name(table_name: str) -> str:
    """``order_items`` -> ``OrderItem``."""
    parts = words(table_name)
    if not parts:
        return "Item"
    parts[-1] = singular(parts[-1])
    return pascal("_".join(parts))
