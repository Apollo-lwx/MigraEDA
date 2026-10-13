"""Conversion orchestration: IR -> target format -> closed-loop verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from migraeda.adascii import parse_schdoc_ascii, write_schdoc_ascii
from migraeda.eprj_sqlite import parse_eprj, parse_eprj_ir
from migraeda.eprj_write import write_eprj
from migraeda.ir import SchematicIR, pin_abs
from migraeda.lvs import LvsResult, compare_netlists
from migraeda.netlist_model import NetlistModel, SchComponent
from migraeda.schdoc import parse_schdoc, parse_schdoc_ir
from migraeda.schgeom import PinPoint, SchematicConnectivity


def load_ir(path: str | Path) -> SchematicIR:
    """Load a schematic file (.eprj or binary/ascii .SchDoc) into IR."""
    path = Path(path)
    suf = path.suffix.lower()
    if suf == ".eprj":
        return parse_eprj_ir(path)
    if suf == ".schdoc":
        with open(path, "rb") as fh:
            head = fh.read(16)
        if head.startswith(b"|HEADER"):
            from migraeda.adascii import parse_schdoc_ascii_ir

            return parse_schdoc_ascii_ir(path)
        return parse_schdoc_ir(path)
    raise ValueError(f"unsupported input format: {path.suffix}")


def netlist_from_ir(ir: SchematicIR) -> NetlistModel:
    """Derive a pin-level NetlistModel from IR via the geometry engine."""
    conn = SchematicConnectivity()
    for i, w in enumerate(ir.wires):
        conn.add_wire(i, w.points, w.net)
    for lb in ir.labels:
        conn.add_label(lb.x, lb.y, lb.text, wire_id=lb.wire_idx)
    for pp in ir.power_ports:
        conn.add_pin(PinPoint(owner=f"PWR:{pp.net}@{len(conn._pins)}", pin="1",
                              x=pp.x, y=pp.y),
                     net_name=pp.net)
    model = NetlistModel(source=f"ir:{ir.source}")
    for comp in ir.components:
        model.components[comp.ref] = SchComponent(
            ref=comp.ref, value=comp.value, footprint=comp.footprint,
            device=comp.device, description=comp.description,
        )
        for p in comp.pins:
            hx, hy = pin_abs(comp, p)
            conn.add_pin(PinPoint(owner=comp.ref, pin=p.number, x=hx, y=hy))

    groups = conn.resolve()
    synth = 0
    for g in groups:
        named = sorted(n for n in g.names if n)
        if named:
            net = named[0]
        else:
            real = [p for p in g.pins if not p.owner.startswith("PWR:")]
            if not real:
                continue
            anchor = min((p.owner, p.pin) for p in real)
            net = f"~Net{anchor[0]}_{anchor[1]}"
            synth += 1
        for p in g.pins:
            if not p.owner.startswith("PWR:"):
                model.pin_nets[(p.owner, p.pin)] = net
    model.notes.append(f"ir-derived unnamed nets synthesized: {synth}")
    return model


def load_netlist(path: str | Path) -> NetlistModel:
    """Parse any supported file into a NetlistModel (for `verify`)."""
    path = Path(path)
    suf = path.suffix.lower()
    if suf == ".eprj":
        return parse_eprj(path)
    if suf == ".schdoc":
        with open(path, "rb") as fh:
            head = fh.read(16)
        if head.startswith(b"|HEADER"):
            return parse_schdoc_ascii(path)
        return parse_schdoc(path)
    if suf == ".pcbdoc":
        from migraeda.pcbdoc import parse_pcbdoc

        with open(path, "rb") as fh:
            head = fh.read(16)
        if head.startswith(b"|RECORD"):
            from migraeda.pcbascii import parse_pcb_ascii

            nl = parse_pcb_ascii(path)
        else:
            nl = parse_pcbdoc(path)
        m = NetlistModel(source=f"pcbdoc:{path.name}")
        seen: set[str] = set()
        for c in nl.components:
            if c.designator and c.designator not in seen:
                seen.add(c.designator)
                m.components[c.designator] = SchComponent(
                    ref=c.designator, value=c.lib_reference, footprint=c.pattern
                )
        for (ref, pin), nets in nl.pin_net_sets().items():
            m.pin_nets[(ref, pin)] = "|".join(sorted(nets))
        return m
    raise ValueError(f"unsupported input format: {path.suffix}")


@dataclass
class ConvertResult:
    output: Path
    direction: str
    src_components: int
    src_wires: int
    out_path: Path
    verify: LvsResult | None = None
    notes: list[str] = field(default_factory=list)


def load_library(path: str | Path):
    """Load a library from .eprj / .SchLib / .PcbLib / .PcbDoc (embedded)."""
    from migraeda.eprj_lib import extract_eprj_library
    from migraeda.libmodel import LibFootprint, LibPad, Library
    from migraeda.pcblib import parse_pcblib
    from migraeda.pcbdoc import parse_pcbdoc
    from migraeda.schlib import parse_schlib

    path = Path(path)
    suf = path.suffix.lower()
    if suf == ".eprj":
        return extract_eprj_library(path)
    if suf == ".pcblib":
        return parse_pcblib(path)
    if suf == ".schlib":
        return parse_schlib(path)
    if suf == ".pcbdoc":
        with open(path, "rb") as fh:
            head = fh.read(16)
        if head.startswith(b"|RECORD"):
            from migraeda.pcbascii import parse_pcb_ascii

            nl = parse_pcb_ascii(path)
        else:
            nl = parse_pcbdoc(path)
        lib = Library(source=f"pcbdoc-embedded:{path.name}")
        for pattern, pads in nl.footprint_map().items():
            lib.footprints[pattern] = LibFootprint(
                name=pattern,
                pads=[
                    LibPad(number=p.name, x=p.x_mil, y=p.y_mil,
                           size_x=p.size_x_mil, size_y=p.size_y_mil,
                           hole=p.hole_mil, layer=str(p.layer))
                    for p in pads
                ],
            )
        return lib
    raise ValueError(f"unsupported library source: {path.suffix}")


@dataclass
class LibConvertResult:
    output: Path
    symbols: int
    footprints: int
    verify_grade: str = ""
    verify_details: str = ""


@dataclass
class PcbConvertResult:
    output: Path
    components: int
    pads: int
    tracks: int
    vias: int
    verify_grade: str = ""
    verify_details: str = ""

    @property
    def out_path(self) -> Path:
        return self.output


@dataclass
class RoundtripResult:
    direction: str
    intermediate: Path  # first-leg output (kept)
    final: Path  # round-tripped output (kept)
    leg1_verify: str
    final_common_pins: int
    final_mismatches: int
    nets_matched: int
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.final_mismatches == 0


def roundtrip(src: str | Path, out_dir: str | Path | None = None) -> RoundtripResult:
    """Full round trip: src -> target format -> back to source format,
    then LVS-compare the round-tripped file against the ORIGINAL file.

    Both intermediate and final artifacts are written to out_dir for
    inspection.
    """
    from migraeda.adascii import parse_schdoc_ascii, write_schdoc_ascii
    from migraeda.eprj_sqlite import parse_eprj, parse_eprj_ir
    from migraeda.eprj_write import write_eprj
    from migraeda.schdoc import parse_schdoc

    src = Path(src)
    suf = src.suffix.lower()
    out_dir = Path(out_dir) if out_dir else src.parent / "out" / "roundtrip"
    out_dir.mkdir(parents=True, exist_ok=True)

    if suf == ".eprj":
        # eprj -> SchDoc(ascii) -> eprj
        ir1 = parse_eprj_ir(src)
        intermediate = write_schdoc_ascii(ir1, out_dir / (src.stem + ".fwd.SchDoc"))
        m1 = netlist_from_ir(ir1)
        m2 = parse_schdoc_ascii(intermediate)
        v1 = compare_netlists(m1, m2)
        ir2 = load_ir(intermediate)
        final = write_eprj(ir2, out_dir / (src.stem + ".roundtrip.eprj"))
        back = parse_eprj(final)
        orig = parse_eprj(src)
        res = compare_netlists(orig, back)
        return RoundtripResult(
            direction="eprj -> ad -> eprj",
            intermediate=intermediate,
            final=final,
            leg1_verify=f"{len(v1.pin_mismatches)} mismatch / {v1.common_pin_count} pins",
            final_common_pins=res.common_pin_count,
            final_mismatches=len(res.pin_mismatches),
            nets_matched=len(res.matches),
            notes=[*(f"leg1: {n}" for n in ir1.notes), *(f"back: {n}" for n in back.notes)],
        )
    if suf == ".schdoc":
        # SchDoc -> eprj -> SchDoc(ascii)
        ir1 = load_ir(src)
        intermediate = write_eprj(ir1, out_dir / (src.stem + ".fwd.eprj"))
        m1 = netlist_from_ir(ir1)
        m2 = parse_eprj(intermediate)
        v1 = compare_netlists(m1, m2)
        ir2 = parse_eprj_ir(intermediate)
        final = write_schdoc_ascii(ir2, out_dir / (src.stem + ".roundtrip.SchDoc"))
        back = parse_schdoc_ascii(final)
        orig = parse_schdoc(src)
        res = compare_netlists(orig, back)
        return RoundtripResult(
            direction="schdoc -> eprj -> schdoc",
            intermediate=intermediate,
            final=final,
            leg1_verify=f"{len(v1.pin_mismatches)} mismatch / {v1.common_pin_count} pins",
            final_common_pins=res.common_pin_count,
            final_mismatches=len(res.pin_mismatches),
            nets_matched=len(res.matches),
            notes=[*(f"leg1: {n}" for n in ir1.notes), *(f"back: {n}" for n in back.notes)],
        )
    raise ValueError(f"roundtrip supports .eprj / .SchDoc, got {src.suffix}")


@dataclass
class PcbRoundtripResult:
    leg1: Path
    final: Path
    leg1_grade: str
    final_grade: str
    final_details: str

    @property
    def ok(self) -> bool:
        return self.final_grade == "PASS"


def eprj_has_pcb(src: str | Path) -> bool:
    import sqlite3

    try:
        con = sqlite3.connect(str(src))
        try:
            row = con.execute(
                "SELECT LENGTH(dataStr) FROM documents WHERE docType=3"
                " ORDER BY LENGTH(dataStr) DESC LIMIT 1"
            ).fetchone()
            return bool(row and row[0] > 1000)
        finally:
            con.close()
    except sqlite3.Error:
        return False


def roundtrip_pcb(src: str | Path, out_dir: str | Path | None = None) -> PcbRoundtripResult:
    """PCB round trip: eprj(PCB) -> ASCII PcbDoc -> eprj(PCB), then
    pcbdiff the round-tripped PCB against the ORIGINAL one."""
    import json
    import sqlite3

    from migraeda.epcb import parse_epcb
    from migraeda.eprj_lib import _parse_footprint
    from migraeda.eprj_pcb_write import write_eprj_pcb
    from migraeda.pcbascii import parse_pcb_ascii, write_pcb_ascii
    from migraeda.pcbdiff import compare_pcb

    src = Path(src)
    out_dir = Path(out_dir) if out_dir else src.parent / "out" / "roundtrip"
    out_dir.mkdir(parents=True, exist_ok=True)

    # carry-over metadata: footprint library + designator->uuids
    con = sqlite3.connect(str(src))
    try:
        footprints = {}
        fp_uuid_by_pattern: dict[str, str] = {}
        for fu, title, data in con.execute(
            "SELECT uuid, display_title, dataStr FROM components WHERE docType=4"
        ):
            footprints[fu] = _parse_footprint(data, title)
            fp_uuid_by_pattern[title] = fu
        pcb_docs = [
            r[0]
            for r in con.execute(
                "SELECT dataStr FROM documents WHERE docType=3 AND LENGTH(dataStr) > 1000"
            )
        ]
        comp_attrs: dict[str, dict[str, str]] = {}
        for data in pcb_docs:
            for line in data.splitlines():
                line = line.strip()
                if not line.startswith("["):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec[0] == "ATTR" and len(rec) >= 9:
                    comp_attrs.setdefault(str(rec[3]), {})[str(rec[7])] = str(rec[8])
    finally:
        con.close()
    dev_uuid_by_ref = {
        ca["Designator"]: ca.get("Device", "")
        for ca in comp_attrs.values()
        if "Designator" in ca
    }

    # leg 1: eprj -> ascii PcbDoc
    nl = parse_epcb(src)
    leg1 = write_pcb_ascii(nl, out_dir / (src.stem + ".fwd.PcbDoc"))
    back1 = parse_pcb_ascii(leg1)
    v1 = compare_pcb(nl, back1, pos_tol_mil=1.0)

    # leg 2: ascii PcbDoc -> eprj with PCB
    final = write_eprj_pcb(
        back1, out_dir / (src.stem + ".roundtrip.eprj"),
        footprints=footprints, fp_uuid_by_pattern=fp_uuid_by_pattern,
        dev_uuid_by_ref=dev_uuid_by_ref, project_name=src.stem,
    )

    # final compare: round-tripped pcb vs ORIGINAL pcb
    nl_rt = parse_epcb(final)
    res = compare_pcb(nl, nl_rt, pos_tol_mil=1.0)
    return PcbRoundtripResult(
        leg1=leg1,
        final=final,
        leg1_grade=v1.grade,
        final_grade=res.grade,
        final_details=(
            f"comps {res.comps_common}/{len(nl.components)}, "
            f"pads {res.pads_checked} checked/{len(res.pads_moved)} moved, "
            f"vias {res.vias_a} vs {res.vias_b}, copper diffs {len(res.copper_diffs)}"
        ),
    )


def convert_pcb(src: str | Path, out_dir: str | Path | None = None,
                verify: bool = True) -> PcbConvertResult:
    """Convert the PCB document inside an .eprj into an ASCII .PcbDoc,
    with pcbdiff loop verification against the source."""
    from migraeda.epcb import parse_epcb
    from migraeda.pcbascii import parse_pcb_ascii, write_pcb_ascii
    from migraeda.pcbdiff import compare_pcb

    src = Path(src)
    if src.suffix.lower() != ".eprj":
        raise ValueError(f"PCB conversion currently supports .eprj input, got {src.suffix}")
    nl = parse_epcb(src)
    out_dir = Path(out_dir) if out_dir else src.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (src.stem + ".PcbDoc")
    write_pcb_ascii(nl, out)

    res = PcbConvertResult(
        output=out,
        components=len(nl.components),
        pads=len(nl.pads),
        tracks=len(nl.tracks),
        vias=len(nl.vias),
    )
    if verify:
        back = parse_pcb_ascii(out)
        diff = compare_pcb(nl, back, pos_tol_mil=1.0)
        res.verify_grade = diff.grade
        res.verify_details = (
            f"comps {diff.comps_common}/{len(nl.components)}, "
            f"pads {diff.pads_checked} checked/{len(diff.pads_moved)} moved, "
            f"copper diffs {len(diff.copper_diffs)}"
        )
    return res


def libconvert(src: str | Path, out_dir: str | Path | None = None,
               verify: bool = True) -> LibConvertResult:
    """Convert a library source into an .eprj library package (+loop verify)."""
    from migraeda.eprj_lib import extract_eprj_library
    from migraeda.eprj_write import write_library_eprj
    from migraeda.libdiff import compare_libraries

    src = Path(src)
    lib = load_library(src)
    out_dir = Path(out_dir) if out_dir else src.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (src.stem + ".eprj")
    write_library_eprj(lib, out, project_name=src.stem)

    res = LibConvertResult(
        output=out, symbols=len(lib.symbols), footprints=len(lib.footprints)
    )
    if verify:
        back = extract_eprj_library(out)
        diff = compare_libraries(lib, back, pos_tol=0.6)
        res.verify_grade = diff.grade
        res.verify_details = (
            f"symbols {diff.symbols_common} common/{len(diff.symbol_diffs)} diff, "
            f"footprints {diff.fps_common} common/{len(diff.fp_diffs)} diff"
        )
    return res


def convert(src: str | Path, to: str, out_dir: str | Path | None = None,
            verify: bool = True) -> ConvertResult:
    """Convert a schematic between .eprj and .SchDoc, with loop verification.

    to: "ad"   (produce ASCII .SchDoc from .eprj)
        "eprj" (produce .eprj from binary .SchDoc)
    """
    src = Path(src)
    ir = load_ir(src)
    out_dir = Path(out_dir) if out_dir else src.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if to == "ad":
        out = out_dir / (src.stem + ".SchDoc")
        write_schdoc_ascii(ir, out)
        direction = "eprj -> ad-ascii-schdoc"
        reparsed: NetlistModel = parse_schdoc_ascii(out)
    elif to == "adpcb":
        return convert_pcb(src, out_dir=out_dir, verify=verify)
    elif to == "eprj":
        out = out_dir / (src.stem + ".eprj")
        write_eprj(ir, out)
        direction = "schdoc -> eprj"
        reparsed = parse_eprj(out)
    else:
        raise ValueError(f"unknown target format: {to!r} (use 'ad'/'adpcb'/'eprj')")

    res = ConvertResult(
        output=out,
        direction=direction,
        src_components=len(ir.components),
        src_wires=len(ir.wires),
        out_path=out,
        notes=list(ir.notes),
    )
    if verify:
        res.verify = compare_netlists(netlist_from_ir(ir), reparsed)
    return res
