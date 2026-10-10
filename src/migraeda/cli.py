"""Command-line interface for MigraEDA."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from migraeda import __version__
from migraeda.audit import rollback
from migraeda.diff import diff_stats
from migraeda.migrate import kicad_available, run_migrate
from migraeda.models import ProjectStats
from migraeda.normalize import normalize_epro, normalize_stats_json
from migraeda.report import load_diff_json, write_report


def _cmd_migrate(args: argparse.Namespace) -> int:
    result = run_migrate(
        args.input,
        args.output,
        dry_run=args.dry_run or not kicad_available(),
    )
    print(f"migration_id: {result['migration_id']}")
    print(f"grade: {result['grade']}")
    print(f"backend: {result['backend']}")
    print(f"outdir: {result['outdir']}")
    return 0


def _load_stats_side(path: Path) -> ProjectStats:
    path = Path(path)
    if path.suffix.lower() == ".epro" or path.name.endswith(".epro"):
        return normalize_epro(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    # accept either a stats dict or a diff-like wrapper
    if "component_count" in data or "net_names" in data:
        return normalize_stats_json(data)
    if "source" in data and isinstance(data["source"], dict) and "component_count" in data["source"]:
        return normalize_stats_json(data["source"])
    raise SystemExit(f"cannot interpret stats from {path}")


def _cmd_diff(args: argparse.Namespace) -> int:
    source = _load_stats_side(Path(args.source))
    target = _load_stats_side(Path(args.target))
    result = diff_stats(source, target)
    out = Path(args.output)
    if out.suffix.lower() == ".json":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        write_report(result, out, fmt="md")
        # also drop sibling json for tooling
        json_path = out.with_suffix(".json") if out.suffix else out.parent / "diff.json"
        if out.name == "report.md":
            json_path = out.parent / "diff.json"
        json_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"grade: {result.grade.value}")
    print(f"wrote: {out}")
    return 0 if result.grade.value != "FAIL" else 2


def _cmd_report(args: argparse.Namespace) -> int:
    diff = load_diff_json(args.diff_json)
    fmt = "html" if args.html else "md"
    out = Path(args.output)
    if args.html and out.suffix.lower() not in {".html", ".htm"}:
        # honor explicit -o even if extension is md; content follows --html
        pass
    write_report(diff, out, fmt=fmt)
    print(f"wrote: {out}")
    return 0


def _cmd_rollback(args: argparse.Namespace) -> int:
    result = rollback(args.migration_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migraeda",
        description="MigraEDA — verifiable EasyEDA Pro → KiCad migration.",
    )
    p.add_argument("--version", action="version", version=f"migraeda {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("migrate", help="Migrate an .epro (dry-run works without KiCad)")
    m.add_argument("input", help="Input .epro path")
    m.add_argument("-o", "--output", required=True, help="Output directory")
    m.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call KiCad; emit placeholder project + stats + diff + audit",
    )
    m.set_defaults(func=_cmd_migrate)

    d = sub.add_parser("diff", help="diff_v0 between source .epro/stats and target stats")
    d.add_argument("source", help="Source .epro or stats JSON")
    d.add_argument("target", help="Target .epro, kicad_stats.json, or stats JSON")
    d.add_argument("-o", "--output", required=True, help="Output report.md or diff.json")
    d.set_defaults(func=_cmd_diff)

    r = sub.add_parser("report", help="Render a diff.json to markdown or HTML")
    r.add_argument("diff_json", help="Path to diff.json")
    r.add_argument("-o", "--output", required=True, help="Output path")
    r.add_argument("--html", action="store_true", help="Write HTML instead of markdown")
    r.set_defaults(func=_cmd_report)

    rb = sub.add_parser("rollback", help="Roll back a migration by id")
    rb.add_argument("migration_id", help="migration_id from a previous migrate")
    rb.set_defaults(func=_cmd_rollback)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
