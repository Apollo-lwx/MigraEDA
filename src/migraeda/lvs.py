"""LVS-style comparison of two pin-level netlists.

Net correspondence is established by:
1. exact name match (case-insensitive) for named nets;
2. greedy structural match by shared member-pin count (for auto-named
   and renamed nets).

Then every common (ref, pin) is checked for net agreement under that
correspondence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from migraeda.netlist_model import NetlistModel

_SYNTH_PREFIX = "~"


def norm_ref(ref: str) -> str:
    return re.sub(r"\s+", "", ref).upper()


def norm_net(name: str) -> str:
    # '~' marks synthesized names; '~NetR1_2' and 'NetR1_2' anchor identically
    return re.sub(r"\s+", "", name.lstrip("~")).upper()


@dataclass
class NetMatch:
    a_net: str
    b_net: str
    shared_pins: int
    a_size: int
    b_size: int
    by_name: bool = False


@dataclass
class PinMismatch:
    ref: str
    pin: str
    a_net: str
    b_net: str


@dataclass
class LvsResult:
    a_name: str
    b_name: str
    matches: list[NetMatch] = field(default_factory=list)
    a_only_nets: list[str] = field(default_factory=list)
    b_only_nets: list[str] = field(default_factory=list)
    pin_mismatches: list[PinMismatch] = field(default_factory=list)
    common_pin_count: int = 0
    a_only_pins: list[tuple[str, str]] = field(default_factory=list)
    b_only_pins: list[tuple[str, str]] = field(default_factory=list)
    a_only_refs: list[str] = field(default_factory=list)
    b_only_refs: list[str] = field(default_factory=list)

    @property
    def matched_pin_count(self) -> int:
        return self.common_pin_count - len(self.pin_mismatches)


def _norm_pinmap(model: NetlistModel, skip_virtual: bool) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for (ref, pin), net in model.pin_nets.items():
        if skip_virtual and (ref, pin) in model.virtual_pins:
            continue
        out[(norm_ref(ref), pin)] = net
    return out


def compare_netlists(a: NetlistModel, b: NetlistModel) -> LvsResult:
    res = LvsResult(a_name=a.source, b_name=b.source)
    ap = _norm_pinmap(a, skip_virtual=True)
    bp = _norm_pinmap(b, skip_virtual=True)

    a_refs = {norm_ref(r) for r in a.components}
    b_refs = {norm_ref(r) for r in b.components}
    res.a_only_refs = sorted(a_refs - b_refs)
    res.b_only_refs = sorted(b_refs - a_refs)

    common = sorted(set(ap) & set(bp))
    res.common_pin_count = len(common)
    res.a_only_pins = sorted(set(ap) - set(bp))
    res.b_only_pins = sorted(set(bp) - set(ap))

    # net membership over common pins
    def members(pm: dict[tuple[str, str], str]) -> dict[str, set[tuple[str, str]]]:
        out: dict[str, set[tuple[str, str]]] = {}
        for k, net in pm.items():
            out.setdefault(net, set()).add(k)
        return out

    am = members(ap)
    bm = members(bp)

    # 1. name-seeded matching (skip tool-auto-named nets like ~NetX / $1Nx /
    # NetX_auto patterns — those are matched structurally below)
    def _auto(net: str) -> bool:
        return net.startswith(_SYNTH_PREFIX) or net.startswith("$")

    matched_a: set[str] = set()
    matched_b: set[str] = set()
    b_by_norm = {}
    for net in bm:
        b_by_norm.setdefault(norm_net(net), []).append(net)

    for net_a in sorted(am):
        if _auto(net_a):
            continue
        cands = b_by_norm.get(norm_net(net_a), [])
        unnamed = [c for c in cands if c not in matched_b]
        if unnamed:
            net_b = unnamed[0]
            shared = len(am[net_a] & bm[net_b])
            res.matches.append(
                NetMatch(net_a, net_b, shared, len(am[net_a]), len(bm[net_b]), by_name=True)
            )
            matched_a.add(net_a)
            matched_b.add(net_b)

    # 2. structural greedy matching on the remainder
    pairs: list[tuple[int, str, str]] = []
    for net_a, mem_a in am.items():
        if net_a in matched_a:
            continue
        for net_b, mem_b in bm.items():
            if net_b in matched_b:
                continue
            shared = len(mem_a & mem_b)
            if shared:
                pairs.append((shared, net_a, net_b))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    for shared, net_a, net_b in pairs:
        if net_a in matched_a or net_b in matched_b:
            continue
        res.matches.append(
            NetMatch(net_a, net_b, shared, len(am[net_a]), len(bm[net_b]), by_name=False)
        )
        matched_a.add(net_a)
        matched_b.add(net_b)

    res.a_only_nets = sorted(n for n in am if n not in matched_a)
    res.b_only_nets = sorted(n for n in bm if n not in matched_b)

    # 3. pin-level agreement under the correspondence
    a2b: dict[str, str] = {m.a_net: m.b_net for m in res.matches}
    for key in common:
        na, nb = ap[key], bp[key]
        if na == nb:
            continue
        if a2b.get(na) == nb:
            continue
        ref, pin = key
        res.pin_mismatches.append(PinMismatch(ref=ref, pin=pin, a_net=na, b_net=nb))
    return res
