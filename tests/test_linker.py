import pytest

from stackbooster.linker import normalize_url
from stackbooster.scanner import scan


@pytest.mark.parametrize(
    ("url", "source", "expected"),
    [
        ("cart.php", "index.php", "/cart.php"),
        ("../login.php", "admin/orders.php", "/login.php"),
        ("orders.php?status=new", "admin/orders.php", "/admin/orders.php"),
        ("/", "x/y.php", "/index.php"),
        ("shop/", "index.php", "/shop/index.php"),
        ("?page=2", "admin/orders.php", "/admin/orders.php"),
    ],
)
def test_normalize_url(url, source, expected):
    assert normalize_url(url, source)[0] == expected


@pytest.mark.parametrize("url", ["#top", "mailto:a@b.c", "javascript:void(0)", "https://cdn.example.com/x.js", "//cdn/x"])
def test_off_site_urls_are_skipped(url):
    assert normalize_url(url, "index.php") is None


def links(site):
    return {(link.source, link.target, link.kind, link.method): link.resolved for link in site.links}


def test_form_and_ajax_links(shop_site):
    found = links(shop_site)
    assert found[("/cart.php", "/checkout.php", "form", "POST")]
    assert found[("/product.php", "/api.php?action=add_to_cart", "ajax", "POST")]
    assert found[("/login.php", "/login.php", "form", "POST")]  # empty action posts to itself
    assert found[("/admin/orders.php", "/admin/orders.php", "form", "POST")]


def test_partial_links_resolve_against_including_page(shop_site):
    found = links(shop_site)
    assert found[("/includes/header.php", "/cart.php", "link", "GET")]
    assert found[("/includes/header.php", "/api.php?action=cart_count", "script-ajax", "GET")]
    assert found[("/includes/header.php", "/api.php?action=search", "script-ajax", "GET")]


def test_unresolved_links_are_reported(shop_site):
    unresolved = {(link.source, link.target) for link in shop_site.links if not link.resolved}
    assert unresolved == {("/contact.html", "contact.php"), ("/includes/header.php", "logout.php")}


def test_extensionless_url_matches_php_file(make_project):
    root = make_project(
        {
            "about.php": "<?php echo '<p>hi</p>'; ?>",
            "index.html": "<html><body><a href='about'>About</a><a href='style.css'>x</a></body></html>",
        }
    )
    site = scan(root)
    assert [(link.target, link.resolved) for link in site.links] == [("/about.php", True)]


def test_js_without_loader_page_resolves_against_its_folder(make_project):
    root = make_project({"js/app.js": "fetch('../data.php')", "data.php": "<?php echo json_encode([]);"})
    site = scan(root)
    (link,) = site.links
    assert (link.source, link.target, link.resolved) == ("/js/app.js", "/data.php", True)
