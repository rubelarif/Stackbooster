from pathlib import Path

import pytest

from stackbooster.planner import build_plan
from stackbooster.scanner import scan

FIXTURES = Path(__file__).parent / "fixtures"
SHOP = FIXTURES / "legacy_shop"


@pytest.fixture(scope="session")
def shop_root() -> Path:
    return SHOP


@pytest.fixture(scope="session")
def shop_site():
    return scan(SHOP)


@pytest.fixture(scope="session")
def shop_plan(shop_site):
    return build_plan(shop_site)


@pytest.fixture
def make_project(tmp_path):
    """Write a small legacy project from a {relative_path: text} dict and return its root."""

    def _make(files: dict[str, str]) -> Path:
        for rel, text in files.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return tmp_path

    return _make
