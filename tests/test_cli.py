import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, env_extra: dict | None = None):
    env = {**dict(**__import__("os").environ), **(env_extra or {})}
    return subprocess.run(
        [sys.executable, "-m", "migraeda", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_migrate_dry_run(simple_epro, tmp_path, audit_tmp):
    out = tmp_path / "cli_out"
    r = _run(
        "migrate",
        str(simple_epro),
        "-o",
        str(out),
        "--dry-run",
        env_extra={"MIGRAEDA_AUDIT_DIR": str(audit_tmp), "PYTHONPATH": str(ROOT / "src")},
    )
    assert r.returncode == 0, r.stderr
    assert "migration_id:" in r.stdout
    assert (out / "diff.json").is_file()
    assert (out / "report.md").is_file()
    data = json.loads((out / "diff.json").read_text())
    assert data["grade"] == "PASS"


def test_cli_diff_warn(bus_epro, golden_dir, tmp_path):
    out = tmp_path / "warn.md"
    r = _run(
        "diff",
        str(bus_epro),
        str(golden_dir / "bus_mismatch_target_warn.json"),
        "-o",
        str(out),
        env_extra={"PYTHONPATH": str(ROOT / "src")},
    )
    assert r.returncode == 0
    assert "WARN" in r.stdout
    assert out.is_file()


def test_cli_report_html(simple_epro, tmp_path, audit_tmp):
    out = tmp_path / "m"
    _run(
        "migrate",
        str(simple_epro),
        "-o",
        str(out),
        "--dry-run",
        env_extra={"MIGRAEDA_AUDIT_DIR": str(audit_tmp), "PYTHONPATH": str(ROOT / "src")},
    )
    html_out = tmp_path / "r.html"
    r = _run(
        "report",
        str(out / "diff.json"),
        "-o",
        str(html_out),
        "--html",
        env_extra={"PYTHONPATH": str(ROOT / "src")},
    )
    assert r.returncode == 0
    assert "<html" in html_out.read_text(encoding="utf-8")


def test_cli_rollback(simple_epro, tmp_path, audit_tmp):
    out = tmp_path / "m2"
    r = _run(
        "migrate",
        str(simple_epro),
        "-o",
        str(out),
        "--dry-run",
        env_extra={"MIGRAEDA_AUDIT_DIR": str(audit_tmp), "PYTHONPATH": str(ROOT / "src")},
    )
    mid = [ln.split(":", 1)[1].strip() for ln in r.stdout.splitlines() if ln.startswith("migration_id:")][0]
    rb = _run(
        "rollback",
        mid,
        env_extra={"MIGRAEDA_AUDIT_DIR": str(audit_tmp), "PYTHONPATH": str(ROOT / "src")},
    )
    assert rb.returncode == 0
    assert "rolled_back" in rb.stdout
