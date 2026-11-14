import json

from click.testing import CliRunner

from stackbooster.cli import main


def run(*args):
    result = CliRunner().invoke(main, [str(a) for a in args], catch_exceptions=False)
    return result


def test_analyze_summary(shop_root):
    result = run("analyze", shop_root, "--summary")
    assert result.exit_code == 0
    assert json.loads(result.output)["routes"] == 15


def test_analyze_then_report_from_json(shop_root, tmp_path):
    site_json = tmp_path / "site.json"
    assert run("analyze", shop_root, "-o", site_json).exit_code == 0
    assert json.loads(site_json.read_text())["schema_version"] == 1
    out = tmp_path / "plan.md"
    assert run("report", site_json, "-o", out).exit_code == 0
    assert "Migration plan" in out.read_text()


def test_html_report_and_plan(shop_root, tmp_path):
    assert run("report", shop_root, "-f", "html", "-o", tmp_path / "r.html").exit_code == 0
    result = run("plan", shop_root)
    data = json.loads(result.output)
    assert data["target"]["key"] == "fastapi-react"
    assert sum(data["effort_totals"].values()) == len(data["items"])


def test_exclude_and_no_infer(shop_root):
    result = run("analyze", shop_root, "-x", "admin", "--no-infer")
    data = json.loads(result.output)
    assert not any(r["file"].startswith("admin/") for r in data["routes"])
    assert not any(fk["inferred"] for t in data["tables"] for fk in t["foreign_keys"])


def test_scaffold_refuses_to_overwrite(shop_root, tmp_path):
    out = tmp_path / "rebuilt"
    first = run("scaffold", shop_root, "-o", out)
    assert first.exit_code == 0
    assert (out / "backend/app/models.py").exists()
    assert (out / "MIGRATION_PLAN.md").exists()
    second = CliRunner().invoke(main, ["scaffold", str(shop_root), "-o", str(out)])
    assert second.exit_code != 0 and "--force" in second.output
    assert run("scaffold", shop_root, "-o", out, "--force").exit_code == 0


def test_graph_and_targets(shop_root):
    assert run("graph", shop_root).output.startswith("flowchart LR")
    assert "fastapi-react" in run("targets").output


def test_bad_source_file(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    result = CliRunner().invoke(main, ["analyze", str(bad)])
    assert result.exit_code != 0
