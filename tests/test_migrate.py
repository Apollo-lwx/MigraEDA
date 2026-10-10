from migraeda.migrate import kicad_available, run_migrate


def test_migrate_dry_run_pass(simple_epro, tmp_path, audit_tmp):
    out = tmp_path / "out"
    result = run_migrate(simple_epro, out, dry_run=True, audit_root=audit_tmp)
    assert result["grade"] == "PASS"
    assert result["backend"] == "dry-run"
    assert (out / "simple.kicad_pro").is_file()
    assert (out / "kicad_stats.json").is_file()


def test_kicad_available_bool():
    assert isinstance(kicad_available(), bool)
