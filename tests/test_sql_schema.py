from stackbooster.analyzers.sql_schema import parse_column
from stackbooster.scanner import scan


def test_tables_found(shop_site):
    names = [t.name for t in shop_site.tables]
    assert names == [
        "categories", "products", "users", "orders", "order_items", "cart_items", "reviews", "newsletter_signups",
    ]
    assert shop_site.files["db/seed.sql"] == "sql-data"


def test_columns_and_types(shop_site):
    products = shop_site.table("products")
    price = products.column("price")
    assert (price.type, price.length, price.nullable, price.default) == ("DECIMAL", "10,2", False, "0.00")
    pid = products.column("id")
    assert pid.primary_key and pid.auto_increment and pid.unsigned
    assert products.column("description").nullable
    role = shop_site.table("users").column("role")
    assert role.enum_values == ["customer", "admin"]
    assert role.default == "customer"
    assert shop_site.table("users").column("created_at").default == "CURRENT_TIMESTAMP"


def test_keys_and_declared_foreign_keys(shop_site):
    products = shop_site.table("products")
    (fk,) = products.foreign_keys
    assert (fk.columns, fk.ref_table, fk.ref_columns, fk.on_delete, fk.inferred) == (
        ["category_id"], "categories", ["id"], "SET NULL", False,
    )
    assert any(ix.name == "idx_category" for ix in products.indexes)
    assert any(ix.unique and ix.columns == ["slug"] for ix in shop_site.table("categories").indexes)


def test_inline_primary_key_and_reference(shop_site):
    cart = shop_site.table("cart_items")
    assert cart.primary_key == ["id"]
    (fk,) = cart.foreign_keys
    assert (fk.ref_table, fk.on_delete) == ("products", "CASCADE")
    assert any(ix.columns == ["session_id", "product_id"] and ix.unique for ix in cart.indexes)


def test_phpmyadmin_alter_table(shop_site):
    items = shop_site.table("order_items")
    assert items.primary_key == ["id"]
    assert items.column("id").auto_increment  # from ALTER TABLE ... MODIFY
    declared = [fk for fk in items.foreign_keys if not fk.inferred]
    assert [(fk.columns, fk.ref_table) for fk in declared] == [(["product_id"], "products")]
    assert any(ix.name == "order_id" for ix in items.indexes)


def test_inferred_relations(shop_site):
    inferred = {
        (t.name, fk.columns[0], fk.ref_table) for t in shop_site.tables for fk in t.foreign_keys if fk.inferred
    }
    assert inferred == {
        ("orders", "user_id", "users"),
        ("order_items", "order_id", "orders"),
        ("reviews", "product_id", "products"),
        ("reviews", "user_id", "users"),
    }


def test_no_infer_option(shop_root):
    site = scan(shop_root, infer=False)
    assert not any(fk.inferred for t in site.tables for fk in t.foreign_keys)


def test_engine_and_missing_primary_key(shop_site):
    assert shop_site.table("orders").engine == "MyISAM"
    assert shop_site.table("newsletter_signups").primary_key == []
    assert "table 'newsletter_signups' has no primary key" in shop_site.warnings


def test_parse_column_variants():
    col, fk = parse_column("`owner_id` bigint(20) unsigned NOT NULL REFERENCES `owners`(`id`) ON UPDATE CASCADE")
    assert (col.type, col.unsigned, col.nullable) == ("BIGINT", True, False)
    assert (fk.ref_table, fk.on_update) == ("owners", "CASCADE")
    col, fk = parse_column("note varchar(20) DEFAULT NULL")
    assert col.default is None and col.nullable and fk is None


def test_duplicate_and_unknown_alter_warn(make_project):
    root = make_project(
        {
            "a.sql": "CREATE TABLE t (id int PRIMARY KEY);\nALTER TABLE missing ADD KEY k (x);",
            "b.sql": "CREATE TABLE t (id int PRIMARY KEY);",
        }
    )
    site = scan(root)
    assert len(site.tables) == 1
    assert any("defined again" in w for w in site.warnings)
    assert any("unknown table missing" in w for w in site.warnings)
