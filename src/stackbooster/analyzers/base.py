"""Analyzer interface and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from stackbooster.model import SiteMap


@dataclass
class FileContext:
    """One source file handed to an analyzer."""

    path: Path  # absolute path on disk
    rel_path: str  # path relative to the project root, with forward slashes
    text: str


class Analyzer(ABC):
    """Reads one kind of legacy source file and records what it finds in a SiteMap.

    To support a new legacy stack, subclass this, set ``name`` and
    ``extensions``, and register the class in :data:`stackbooster.analyzers.ANALYZERS`.
    """

    name: str = "base"
    extensions: tuple[str, ...] = ()

    def accepts(self, rel_path: str) -> bool:
        return rel_path.lower().endswith(self.extensions)

    @abstractmethod
    def analyze(self, ctx: FileContext, site: SiteMap) -> None:
        """Add routes, pages, tables or warnings for ``ctx`` to ``site``."""
