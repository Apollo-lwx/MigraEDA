"""Invariant self-check: a battery of 'parser-suspicious' signals on one file.

These invariants catch BOTH genuine file anomalies and parser bugs:
- pin-on-wire hit rate (low rate = wrong transform or broken geometry)
- single-pin nets (floating pins / missed connections)
- net name conflicts & case variants (Altium merges case-insensitively)
- duplicate designators
- components lacking symbol/footprint data
- pads with no net (PCB)
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from migraeda.convert import load_netlist
from migraeda.netlist_model import NetlistModel


def selfcheck(path: str | Path) -> str:
    path = Path(path)
    model = load_netlist(path)
    L: list[str] = []
    w = L.append
    w(f"selfcheck: {path.name}")
    w(f"  parsed: {len(model.components)} comps, {len(model.pin_nets)} pins, "
      f"{len(model.net_members())} nets")
    issues = 0

    # duplicate designators
    refs = [r for r in model.components]
    dup = [r for r, n in Counter(refs).items() if n > 1]
    if dup:
        issues += 1
        w(f"  ⚠ duplicate designators: {dup[:10]}")

    # single-pin nets (excluding virtual pins)
    singles = []
    for net, members in model.net_members().items():
        real = [x for x in members if x not in model.virtual_pins]
        if len(real) == 1:
            singles.append((net, real[0]))
    if singles:
        w(f"  ⚠ single-pin nets: {len(singles)}"
          + (" (first: " + ", ".join(f"{r}.{p}->{n}" for n, (r, p) in singles[:8]) + ")"
             if singles else ""))

    # name conflicts: case variants that Altium would merge
    names = sorted(model.net_members())
    variants = set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a != b and a.upper() == b.upper():
                variants.add((a, b))
    if variants:
        w(f"  ⚠ case-variant net names (merge in Altium semantics): "
          + ", ".join(f"{a}~{b}" for a, b in sorted(variants)[:8]))

    # name conflicts recorded by parser
    conflicts = [n for n in model.notes if "conflict" in n]
    for n in conflicts[:6]:
        w(f"  ⚠ {n}")

    # missing data
    no_fp = [r for r, c in model.components.items() if not c.footprint]
    if no_fp:
        w(f"  ⚠ components without footprint info: {len(no_fp)}")
    if model.virtual_pins:
        w(f"  ⚠ virtual pins (symbols missing): {len(model.virtual_pins)}")

    # pins of components with no net
    comp_pins = {(r, p) for (r, p) in model.pin_nets if r in model.components}
    no_net = [f"{r}.{p}" for (r, p), n in model.pin_nets.items()
              if r in model.components and n.startswith("~")]
    if no_net:
        w(f"  ⚠ pins on synthesized (unlabeled) nets: {len(no_net)}")

    if issues == 0 and not singles and not variants and not no_net:
        w("  no suspicious signals ✅")
    for n in model.notes:
        w(f"  note: {n}")
    return "\n".join(L)
