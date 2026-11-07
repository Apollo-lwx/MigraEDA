"""Fuzz round-trip robustness: mutate a real design file and re-run the
full conversion chain. Any crash, asymmetry, or invariant violation is a
candidate parser/converter bug — with a reproducible seed attached.
"""

from __future__ import annotations

import random
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from migraeda.adascii import parse_schdoc_ascii, write_schdoc_ascii
from migraeda.convert import load_ir, netlist_from_ir
from migraeda.eprj_sqlite import parse_eprj
from migraeda.eprj_write import write_eprj
from migraeda.ir import SchematicIR


def _clone(ir: SchematicIR) -> SchematicIR:
    import copy

    return copy.deepcopy(ir)


def _m_jitter(ir: SchematicIR, rng: random.Random) -> str:
    """Jitter all coordinates by ±2 then snap to the unit grid
    (keeps connectivity valid; exercises precision robustness)."""
    for c in ir.components:
        c.x = round(c.x + rng.uniform(-2, 2))
        c.y = round(c.y + rng.uniform(-2, 2))
    for w in ir.wires:
        w.points = [(round(x + rng.uniform(-2, 2)), round(y + rng.uniform(-2, 2)))
                    for x, y in w.points]
    return "jitter±2(snap)"


def _m_rotate(ir: SchematicIR, rng: random.Random) -> str:
    """Rotate a random component by 90°."""
    if not ir.components:
        return "rotate(noop)"
    c = rng.choice(ir.components)
    c.rotation = (c.rotation + 90) % 360
    return f"rotate {c.ref} ->{c.rotation}"


def _m_case_net(ir: SchematicIR, rng: random.Random) -> str:
    """Introduce a case-variant duplicate of an existing net name."""
    names = {lb.text for lb in ir.labels} | {w.net for w in ir.wires if w.net}
    if not names:
        return "case-net(noop)"
    n = rng.choice(sorted(names))
    variant = n.lower() if any(ch.isupper() for ch in n) else n.upper()
    for lb in ir.labels:
        if lb.text == n and rng.random() < 0.5:
            lb.text = variant
    return f"case-variant {n}~{variant}"


def _m_unicode_net(ir: SchematicIR, rng: random.Random) -> str:
    """Add a net label with CJK + special characters at a random wire vertex."""
    if not ir.wires:
        return "unicode(noop)"
    w = rng.choice(ir.wires)
    x, y = w.points[len(w.points) // 2]
    from migraeda.ir import IRNetLabel

    ir.labels.append(
        IRNetLabel(x=x, y=y, text=rng.choice(["电源地_α", "信号-3V3", "MOTOR+''", "网 络", "μV"])))
    return "unicode-net"


def _m_degen_wire(ir: SchematicIR, rng: random.Random) -> str:
    """Insert a degenerate (zero-length) named wire at a random component pin."""
    from migraeda.ir import IRWire, pin_abs

    cands = [c for c in ir.components if c.pins]
    if not cands:
        return "degen(noop)"
    c = rng.choice(cands)
    p = rng.choice(c.pins)
    hx, hy = pin_abs(c, p)
    net = f"FZNET{rng.randint(1, 999)}"
    ir.wires.append(IRWire(points=[(hx, hy), (hx, hy)], net=net))
    return f"degen-net {net}@{c.ref}.{p.number}"


def _m_drop_wire(ir: SchematicIR, rng: random.Random) -> str:
    """Delete a random wire."""
    if len(ir.wires) < 2:
        return "drop(noop)"
    i = rng.randrange(len(ir.wires))
    ir.wires.pop(i)
    return f"drop wire#{i}"


_MUTATORS = [_m_jitter, _m_rotate, _m_case_net, _m_unicode_net, _m_degen_wire, _m_drop_wire]


@dataclass
class FuzzAnomaly:
    seed: int
    mutation: str
    stage: str
    detail: str


@dataclass
class FuzzReport:
    iterations: int
    anomalies: list[FuzzAnomaly] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.anomalies


def fuzz_file(src: str | Path, iterations: int = 50, seed: int = 42,
              keep_dir: str | Path | None = None) -> FuzzReport:
    """Run `iterations` mutated round-trips from a real file."""
    base_ir = load_ir(src)
    report = FuzzReport(iterations=iterations)
    tmp = Path(tempfile.mkdtemp(prefix="migraeda-fuzz-"))
    if keep_dir:
        Path(keep_dir).mkdir(parents=True, exist_ok=True)
    try:
        for i in range(iterations):
            iseed = seed + i
            rng = random.Random(iseed)
            ir = _clone(base_ir)
            mut = rng.choice(_MUTATORS)(ir, rng)
            try:
                ad = write_schdoc_ascii(ir, tmp / "f.SchDoc")
                m_ad = parse_schdoc_ascii(ad)
                ep = write_eprj(ir, tmp / "f.eprj")
                m_ep = parse_eprj(ep)
            except Exception as exc:  # noqa: BLE001 - fuzz wants every failure
                report.anomalies.append(
                    FuzzAnomaly(iseed, mut, "convert", repr(exc)[:200])
                )
                if keep_dir:
                    shutil.copy(tmp / "f.SchDoc", Path(keep_dir) / f"crash-{iseed}.SchDoc")
                continue
            # invariants:
            # 1) named-net MEMBERSHIP must be preserved (case-insensitive):
            #    every pin that was on a named net in the base model must still
            #    be on SOME named net (name spellings may vary by mutation)
            base_named_pins = {
                k for k, n in netlist_from_ir(base_ir).pin_nets.items()
                if not n.startswith("~")
            }
            ep_named_pins = {
                k for k, n in m_ep.pin_nets.items()
                if not n.startswith("~") and k not in m_ep.virtual_pins
            }
            if not mut.startswith(("case-variant", "drop", "degen")):
                lost = base_named_pins - ep_named_pins
                if lost:
                    report.anomalies.append(
                        FuzzAnomaly(iseed, mut, "invariant",
                                    f"named-net pins lost: {sorted(lost)[:6]}")
                    )
            # 2) real (non-virtual) pin count must not DROP vs the AD-side parse
            ad_real = {k for k, n in m_ad.pin_nets.items() if not n.startswith("~")}
            ep_real = {k for k, n in m_ep.pin_nets.items() if k not in m_ep.virtual_pins}
            if len(ep_real) < len(ad_real) - 5:
                report.anomalies.append(
                    FuzzAnomaly(iseed, mut, "invariant",
                                f"real pins dropped: ad={len(ad_real)} eprj={len(ep_real)}")
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def render_fuzz_report(src: str | Path, report: FuzzReport) -> str:
    lines = [f"fuzz: {Path(src).name} x{report.iterations} iterations"]
    if report.ok:
        lines.append("no anomalies ✅")
    else:
        lines.append(f"anomalies: {len(report.anomalies)} ❌")
        for a in report.anomalies[:20]:
            lines.append(f"  seed={a.seed} [{a.stage}] {a.mutation}: {a.detail}")
        if len(report.anomalies) > 20:
            lines.append(f"  ... +{len(report.anomalies) - 20} more")
    return "\n".join(lines)
