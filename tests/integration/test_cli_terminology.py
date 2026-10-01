import json

from typer.testing import CliRunner

from kaizen.cli.main import app

runner = CliRunner()


def test_terminology_lifecycle_via_cli(tmp_path):
    ws = tmp_path / "ws"
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "list"])
    assert r.exit_code == 0, r.output
    assert "REL-001" in r.output and "Surgical Tape" in r.output
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "add", "--canonical", "Vessel Dilator", "--alias", "DILATOR VESSEL", "--alias", "DILATOR", "--scope", "global", "--by", "rahul", "--notes", "cli test"])
    assert r.exit_code == 0, r.output
    new_id = [t for t in r.output.split() if t.startswith("REL-")][0]
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "update", new_id, "--alias", "DILATOR VESSEL", "--alias", "DILATOR", "--alias", "VESSEL DILATOR", "--by", "rahul", "--note", "alias added"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "history", new_id])
    assert r.exit_code == 0 and "v1" in r.output and "v2" in r.output and "alias added" in r.output
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "deactivate", new_id, "--by", "rahul"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "list"])
    assert new_id not in r.output
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "list", "--all"])
    assert new_id in r.output
    out = tmp_path / "rels.xlsx"
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "export", str(out)])
    assert r.exit_code == 0 and out.exists()
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "import", str(out), "--by", "rahul"])
    assert r.exit_code == 0 and "unchanged" in r.output


def test_run_records_relationship_usage_in_workspace(tmp_path):
    from kaizen.datasets.build import build_golden

    golden = build_golden(tmp_path / "golden")
    ws = tmp_path / "ws"
    r = runner.invoke(app, ["--workspace", str(ws), "run", str(golden / "sku-001"), "--out", str(tmp_path / "out")])
    assert r.exit_code == 0, r.output
    run = json.loads((tmp_path / "out" / "run.json").read_text())
    run_id = run["metadata"]["run_id"]
    assert run["relationship_usage"]["REL-001"] >= 1
    r = runner.invoke(app, ["--workspace", str(ws), "runs", "list"])
    assert r.exit_code == 0 and run_id in r.output
    r = runner.invoke(app, ["--workspace", str(ws), "terminology", "update", "REL-001", "--canonical", "Surgical Tape (renamed)", "--by", "rahul"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["--workspace", str(ws), "runs", "relationships", run_id])
    assert r.exit_code == 0 and "Surgical Tape" in r.output and "(renamed)" not in r.output and "v1" in r.output


def test_authorized_source_mapping_preview_and_repeat_import(tmp_path):
    path = tmp_path / "authorized.csv"
    path.write_text("ERP,Customer,Component\nDEAD END SOURCE CAP,Customer end cap,0000123\n")
    ws = tmp_path / "ws"
    inspected = runner.invoke(app, ["terminology", "inspect", str(path)])
    assert inspected.exit_code == 0 and '"ERP"' in inspected.output
    command = ["--workspace", str(ws), "terminology", "import", str(path), "--canonical-column", "Customer", "--alias-column", "ERP",
               "--anchor-column", "Component", "--default-scope", "sku:1175108DNS", "--by", "quality"]
    preview = runner.invoke(app, command + ["--dry-run"])
    assert preview.exit_code == 0 and "Preview: created 1" in preview.output
    listed = runner.invoke(app, ["--workspace", str(ws), "terminology", "list"])
    assert "Customer end cap" not in listed.output
    imported = runner.invoke(app, command)
    assert imported.exit_code == 0 and "created 1" in imported.output
    again = runner.invoke(app, command)
    assert again.exit_code == 0 and "created 0, updated 0, unchanged 1" in again.output
