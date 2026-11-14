import importlib
import sys

import pytest

from stackbooster.model import Column, FormField
from stackbooster.targets import get_target
from stackbooster.targets.fastapi_react import guess_param_type, sqlalchemy_type


@pytest.mark.parametrize(
    ("col", "expected"),
    [
        (Column("a", "INT", "11"), ("Integer", "int")),
        (Column("a", "TINYINT", "1"), ("Boolean", "bool")),
        (Column("a", "TINYINT", "4"), ("SmallInteger", "int")),
        (Column("a", "DECIMAL", "10,2"), ("Numeric(10, 2)", "Decimal")),
        (Column("a", "VARCHAR", "64"), ("String(64)", "str")),
        (Column("a", "LONGTEXT"), ("Text", "str")),
        (Column("a", "DATETIME"), ("DateTime", "datetime")),
        (Column("a", "BLOB"), ("LargeBinary", "bytes")),
        (Column("a", "GEOMETRY"), ("String", "str")),
    ],
)
def test_sqlalchemy_type(col, expected):
    assert sqlalchemy_type(col) == expected


def test_enum_type():
    sa, py = sqlalchemy_type(Column("role", "ENUM", enum_values=["a", "b"]), "users")
    assert sa == "Enum('a', 'b', name=\"users_role\")" and py == "str"


def test_guess_param_type():
    assert guess_param_type("product_id") == "int"
    assert guess_param_type("is_active") == "bool"
    assert guess_param_type("age", FormField("age", "number")) == "int"
    assert guess_param_type("email", FormField("email", "email")) == "str"


def test_endpoint_paths(shop_site):
    target = get_target()
    assert target.api_path(shop_site.route("/index.php")) == "/api/home"
    assert target.api_path(shop_site.route("/admin/orders.php")) == "/api/admin/orders"
    assert target.api_path(shop_site.route("/api.php?action=add_to_cart")) == "/api/add-to-cart"


def test_form_types_flow_into_request_model(shop_site):
    mapping = get_target().map_route(shop_site.route("/checkout.php"), shop_site)
    (endpoint,) = mapping.details["endpoints"]
    assert endpoint["body_model"] == "CheckoutPostRequest"
    required = {p["name"]: p["required"] for p in endpoint["params"]}
    assert required == {"full_name": True, "email": True, "address": True, "coupon": False}


def test_model_relationships_are_symmetric(shop_site, shop_plan):
    models = {i.target_name: i for i in shop_plan.items if i.kind == "model"}
    for name, item in models.items():
        for rel in item.details["relationships"]:
            other = models[rel["target"]]
            back = [r for r in other.details["relationships"] if r["attr"] == rel["back_populates"]]
            assert back, f"{name}.{rel['attr']} has no partner {rel['target']}.{rel['back_populates']}"
            assert back[0]["back_populates"] == rel["attr"]


def test_page_mapping(shop_site):
    target = get_target()
    product = target.map_page(shop_site.page("/product.php"), shop_site)
    assert product.name == "ProductPage"
    assert product.details["route_path"] == "/product/:id"
    assert product.details["api_calls"][0]["endpoint"] == "POST /api/add-to-cart"
    header = target.map_page(shop_site.page("/includes/header.php"), shop_site)
    assert (header.kind, header.name) == ("layout", "Header")
    home = target.map_page(shop_site.page("/index.php"), shop_site)
    assert (home.name, home.details["route_path"], home.details["data_endpoint"]) == ("HomePage", "/", "GET /api/home")


@pytest.fixture
def scaffold_files(shop_site, shop_plan):
    return get_target().scaffold(shop_site, shop_plan)


def test_scaffold_file_set(scaffold_files):
    assert "backend/app/models.py" in scaffold_files
    assert "backend/app/routers/api.py" in scaffold_files
    assert "frontend/src/pages/ProductPage.tsx" in scaffold_files
    assert "frontend/src/components/Header.tsx" in scaffold_files
    for path, content in scaffold_files.items():
        if path.endswith(".py"):
            compile(content, path, "exec")


def test_generated_backend_imports_and_creates_tables(scaffold_files, tmp_path, monkeypatch):
    sqlalchemy = pytest.importorskip("sqlalchemy")
    pytest.importorskip("fastapi")
    for rel, content in scaffold_files.items():
        if rel.startswith("backend/"):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.syspath_prepend(str(tmp_path / "backend"))
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        monkeypatch.delitem(sys.modules, name)

    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    sqlalchemy.orm.configure_mappers()  # fails if any relationship is inconsistent
    database.Base.metadata.create_all(database.engine)
    tables = set(sqlalchemy.inspect(database.engine).get_table_names())
    assert {"products", "order_items", "newsletter_signups"} <= tables
    assert "category" in models.Product.__mapper__.relationships

    main = importlib.import_module("app.main")
    # The OpenAPI schema is the stable way to list routes across FastAPI versions.
    paths = main.app.openapi()["paths"]
    assert "post" in paths["/api/checkout"]
    assert "get" in paths["/api/cart-count"]
    assert "post" in paths["/api/admin/orders"] and "get" in paths["/api/admin/orders"]
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        monkeypatch.delitem(sys.modules, name)
