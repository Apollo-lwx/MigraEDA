"""Command-line interface for MigraEDA."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from migraeda import __version__
from migraeda.audit import rollback
from migraeda.convert import convert, load_netlist
from migraeda.diff import diff_stats
from migraeda.lvs import compare_netlists
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


def _cmd_convert(args: argparse.Namespace) -> int:
    from migraeda.convert import PcbConvertResult

    res = convert(args.input, args.to, out_dir=args.output, verify=not args.no_verify)
    if isinstance(res, PcbConvertResult):
        print("direction: eprj-pcb -> ad-ascii-pcbdoc")
        print(f"source: {res.components} components, {res.pads} pads, "
              f"{res.tracks} tracks, {res.vias} vias")
        print(f"written: {res.out_path}")
        if res.verify_grade:
            print(f"loop-verify: {res.verify_grade} ({res.verify_details})")
            return {"PASS": 0, "WARN": 1, "FAIL": 2}[res.verify_grade]
        return 0
    print(f"direction: {res.direction}")
    print(f"source: {res.src_components} components, {res.src_wires} wires")
    print(f"written: {res.out_path}")
    for n in res.notes:
        print(f"note: {n}")
    if res.verify is not None:
        v = res.verify
        print(
            f"loop-verify: common_pins={v.common_pin_count} "
            f"mismatched={len(v.pin_mismatches)} "
            f"nets_matched={len(v.matches)}"
        )
        for pm in v.pin_mismatches[:20]:
            print(f"  mismatch: {pm.ref}.{pm.pin} src={pm.a_net!r} out={pm.b_net!r}")
        if v.pin_mismatches:
            return 2
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    a = load_netlist(args.file_a)
    b = load_netlist(args.file_b)
    res = compare_netlists(a, b)
    print(f"A: {res.a_name}")
    print(f"B: {res.b_name}")
    print(
        f"common pins: {res.common_pin_count}, mismatched: {len(res.pin_mismatches)}, "
        f"nets matched: {len(res.matches)}"
    )
    print(f"refs only in A: {res.a_only_refs}")
    print(f"refs only in B: {res.b_only_refs}")
    if res.pin_mismatches:
        print("pin mismatches:")
        for pm in res.pin_mismatches[: int(args.limit)]:
            print(f"  {pm.ref}.{pm.pin}: A={pm.a_net!r} B={pm.b_net!r}")
    named = [m for m in res.matches if m.by_name]
    renamed = [m for m in res.matches if not m.by_name]
    print(f"name-matched nets: {len(named)}, structurally-matched nets: {len(renamed)}")
    if args.report:
        from migraeda.verify_report import write_verify_report

        out = write_verify_report(a, b, res, args.report)
        print(f"report: {out}")
    return 0 if not res.pin_mismatches else 2


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

    c = sub.add_parser(
        "convert",
        help="Convert a schematic between .eprj and .SchDoc (with loop verification)",
    )
    c.add_argument("input", help="Input file (.eprj or binary .SchDoc)")
    c.add_argument("--to", required=True, choices=["ad", "eprj", "adpcb"],
                   help="Target: 'ad' (ASCII .SchDoc), 'eprj', or 'adpcb' (ASCII .PcbDoc)")
    c.add_argument("-o", "--output", default=None,
                   help="Output directory (default: <input_dir>/out)")
    c.add_argument("--no-verify", action="store_true",
                   help="Skip closed-loop verification of the converted file")
    c.set_defaults(func=_cmd_convert)

    v = sub.add_parser("verify", help="LVS-compare two design files (eprj/SchDoc/PcbDoc)")
    v.add_argument("file_a", help="First file")
    v.add_argument("file_b", help="Second file")
    v.add_argument("--limit", default=30, help="Max mismatches to print")
    v.add_argument("--report", default=None, help="Write a standard Markdown report to this path")
    v.set_defaults(func=_cmd_verify)

    pd = sub.add_parser("pcbdiff", help="PCB-level diff between two .PcbDoc files")
    pd.add_argument("file_a", help="First .PcbDoc")
    pd.add_argument("file_b", help="Second .PcbDoc")
    pd.add_argument("--tol", type=float, default=2.0, help="Position tolerance in mil")
    pd.add_argument("--report", default=None, help="Write a Markdown report to this path")
    pd.set_defaults(func=_cmd_pcbdiff)

    ld = sub.add_parser("libdiff", help="Library-level diff (symbols/footprints) between library sources")
    ld.add_argument("file_a", help="Library source A (.eprj/.SchLib/.PcbLib/.PcbDoc)")
    ld.add_argument("file_b", help="Library source B (.eprj/.SchLib/.PcbLib/.PcbDoc)")
    ld.add_argument("--tol", type=float, default=1.0, help="Position tolerance in mil")
    ld.add_argument("--report", default=None, help="Write a Markdown report to this path")
    ld.set_defaults(func=_cmd_libdiff)

    lc = sub.add_parser("libconvert", help="Convert a library source into an .eprj library package")
    lc.add_argument("input", help="Library source (.eprj/.SchLib/.PcbLib/.PcbDoc)")
    lc.add_argument("-o", "--output", default=None, help="Output directory (default: <input_dir>/out)")
    lc.add_argument("--no-verify", action="store_true", help="Skip loop verification")
    lc.set_defaults(func=_cmd_libconvert)

    rt = sub.add_parser(
        "roundtrip",
        help="Round-trip conversion (src -> target -> back) with LVS vs the original; "
        "intermediate artifacts are kept for inspection",
    )
    rt.add_argument("input", help="Source file (.eprj or .SchDoc)")
    rt.add_argument("-o", "--output", default=None,
                    help="Output dir (default: <input_dir>/out/roundtrip)")
    rt.set_defaults(func=_cmd_roundtrip)

    s = sub.add_parser("samples", help="List design samples under samples/ (see samples/README.md)")
    s.add_argument("--root", default="samples", help="Samples root directory")
    s.set_defaults(func=_cmd_samples)

    li = sub.add_parser(
        "libinspect",
        help="Structural self-inspection of a library/design file (metadata only, safe to share)",
    )
    li.add_argument("input", help="File to inspect (.SchLib/.PcbLib/.PcbDoc/.SchDoc/...)")
    li.set_defaults(func=_cmd_libinspect)

    fz = sub.add_parser(
        "fuzz",
        help="Fuzz the conversion chain with mutated inputs (finds hidden bugs)",
    )
    fz.add_argument("input", help="Source file (.eprj/.SchDoc)")
    fz.add_argument("-n", "--iterations", type=int, default=50, help="Iterations")
    fz.add_argument("--seed", type=int, default=42, help="Base random seed")
    fz.add_argument("--keep", default=None, help="Dir to keep crashing artifacts")
    fz.set_defaults(func=_cmd_fuzz)

    sc = sub.add_parser(
        "selfcheck",
        help="Invariant battery on one file (suspicious signals for parser/file issues)",
    )
    sc.add_argument("input", help="File to check (.eprj/.SchDoc/.PcbDoc)")
    sc.set_defaults(func=_cmd_selfcheck)
    return p


def _cmd_fuzz(args: argparse.Namespace) -> int:
    from migraeda.fuzz import fuzz_file, render_fuzz_report

    report = fuzz_file(args.input, iterations=args.iterations,
                       seed=args.seed, keep_dir=args.keep)
    print(render_fuzz_report(args.input, report))
    return 0 if report.ok else 2


def _cmd_selfcheck(args: argparse.Namespace) -> int:
    from migraeda.selfcheck import selfcheck

    print(selfcheck(args.input))
    return 0


def _cmd_libinspect(args: argparse.Namespace) -> int:
    from migraeda.libinspect import inspect_library

    print(inspect_library(args.input))
    return 0


def _cmd_samples(args: argparse.Namespace) -> int:
    from migraeda.samples import describe

    print(describe(args.root))
    return 0


def _cmd_roundtrip(args: argparse.Namespace) -> int:
    from migraeda.convert import eprj_has_pcb, roundtrip, roundtrip_pcb

    res = roundtrip(args.input, out_dir=args.output)
    print(f"direction: {res.direction}")
    print(f"leg1 kept: {res.intermediate}")
    print(f"leg1 loop-verify: {res.leg1_verify}")
    print(f"roundtrip kept: {res.final}")
    print(f"final vs ORIGINAL: common_pins={res.final_common_pins} "
          f"mismatched={res.final_mismatches} nets_matched={res.nets_matched}")
    for n in res.notes[:10]:
        print(f"  note: {n}")
    print(f"roundtrip: {'IDENTICAL ✅' if res.ok else 'DIFFERS ❌'}")
    rc = 0 if res.ok else 2

    # PCB round trip too, when the source project carries PCB data
    if args.input.lower().endswith(".eprj") and eprj_has_pcb(args.input):
        print("\n--- PCB round trip ---")
        pres = roundtrip_pcb(args.input, out_dir=args.output)
        print(f"leg1 kept: {pres.leg1}")
        print(f"leg1 pcbdiff: {pres.leg1_grade}")
        print(f"roundtrip kept: {pres.final}")
        print(f"final pcbdiff vs ORIGINAL: {pres.final_grade} ({pres.final_details})")
        print(f"pcb roundtrip: {'PASS ✅' if pres.ok else 'FAIL ❌'}")
        rc = max(rc, 0 if pres.ok else 2)
    return rc


def _cmd_libconvert(args: argparse.Namespace) -> int:
    from migraeda.convert import libconvert

    res = libconvert(args.input, out_dir=args.output, verify=not args.no_verify)
    print(f"library: {res.symbols} symbols, {res.footprints} footprints")
    print(f"written: {res.output}")
    if res.verify_grade:
        print(f"loop-verify: {res.verify_grade} ({res.verify_details})")
        return {"PASS": 0, "WARN": 1, "FAIL": 2}[res.verify_grade]
    return 0


def _load_library(path: str):
    from migraeda.convert import load_library

    try:
        return load_library(path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _cmd_libdiff(args: argparse.Namespace) -> int:
    from migraeda.libdiff import compare_libraries, render_libdiff_report

    a = _load_library(args.file_a)
    b = _load_library(args.file_b)
    res = compare_libraries(a, b, pos_tol=args.tol)
    print(f"grade: {res.grade}")
    print(f"symbols: {res.symbols_common} common, {len(res.symbol_diffs)} diff  "
          f"footprints: {res.fps_common} common, {len(res.fp_diffs)} diff")
    if res.scale_suspect:
        print(f"WARNING: {res.scale_suspect}")
    for d in (res.symbol_diffs + res.fp_diffs)[:10]:
        for i in d.issues[:3]:
            print(f"  {d.name}: {i}")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_libdiff_report(res, args.file_a, args.file_b),
                       encoding="utf-8")
        print(f"report: {out}")
    return {"PASS": 0, "WARN": 1, "FAIL": 2}[res.grade]


def _cmd_pcbdiff(args: argparse.Namespace) -> int:
    from migraeda.epcb import parse_epcb
    from migraeda.pcbdiff import compare_pcb, render_pcbdiff_report
    from migraeda.pcbdoc import parse_pcbdoc

    def load_pcb(p: str):
        suf = Path(p).suffix.lower()
        if suf == ".pcbdoc":
            with open(p, "rb") as fh:
                head = fh.read(16)
            if head.startswith(b"|RECORD"):
                from migraeda.pcbascii import parse_pcb_ascii

                return parse_pcb_ascii(p)
            return parse_pcbdoc(p)
        if suf == ".eprj":
            return parse_epcb(p)
        raise SystemExit(f"unsupported PCB source: {p}")

    a = load_pcb(args.file_a)
    b = load_pcb(args.file_b)
    res = compare_pcb(a, b, pos_tol_mil=args.tol)
    print(f"grade: {res.grade}")
    if res.alignment:
        print(f"alignment: {res.alignment}")
    print(f"outline: {'OK' if res.outline_ok else 'DIFF'}  "
          f"comps: {res.comps_common} common, {len(res.comps_moved)} moved  "
          f"pads: {res.pads_checked} checked, {len(res.pads_moved)} moved  "
          f"vias: {res.vias_a} vs {res.vias_b}")
    print(f"copper diffs: {len(res.copper_diffs)}, nets only A/B: "
          f"{len(res.nets_only_a)}/{len(res.nets_only_b)}")
    for item in (res.comps_moved + res.pads_moved + res.copper_diffs)[:15]:
        print(f"  {item}")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_pcbdiff_report(res, args.file_a, args.file_b),
                       encoding="utf-8")
        print(f"report: {out}")
    return {"PASS": 0, "WARN": 1, "FAIL": 2}[res.grade]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
