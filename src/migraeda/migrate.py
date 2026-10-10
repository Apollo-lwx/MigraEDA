"""Migrate pipeline: parse → normalize → (optional KiCad) → diff → report → audit."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from migraeda.audit import new_migration_id, record_migration
from migraeda.diff import diff_stats
from migraeda.epro_parse import parse_epro
from migraeda.models import ProjectStats
from migraeda.normalize import normalize_model
from migraeda.report import write_report


def kicad_available() -> bool:
    """Return True if pcbnew or kicad-cli looks available."""
    try:
        import pcbnew  # type: ignore  # noqa: F401

        return True
    except Exception:
        pass
    return shutil.which("kicad-cli") is not None or shutil.which("kicad") is not None


def _write_placeholder_kicad(outdir: Path, stats: ProjectStats) -> list[str]:
    """Write minimal KiCad-like placeholders (openable as text, not full PCB)."""
    artifacts: list[str] = []
    pro = outdir / f"{stats.name}.kicad_pro"
    pcb = outdir / f"{stats.name}.kicad_pcb"
    sch = outdir / f"{stats.name}.kicad_sch"

    pro.write_text(
        json.dumps(
            {
                "meta": {"filename": pro.name, "generator": "MigraEDA", "version": 1},
                "project": {"title": stats.name},
                "migraeda": {"placeholder": True, "note": "dry-run / no-KiCad stub"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts.append(pro.name)

    refs = "\n".join(f"  ;; footprint {r}" for r in stats.component_refs)
    nets = "\n".join(f"  ;; net {n}" for n in stats.net_names)
    pcb.write_text(
        f"(kicad_pcb (version 20240108) (generator MigraEDA)\n"
        f"  (general (thickness 1.6))\n"
        f"  ;; PLACEHOLDER — not a real layout. vias={stats.via_count}\n"
        f"{refs}\n{nets}\n)\n",
        encoding="utf-8",
    )
    artifacts.append(pcb.name)

    sch.write_text(
        f"(kicad_sch (version 20231120) (generator MigraEDA)\n"
        f"  ;; PLACEHOLDER schematic for {stats.name}\n)\n",
        encoding="utf-8",
    )
    artifacts.append(sch.name)
    return artifacts


def _target_stats_for_dry_run(source: ProjectStats, *, inject_mismatch: dict | None = None) -> ProjectStats:
    """Build comparable target stats from source (identity), optional mismatch for tests."""
    data = source.to_dict()
    data["source"] = "dry-run-generated"
    if inject_mismatch:
        data.update(inject_mismatch)
    return ProjectStats.from_dict(data)


def run_migrate(
    input_epro: str | Path,
    outdir: str | Path,
    *,
    dry_run: bool = True,
    audit_root: Path | None = None,
    inject_target_mismatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run full migrate pipeline. Always works without KiCad when dry_run=True."""
    input_epro = Path(input_epro)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    migration_id = new_migration_id()
    model = parse_epro(input_epro)
    source_stats = normalize_model(model)

    source_stats_path = outdir / "source_stats.json"
    source_stats_path.write_text(
        json.dumps(source_stats.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    use_kicad = (not dry_run) and kicad_available()
    backend = "kicad" if use_kicad else "dry-run"

    # MVP: even if KiCad is present, we still emit stats from source unless a
    # real importer is wired. Hook point for future pcbnew/CLI backend.
    if use_kicad:
        # Future: call real importer here. For now identical to dry-run placeholders
        # plus a marker so CI stays deterministic without KiCad.
        target_stats = _target_stats_for_dry_run(source_stats, inject_mismatch=inject_target_mismatch)
        kicad_artifacts = _write_placeholder_kicad(outdir, target_stats)
    else:
        target_stats = _target_stats_for_dry_run(source_stats, inject_mismatch=inject_target_mismatch)
        kicad_artifacts = _write_placeholder_kicad(outdir, target_stats)

    kicad_stats_path = outdir / "kicad_stats.json"
    kicad_stats_path.write_text(
        json.dumps(target_stats.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = diff_stats(source_stats, target_stats)
    diff_path = outdir / "diff.json"
    diff_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_path = write_report(result, outdir / "report.md", fmt="md")
    write_report(result, outdir / "report.html", fmt="html")

    artifacts = [
        "source_stats.json",
        "kicad_stats.json",
        "diff.json",
        "report.md",
        "report.html",
        *kicad_artifacts,
    ]

    record_migration(
        migration_id=migration_id,
        source_epro=input_epro,
        outdir=outdir,
        artifacts=artifacts,
        dry_run=dry_run or not use_kicad,
        diff_grade=result.grade.value,
        extra={"backend": backend, "project": source_stats.name},
        audit_root=audit_root,
    )

    return {
        "migration_id": migration_id,
        "grade": result.grade.value,
        "backend": backend,
        "outdir": str(outdir.resolve()),
        "diff": result.to_dict(),
        "artifacts": artifacts,
    }
