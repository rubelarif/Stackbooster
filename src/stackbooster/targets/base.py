"""The target-stack interface.

A target stack decides what each legacy piece becomes: a table becomes an ORM
model, a route becomes an API endpoint, a page becomes a frontend component.
The planner stays stack-agnostic and asks the target for these mappings, so
adding Django or Vue means adding one class, not changing the planner.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from stackbooster.model import Page, Route, SiteMap, Table


@dataclass
class TargetMapping:
    """What one legacy piece becomes in the target stack."""

    kind: str  # "model", "endpoint", "page", "layout"
    name: str  # class, function or component name
    file: str  # file it will live in, relative to the new project root
    summary: str  # one line, e.g. "POST /api/checkout"
    details: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class TargetStack(ABC):
    """Base class for target stacks. Register subclasses in :mod:`stackbooster.targets`."""

    key: str = "base"
    label: str = "Base"
    backend: str = ""
    frontend: str = ""
    orm: str = ""

    @abstractmethod
    def map_table(self, table: Table, site: SiteMap) -> TargetMapping: ...

    @abstractmethod
    def map_route(self, route: Route, site: SiteMap) -> TargetMapping: ...

    @abstractmethod
    def map_page(self, page: Page, site: SiteMap) -> TargetMapping: ...

    def scaffold(self, site: SiteMap, plan: Any) -> dict[str, str]:
        """Return ``{relative_path: file_content}`` for a starter project.

        Targets that cannot generate code yet return an empty dict.
        """
        return {}

    def describe(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "backend": self.backend,
            "frontend": self.frontend,
            "orm": self.orm,
        }
