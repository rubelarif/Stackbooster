from stackbooster.scanner import scan


def routes_by_id(site):
    return {r.id: r for r in site.routes}


def test_plain_page_route(shop_site):
    r = routes_by_id(shop_site)["/products.php"]
    assert r.methods == ["GET"]
    assert [p.name for p in r.params] == ["category", "page", "q"]
    assert all(p.source == "query" for p in r.params)
    assert set(r.tables) == {"products", "categories"}
    assert "html" in r.responses
    listing = r.queries[0]
    assert "LEFT JOIN categories" in listing.snippet  # literals joined with "." are one query
    assert listing.interpolated  # extended later with $sql .= "... " . $category

def test_post_handler_with_redirect(shop_site):
    r = routes_by_id(shop_site)["/checkout.php"]
    assert r.methods == ["POST"]
    assert {p.name for p in r.params} == {"full_name", "email", "address", "coupon"}
    assert r.responses == ["redirect"]
    assert r.uses_session
    kinds = [q.kind for q in r.queries]
    assert kinds == ["INSERT", "INSERT", "DELETE"]


def test_page_that_also_handles_post_keeps_get(shop_site):
    r = routes_by_id(shop_site)["/login.php"]
    assert r.methods == ["GET", "POST"]
    assert "md5/sha1 password hashing" in r.flags


def test_prepared_statement_is_parameterized(shop_site):
    r = routes_by_id(shop_site)["/product.php"]
    first, second = r.queries
    assert first.parameterized and not first.interpolated
    assert second.interpolated  # "... product_id = $id"
    assert set(second.tables) == {"reviews", "users"}  # comma join


def test_front_controller_actions(shop_site):
    routes = routes_by_id(shop_site)
    actions = {r.action for r in shop_site.routes if r.path == "/api.php"}
    assert actions == {"add_to_cart", "remove_from_cart", "cart_count", "search", "autocomplete"}
    add = routes["/api.php?action=add_to_cart"]
    assert add.methods == ["POST"]
    assert add.action_param == "action"
    assert add.responses == ["json"]
    assert {p.name for p in add.params} == {"product_id", "quantity"}
    # The ON DUPLICATE KEY UPDATE clause must not be read as a table name.
    assert add.tables == ["cart_items"]


def test_fallthrough_case_shares_body(shop_site):
    routes = routes_by_id(shop_site)
    search = routes["/api.php?action=search"]
    auto = routes["/api.php?action=autocomplete"]
    assert search.tables == auto.tables == ["products"]
    assert [p.name for p in search.params] == ["q"]


def test_library_and_partials(shop_site):
    routes = routes_by_id(shop_site)
    assert shop_site.files["includes/db.php"] == "php-library"
    assert routes["/includes/db.php"].responses == ["library"]
    assert routes["/includes/db.php"].functions == ["db_all", "cart_total"]
    assert shop_site.files["includes/header.php"] == "partial"
    assert routes["/includes/header.php"].responses == ["partial"]


def test_includes_resolve_relative_to_file(shop_site):
    r = routes_by_id(shop_site)["/admin/orders.php"]
    assert r.includes == ["includes/db.php"]
    assert r.methods == ["GET", "POST"]


def test_commented_out_code_is_ignored(make_project):
    root = make_project(
        {
            "a.php": "<?php\n// $x = $_GET['old'];\n/* mysql_query(\"SELECT * FROM gone\"); */\n"
            "$y = $_POST['new'];\n"
        }
    )
    (route,) = scan(root).routes
    assert [p.name for p in route.params] == ["new"]
    assert route.queries == []
    assert route.flags == []


def test_switch_on_get_directly(make_project):
    root = make_project(
        {
            "ajax.php": "<?php\nswitch ($_GET['op']) {\n case 'list': echo json_encode(1); break;\n"
            " case 'save': $n = $_POST['name']; break;\n}\n"
        }
    )
    site = scan(root)
    assert sorted(r.id for r in site.routes) == ["/ajax.php?action=list", "/ajax.php?action=save"]
    save = site.route("/ajax.php?action=save")
    assert save.action_param == "op"
    assert save.methods == ["POST"]


def test_legacy_mysql_extension_is_flagged(make_project):
    root = make_project({"old.php": "<?php\n$r = mysql_query(\"SELECT * FROM t WHERE id=\" . $_GET['id']);\n"})
    (route,) = scan(root).routes
    assert "mysql_* functions (removed in PHP 7)" in route.flags
    assert route.queries[0].interpolated
