"""Library-level diff: symbol pin maps + footprint pad maps + bindings."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from migraeda.libmodel import Library


@dataclass
class SymbolDiff:
    name: str
    issues: list[str] = field(default_factory=list)


@dataclass
class FootprintDiff:
    name: str
    issues: list[str] = field(default_factory=list)


@dataclass
class LibDiffResult:
    symbols_common: int = 0
    symbols_only_a: list[str] = field(default_factory=list)
    symbols_only_b: list[str] = field(default_factory=list)
    symbol_diffs: list[SymbolDiff] = field(default_factory=list)
    fps_common: int = 0
    fps_only_a: list[str] = field(default_factory=list)
    fps_only_b: list[str] = field(default_factory=list)
    fp_diffs: list[FootprintDiff] = field(default_factory=list)
    scale_suspect: str = ""

    @property
    def grade(self) -> str:
        if self.symbol_diffs or self.fp_diffs:
            return "FAIL"
        if self.symbols_only_a or self.symbols_only_b or self.fps_only_a or self.fps_only_b:
            return "WARN"
        return "PASS"


def _numkey(n: str):
    try:
        return (0, int(n))
    except ValueError:
        return (1, n)


def compare_libraries(a: Library, b: Library, pos_tol: float = 1.0) -> LibDiffResult:
    res = LibDiffResult()

    # ---- symbols
    for name in sorted(set(a.symbols) & set(b.symbols)):
        res.symbols_common += 1
        sa, sb = a.symbols[name], b.symbols[name]
        d = SymbolDiff(name=name)
        pa = {p.number: p for p in sa.pins}
        pb = {p.number: p for p in sb.pins}
        if set(pa) != set(pb):
            d.issues.append(
                f"pin numbers differ: A={sorted(pa, key=_numkey)} B={sorted(pb, key=_numkey)}"
            )
        for num in sorted(set(pa) & set(pb), key=_numkey):
            xa, ya, xb, yb = pa[num].x, pa[num].y, pb[num].x, pb[num].y
            dist = math.hypot(xa - xb, ya - yb)
            if dist > pos_tol:
                d.issues.append(
                    f"pin {num} position: A({xa:.1f},{ya:.1f}) B({xb:.1f},{yb:.1f}) Δ={dist:.1f}"
                )
            if pa[num].name and pb[num].name and pa[num].name != pb[num].name:
                d.issues.append(f"pin {num} name: {pa[num].name!r} vs {pb[num].name!r}")
        if d.issues:
            res.symbol_diffs.append(d)
    res.symbols_only_a = sorted(set(a.symbols) - set(b.symbols))
    res.symbols_only_b = sorted(set(b.symbols) - set(a.symbols))

    # ---- footprints
    for name in sorted(set(a.footprints) & set(b.footprints)):
        res.fps_common += 1
        fa, fb = a.footprints[name], b.footprints[name]
        d = FootprintDiff(name=name)
        pa = {p.number: p for p in fa.pads}
        pb = {p.number: p for p in fb.pads}
        if set(pa) != set(pb):
            d.issues.append(
                f"pad numbers differ: A={sorted(pa, key=_numkey)} B={sorted(pb, key=_numkey)}"
            )
        for num in sorted(set(pa) & set(pb), key=_numkey):
            dist = math.hypot(pa[num].x - pb[num].x, pa[num].y - pb[num].y)
            if dist > pos_tol:
                d.issues.append(
                    f"pad {num} position: A({pa[num].x:.1f},{pa[num].y:.1f}) "
                    f"B({pb[num].x:.1f},{pb[num].y:.1f}) Δ={dist:.1f}"
                )
            if pa[num].size_x and pb[num].size_x:
                ds = abs(pa[num].size_x - pb[num].size_x) + abs(pa[num].size_y - pb[num].size_y)
                if ds > pos_tol:
                    d.issues.append(
                        f"pad {num} size: A({pa[num].size_x:.1f}x{pa[num].size_y:.1f}) "
                        f"B({pb[num].size_x:.1f}x{pb[num].size_y:.1f})"
                    )
            if pa[num].hole and pb[num].hole and abs(pa[num].hole - pb[num].hole) > pos_tol:
                d.issues.append(f"pad {num} hole: A{pa[num].hole:.1f} vs B{pb[num].hole:.1f}")
        if d.issues:
            res.fp_diffs.append(d)
    res.fps_only_a = sorted(set(a.footprints) - set(b.footprints))
    res.fps_only_b = sorted(set(b.footprints) - set(a.footprints))

    # ---- scale sanity: if many matched pins/pads differ by a constant ratio
    ratios: list[float] = []
    for name in set(a.footprints) & set(b.footprints):
        pa = {p.number: p for p in a.footprints[name].pads}
        pb = {p.number: p for p in b.footprints[name].pads}
        for num in set(pa) & set(pb):
            ra = math.hypot(pa[num].x, pa[num].y)
            rb = math.hypot(pb[num].x, pb[num].y)
            if ra > 1 and rb > 1:
                ratios.append(ra / rb)
    if len(ratios) >= 3:
        ratios.sort()
        med = ratios[len(ratios) // 2]
        if abs(med - 1.0) > 0.05:
            res.scale_suspect = (
                f"matched pad positions differ by ~{med:.3f}x median ratio "
                f"(possible unit/origin mismatch)"
            )
    return res


def render_libdiff_report(res: LibDiffResult, name_a: str, name_b: str) -> str:
    L: list[str] = []
    w = L.append
    w("# 库级验证报告")
    w("")
    w(f"| A | `{name_a}` |")
    w(f"|---|---|")
    w(f"| B | `{name_b}` |")
    w("")
    w(f"## 总体结论：**{res.grade}**")
    w("")
    w(f"- 符号：公共 {res.symbols_common}（差异 {len(res.symbol_diffs)}），"
      f"A 独有 {len(res.symbols_only_a)}，B 独有 {len(res.symbols_only_b)}")
    w(f"- 封装：公共 {res.fps_common}（差异 {len(res.fp_diffs)}），"
      f"A 独有 {len(res.fps_only_a)}，B 独有 {len(res.fps_only_b)}")
    if res.scale_suspect:
        w(f"- ⚠️ {res.scale_suspect}")
    w("")
    for title, diffs in (("符号差异", res.symbol_diffs), ("封装差异", res.fp_diffs)):
        if diffs:
            w(f"### {title}")
            w("")
            for d in diffs:
                w(f"- **{d.name}**")
                for i in d.issues:
                    w(f"  - {i}")
            w("")
    for title, items in (("A 独有符号", res.symbols_only_a), ("B 独有符号", res.symbols_only_b),
                         ("A 独有封装", res.fps_only_a), ("B 独有封装", res.fps_only_b)):
        if items:
            w(f"### {title}（{len(items)}）")
            w("")
            w(", ".join(f"`{x}`" for x in items[:80]))
            w("")
    return "\n".join(L)
