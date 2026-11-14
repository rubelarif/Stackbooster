from stackbooster.report import mermaid_diagram, render_html, render_markdown


def test_markdown_report(shop_site, shop_plan):
    md = render_markdown(shop_site, shop_plan)
    assert md.startswith("# Migration plan: legacy_shop")
    assert "## Phase 1: Database models" in md
    assert "POST /api/checkout" in md
    assert "```mermaid" in md
    assert "newsletter_signups" in md  # unused table listed
    assert "sql-injection" in md


def test_html_report_is_escaped(shop_site, shop_plan):
    html = render_html(shop_site, shop_plan)
    assert html.startswith("<!DOCTYPE html>")
    assert "&lt;CartPage /&gt;" in html  # summaries are escaped, not rendered as tags
    assert "re-scan" not in html
    assert "re-scan" in render_html(shop_site, shop_plan, live=True)


def test_mermaid_diagram(shop_site):
    graph = mermaid_diagram(shop_site)
    assert graph.startswith("flowchart LR")
    assert "P_cart_php -->|form POST| R_checkout_php" in graph
    assert "T_products --- T_categories" in graph  # declared FK
    assert "T_orders -.- T_users" in graph  # inferred FK
    assert "-->|link GET|" not in graph
    assert "-->|link GET|" in mermaid_diagram(shop_site, include_links=True)
