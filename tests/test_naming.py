import pytest

from stackbooster.naming import kebab, model_class_name, pascal, plural, singular, snake


@pytest.mark.parametrize(
    ("table", "cls"),
    [("order_items", "OrderItem"), ("categories", "Category"), ("addresses", "Address"),
     ("status", "Status"), ("tblUsers", "TblUser"), ("people", "Person")],
)
def test_model_class_name(table, cls):
    assert model_class_name(table) == cls


def test_case_conversions():
    assert snake("OrderItems") == "order_items"
    assert snake("class") == "class_"
    assert snake("2fa") == "_2fa"
    assert pascal("add_to_cart") == "AddToCart"
    assert kebab("add_to_cart") == "add-to-cart"
    assert kebab("products.php") == "products"


def test_singular_plural():
    assert singular("boxes") == "box"
    assert singular("status") == "status"
    assert plural("category") == "categories"
    assert plural("box") == "boxes"
