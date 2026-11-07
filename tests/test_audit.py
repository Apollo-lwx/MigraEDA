from migraeda.audit import load_record, rollback
from migraeda.migrate import run_migrate


def test_audit_and_rollback(simple_epro, tmp_path, audit_tmp):
    out = tmp_path / "out"
    result = run_migrate(simple_epro, out, dry_run=True, audit_root=audit_tmp)
    mid = result["migration_id"]
    rec = load_record(mid, audit_root=audit_tmp)
    assert rec["status"] == "active"
    assert (out / "report.md").is_file()

    rb = rollback(mid, audit_root=audit_tmp)
    assert rb["status"] == "rolled_back"
    assert not (out / "report.md").exists()
    rec2 = load_record(mid, audit_root=audit_tmp)
    assert rec2["status"] == "rolled_back"
