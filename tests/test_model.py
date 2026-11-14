import json

import pytest

from stackbooster.model import SiteMap


def test_json_round_trip(shop_site, tmp_path):
    path = tmp_path / "site.json"
    shop_site.save(path)
    loaded = SiteMap.load(path)
    assert loaded.to_dict() == shop_site.to_dict()
    assert loaded.route("/api.php?action=search").action == "search"


def test_summary_counts(shop_site):
    s = shop_site.summary()
    assert s["routes"] == len(shop_site.routes) == 15
    assert s["pages"] == 8
    assert s["tables"] == 8
    assert s["unresolved_links"] == 2
    assert s["files_by_kind"]["php"] == 8


def test_unused_and_unknown_tables(shop_site):
    assert shop_site.unused_tables() == ["newsletter_signups"]
    assert shop_site.unknown_tables() == []


def test_schema_version_is_checked(shop_site):
    data = json.loads(shop_site.to_json())
    data["schema_version"] = 999
    with pytest.raises(ValueError, match="schema_version"):
        SiteMap.from_dict(data)
