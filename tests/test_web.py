import json
import urllib.error
import urllib.request

import pytest

from stackbooster.web.server import serve_in_thread


@pytest.fixture
def dashboard(shop_root):
    server = serve_in_thread(shop_root, "fastapi-react")
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()
    server.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read().decode("utf-8")


def test_dashboard_pages(dashboard):
    status, ctype, body = get(dashboard + "/")
    assert status == 200 and ctype.startswith("text/html")
    assert "Migration plan: legacy_shop" in body and "re-scan" in body

    status, ctype, body = get(dashboard + "/api/sitemap.json")
    assert json.loads(body)["summary"]["tables"] == 8

    _, _, body = get(dashboard + "/api/plan.json")
    assert json.loads(body)["target"]["key"] == "fastapi-react"

    _, _, body = get(dashboard + "/api/graph.mmd")
    assert body.startswith("flowchart")

    _, ctype, body = get(dashboard + "/report.md")
    assert ctype.startswith("text/markdown") and body.startswith("# Migration plan")


def test_dashboard_404(dashboard):
    with pytest.raises(urllib.error.HTTPError) as err:
        get(dashboard + "/nope")
    assert err.value.code == 404
