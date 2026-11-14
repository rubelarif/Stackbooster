from stackbooster.analyzers.javascript import find_calls
from stackbooster.scanner import scan


def test_forms_and_fields(shop_site):
    cart = shop_site.page("/cart.php")
    (form,) = cart.forms
    assert form.action == "checkout.php"
    assert form.method == "POST"
    names = [(f.name, f.type, f.required) for f in form.fields]
    assert names == [
        ("full_name", "text", True),
        ("email", "email", True),
        ("address", "textarea", True),
        ("coupon", "text", False),
    ]


def test_title_from_tag_or_php_variable(shop_site):
    assert shop_site.page("/contact.html").title == "Contact us"
    assert shop_site.page("/products.php").title == "Products"  # from $page_title
    assert shop_site.page("/admin/orders.php").title == "Orders - Admin"


def test_html_comments_are_ignored(shop_site):
    contact = shop_site.page("/contact.html")
    assert [f.action for f in contact.forms] == ["contact.php"]


def test_inline_script_ajax(shop_site):
    product = shop_site.page("/product.php")
    (call,) = product.ajax_calls
    assert (call.url, call.method, call.library) == ("api.php?action=add_to_cart", "POST", "jquery")
    assert call.line > 20  # line in the .php file, not in the script block


def test_standalone_js_calls(shop_site):
    calls = [(c.url, c.method, c.library) for c in shop_site.script_calls]
    assert calls == [
        ("api.php?action=cart_count", "GET", "fetch"),
        ("api.php?action=remove_from_cart", "POST", "jquery"),
        ("api.php?action=search&q=", "GET", "jquery"),
    ]


def test_vendored_js_is_skipped(shop_site):
    assert "js/jquery-1.8.3.min.js" not in shop_site.files


def test_partial_detected(shop_site):
    header = shop_site.page("/includes/header.php")
    assert header.partial
    assert "/js/cart.js" in header.scripts


def test_find_calls_variants():
    js = """
    var x = new XMLHttpRequest(); x.open('PUT', '/items/1');
    axios.delete('/api/thing');
    $('#box').load('fragment.html');
    $.ajax('legacy.php', { method: 'post' });
    fetch(`/search?q=${term}`, { method: 'GET' });
    // fetch('commented.php')
    """
    calls = {(c.url, c.method, c.library) for c in find_calls(js)}
    assert calls == {
        ("/items/1", "PUT", "xhr"),
        ("/api/thing", "DELETE", "axios"),
        ("fragment.html", "GET", "jquery"),
        ("legacy.php", "POST", "jquery"),
        ("/search?q=", "GET", "fetch"),
    }


def test_onclick_handler(make_project):
    root = make_project(
        {"page.html": "<html><body><button onclick=\"$.post('vote.php', {})\">Vote</button></body></html>"}
    )
    (page,) = scan(root).pages
    assert [(c.url, c.method) for c in page.ajax_calls] == [("vote.php", "POST")]
