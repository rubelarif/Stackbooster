"""Mermaid flowchart of pages -> routes -> tables."""

from __future__ import annotations

import re

from stackbooster.model import SiteMap


def _node_id(prefix: str, name: str) -> str:
    return prefix + "_" + re.sub(r"\W+", "_", name).strip("_")


def _label(text: str) -> str:
    return text.replace('"', "'")


def mermaid_diagram(site: SiteMap, include_links: bool = False) -> str:
    """Return a Mermaid ``flowchart LR`` showing how the legacy pieces connect.

    Page-to-page navigation links are left out unless ``include_links`` is set,
    because they usually drown out the data flow.
    """
    lines = ["flowchart LR"]
    pages = list(site.pages)
    route_ids = {r.id for r in site.routes if r.responses not in (["partial"], ["library"])}

    lines.append('  subgraph Frontend["Frontend pages"]')
    for p in pages:
        label = f"{p.id} (layout)" if p.partial else p.id
        lines.append(f'    {_node_id("P", p.id)}["{_label(label)}"]')
    lines.append("  end")
    lines.append('  subgraph Backend["Backend routes"]')
    for r in site.routes:
        if r.id in route_ids:
            lines.append(f'    {_node_id("R", r.id)}(["{_label(r.id)}"])')
    lines.append("  end")
    lines.append('  subgraph Database["Database tables"]')
    for t in site.tables:
        lines.append(f'    {_node_id("T", t.name)}[("{_label(t.name)}")]')
    lines.append("  end")

    page_ids = {p.id for p in pages}
    seen: set[str] = set()
    for link in site.links:
        if not link.resolved or link.target not in route_ids:
            continue
        if link.kind == "link" and not include_links:
            continue
        # A page's own route is the same file: the arrow would be noise.
        if link.source == link.target:
            continue
        if link.source not in page_ids:
            continue
        src = _node_id("P", link.source)
        edge = f"  {src} -->|{link.kind} {link.method}| {_node_id('R', link.target)}"
        if edge not in seen:
            seen.add(edge)
            lines.append(edge)

    for r in site.routes:
        if r.id not in route_ids:
            continue
        for q in r.queries:
            for t in q.tables:
                if site.table(t) is None:
                    continue
                edge = f"  {_node_id('R', r.id)} -.->|{q.kind}| {_node_id('T', site.table(t).name)}"
                if edge not in seen:
                    seen.add(edge)
                    lines.append(edge)

    for t in site.tables:
        for fk in t.foreign_keys:
            if site.table(fk.ref_table):
                style = "-.-" if fk.inferred else "---"
                edge = f"  {_node_id('T', t.name)} {style} {_node_id('T', site.table(fk.ref_table).name)}"
                if edge not in seen:
                    seen.add(edge)
                    lines.append(edge)
    return "\n".join(lines) + "\n"
