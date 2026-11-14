"""Legacy source analyzers.

Each analyzer reads one kind of file as text. The order matters only for the
``files`` kind label: the first analyzer that accepts a file names its kind.
"""

from stackbooster.analyzers.base import Analyzer, FileContext
from stackbooster.analyzers.html import HtmlAnalyzer
from stackbooster.analyzers.javascript import JavaScriptAnalyzer
from stackbooster.analyzers.php import PhpAnalyzer
from stackbooster.analyzers.sql_schema import SqlSchemaAnalyzer

ANALYZERS: list[type[Analyzer]] = [PhpAnalyzer, HtmlAnalyzer, JavaScriptAnalyzer, SqlSchemaAnalyzer]

__all__ = [
    "ANALYZERS",
    "Analyzer",
    "FileContext",
    "HtmlAnalyzer",
    "JavaScriptAnalyzer",
    "PhpAnalyzer",
    "SqlSchemaAnalyzer",
]
