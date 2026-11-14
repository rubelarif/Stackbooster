from stackbooster.planner import build_plan, table_order


def items(plan, kind):
    return {i.legacy_id: i for i in plan.items if i.kind == kind}


def test_every_legacy_piece_is_planned(shop_site, shop_plan):
    models = items(shop_plan, "model")
    assert set(models) == {t.name for t in shop_site.tables}
    pages = {i.legacy_id for i in shop_plan.items if i.kind in ("page", "layout")}
    assert pages == {p.id for p in shop_site.pages}
    endpoints = " ".join(i.legacy_id for i in shop_plan.items if i.kind in ("endpoint", "service"))
    for r in shop_site.routes:
        if r.responses != ["partial"]:
            assert r.id in endpoints


def test_parents_come_before_children(shop_site):
    order = [t.name for t in table_order(shop_site.tables)]
    assert order.index("categories") < order.index("products")
    assert order.index("orders") < order.index("order_items")
    assert order.index("users") < order.index("reviews")


def test_table_order_survives_cycles(make_project):
    from stackbooster.scanner import scan

    root = make_project(
        {
            "s.sql": "CREATE TABLE a (id int PRIMARY KEY, b_id int, FOREIGN KEY (b_id) REFERENCES b(id));\n"
            "CREATE TABLE b (id int PRIMARY KEY, a_id int, FOREIGN KEY (a_id) REFERENCES a(id));"
        }
    )
    assert sorted(t.name for t in table_order(scan(root).tables)) == ["a", "b"]


def test_front_controller_grouped_into_one_router(shop_plan):
    routers = [i for i in shop_plan.items if i.kind == "endpoint" and i.target_file.endswith("/api.py")]
    assert len(routers) == 1
    paths = [e["path"] for e in routers[0].details["endpoints"]]
    assert sorted(paths) == ["/api/add-to-cart", "/api/autocomplete", "/api/cart-count", "/api/remove-from-cart", "/api/search"]


def test_phases_are_ordered(shop_plan):
    phases = [i.phase for i in shop_plan.items]
    assert phases == sorted(phases, key=["database", "backend", "frontend"].index)
    assert [key for key, *_ in shop_plan.by_phase()] == ["database", "backend", "frontend"]


def test_risks(shop_plan):
    by_cat = {}
    for r in shop_plan.risks:
        by_cat.setdefault(r.category, []).append(r)
    injection = {r.where for r in by_cat["sql-injection"]}
    assert "/checkout.php" in injection
    assert any("md5" in r.message for r in by_cat["legacy-api"])
    assert {r.where for r in by_cat["broken-link"]} == {"/contact.html", "/includes/header.php"}
    # One session risk per legacy file, not per front-controller action.
    assert sum(1 for r in by_cat["session"] if r.where == "/api.php") == 1
    assert [r.severity for r in shop_plan.risks] == sorted(
        (r.severity for r in shop_plan.risks), key=["high", "medium", "low"].index
    )


def test_products_concatenated_sql_is_flagged(shop_plan):
    # products.php builds SQL with "... '" . $category . "'" concatenation.
    assert any(r.where == "/products.php" and r.category == "sql-injection" for r in shop_plan.risks)


def test_effort_totals(shop_plan):
    totals = shop_plan.effort_totals()
    assert sum(totals.values()) == len(shop_plan.items)


def test_unknown_target_rejected(shop_site):
    import pytest

    with pytest.raises(ValueError, match="unknown target"):
        build_plan(shop_site, "cobol-on-cogs")
