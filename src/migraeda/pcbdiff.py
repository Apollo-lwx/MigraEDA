"""PCB-level equivalence diff between two .PcbDoc files.

Compares what "same layout" means: board outline, component placement,
pad positions, vias, and per-net copper statistics (tracks/arcs/fills/pours
on copper layers only — silkscreen and mechanical primitives excluded).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from migraeda.pcbdoc import PcbNetlist

_COPPER_MAX_LAYER = 32  # v6 layers 1..32 are copper; 33/34 overlay, >32 misc
_PANEL_TOL_MIL = 5.0  # panelization etc. tolerated below this


@dataclass
class NetCopper:
    track_count: int = 0
    track_len_mil: float = 0.0
    arc_count: int = 0
    fill_count: int = 0
    polygon_count: int = 0
    via_count: int = 0


@dataclass
class PcbDiffResult:
    outline_ok: bool = True
    outline_a: tuple[float, float] = (0.0, 0.0)  # w, h in mil
    outline_b: tuple[float, float] = (0.0, 0.0)
    alignment: str = ""  # how positions were aligned before comparing
    comps_common: int = 0
    comps_moved: list[str] = field(default_factory=list)
    comps_only_a: list[str] = field(default_factory=list)
    comps_only_b: list[str] = field(default_factory=list)
    pads_checked: int = 0
    pads_moved: list[str] = field(default_factory=list)
    vias_a: int = 0
    vias_b: int = 0
    vias_unmatched: list[tuple[float, float]] = field(default_factory=list)
    copper_diffs: list[str] = field(default_factory=list)
    nets_only_a: list[str] = field(default_factory=list)
    nets_only_b: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if (self.comps_only_a or self.comps_only_b or self.comps_moved
                or self.pads_moved or self.vias_unmatched or not self.outline_ok):
            return "FAIL"
        if self.copper_diffs or self.vias_a != self.vias_b:
            return "WARN"
        return "PASS"


def _bbox(outline: list[tuple[float, float]]) -> tuple[float, float]:
    if not outline:
        return (0.0, 0.0)
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    return (max(xs) - min(xs), max(ys) - min(ys))


def copper_stats(nl: PcbNetlist) -> dict[str, NetCopper]:
    """Per-net copper statistics on copper layers (v6 layer <= 32)."""
    stats: dict[str, NetCopper] = {}

    def net_name(idx: int) -> str:
        return nl.nets[idx] if 0 <= idx < len(nl.nets) else "?"

    for t in nl.tracks:
        if t.net_index < 0 or t.layer > _COPPER_MAX_LAYER:
            continue
        s = stats.setdefault(net_name(t.net_index), NetCopper())
        s.track_count += 1
        s.track_len_mil += math.hypot(t.x2 - t.x1, t.y2 - t.y1)
    for a in nl.arcs:
        if a.net_index < 0 or a.layer > _COPPER_MAX_LAYER:
            continue
        s = stats.setdefault(net_name(a.net_index), NetCopper())
        s.arc_count += 1
        sweep = abs(a.end_angle - a.start_angle)
        s.track_len_mil += a.radius * math.radians(sweep)
    for f in nl.fills:
        if f.net_index < 0 or f.layer > _COPPER_MAX_LAYER:
            continue
        stats.setdefault(net_name(f.net_index), NetCopper()).fill_count += 1
    for p in nl.polygons:
        if p.net_index < 0:
            continue
        stats.setdefault(net_name(p.net_index), NetCopper()).polygon_count += 1
    for v in nl.vias:
        if v.net_index < 0:
            continue
        stats.setdefault(net_name(v.net_index), NetCopper()).via_count += 1
    return stats


def _similarity_modes():
    return [
        lambda x, y: (x, y),
        lambda x, y: (-y, x),
        lambda x, y: (-x, -y),
        lambda x, y: (y, -x),
        lambda x, y: (-x, y),
        lambda x, y: (y, x),
        lambda x, y: (x, -y),
        lambda x, y: (-y, -x),
    ]


def _fit_alignment(pa: dict[str, tuple[float, float]],
                   pb: dict[str, tuple[float, float]],
                   refs: list[str]):
    """Fit the best similarity transform (8 dihedral modes + scale + translation).
    Returns (mode_fn, scale, tx, ty, mean_err)."""
    n = len(refs)
    cax = sum(pa[r][0] for r in refs) / n
    cay = sum(pa[r][1] for r in refs) / n
    cbx = sum(pb[r][0] for r in refs) / n
    cby = sum(pb[r][1] for r in refs) / n
    vc = sum((pb[r][0] - cbx) ** 2 + (pb[r][1] - cby) ** 2 for r in refs)
    best = None
    for fn in _similarity_modes():
        va = 0.0
        for r in refs:
            tx_, ty_ = fn(pa[r][0] - cax, pa[r][1] - cay)
            va += tx_ * tx_ + ty_ * ty_
        s = math.sqrt(vc / va) if va else 1.0
        tcx, tcy = fn(cax, cay)
        tx = cbx - s * tcx
        ty = cby - s * tcy
        err = 0.0
        for r in refs:
            ex, ey = fn(pa[r][0], pa[r][1])
            err += math.hypot(s * ex + tx - pb[r][0], s * ey + ty - pb[r][1])
        err /= n
        if best is None or err < best[0]:
            best = (err, fn, s, tx, ty)
    return best  # (mean_err, fn, scale, tx, ty)


def compare_pcb(a: PcbNetlist, b: PcbNetlist, pos_tol_mil: float = 2.0,
                len_tol: float = 0.02) -> PcbDiffResult:
    res = PcbDiffResult()
    res.outline_a = _bbox(a.board_outline)
    res.outline_b = _bbox(b.board_outline)
    res.outline_ok = (
        abs(res.outline_a[0] - res.outline_b[0]) <= _PANEL_TOL_MIL
        and abs(res.outline_a[1] - res.outline_b[1]) <= _PANEL_TOL_MIL
    )

    # components by designator (panel duplicates collapse to first occurrence)
    def comp_map(nl: PcbNetlist):
        out = {}
        for c in nl.components:
            if c.designator and c.designator not in out:
                out[c.designator] = c
        return out

    ca, cb = comp_map(a), comp_map(b)
    common_refs = sorted(set(ca) & set(cb))

    # align coordinate frames before comparing positions (different EDA
    # origins / rotations / panel layouts should not look like "moved")
    fn, scale, txx, tyy = None, 1.0, 0.0, 0.0
    if len(common_refs) >= 3:
        pa = {r: (ca[r].x_mil, ca[r].y_mil) for r in common_refs}
        pb = {r: (cb[r].x_mil, cb[r].y_mil) for r in common_refs}
        err, fn, scale, txx, tyy = _fit_alignment(pa, pb, common_refs)
        res.alignment = (
            f"best-fit similarity: mean_err={err:.1f}mil scale={scale:.4f} "
            f"trans=({txx:.0f},{tyy:.0f})"
        )
        if err > max(50.0, pos_tol_mil * 5):
            res.alignment += " — frames/panels differ, positions NOT comparable"
            fn = None

    def ax_pos(ref: str) -> tuple[float, float]:
        x, y = ca[ref].x_mil, ca[ref].y_mil
        if fn is None:
            return (x, y)
        ex, ey = fn(x, y)
        return (scale * ex + txx, scale * ey + tyy)

    position_comparable = fn is not None or len(common_refs) < 3
    for ref in common_refs:
        res.comps_common += 1
        if not position_comparable:
            continue
        ax, ay = ax_pos(ref)
        dx = ax - cb[ref].x_mil
        dy = ay - cb[ref].y_mil
        if math.hypot(dx, dy) > pos_tol_mil or ca[ref].layer != cb[ref].layer:
            res.comps_moved.append(
                f"{ref}: ({ca[ref].x_mil:.1f},{ca[ref].y_mil:.1f},{ca[ref].layer})"
                f" vs ({cb[ref].x_mil:.1f},{cb[ref].y_mil:.1f},{cb[ref].layer})"
            )
    res.comps_only_a = sorted(set(ca) - set(cb))
    res.comps_only_b = sorted(set(cb) - set(ca))

    # pads by (ref, pin) -> position (median across duplicates)
    def pad_pos(nl: PcbNetlist):
        out: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for p in nl.pads:
            if p.component_index < 0 or p.component_index >= len(nl.components):
                continue
            ref = nl.components[p.component_index].designator
            out.setdefault((ref, p.name), []).append((p.x_mil, p.y_mil))
        return {k: v[0] for k, v in out.items()}

    pa, pb = pad_pos(a), pad_pos(b)
    for key in sorted(set(pa) & set(pb)):
        res.pads_checked += 1
        if not position_comparable:
            continue
        ax, ay = pa[key]
        if fn is not None:
            ex, ey = fn(ax, ay)
            ax, ay = scale * ex + txx, scale * ey + tyy
        if math.hypot(ax - pb[key][0], ay - pb[key][1]) > pos_tol_mil:
            res.pads_moved.append(
                f"{key[0]}.{key[1]}: ({pa[key][0]:.1f},{pa[key][1]:.1f})"
                f" vs ({pb[key][0]:.1f},{pb[key][1]:.1f})"
            )

    # vias: match as sorted position lists (both directions)
    res.vias_a = len(a.vias)
    res.vias_b = len(b.vias)
    va = sorted((round(v.x_mil, 1), round(v.y_mil, 1)) for v in a.vias)
    vb = sorted((round(v.x_mil, 1), round(v.y_mil, 1)) for v in b.vias)
    used_b = [False] * len(vb)
    for pt in va:
        found = False
        for j, q in enumerate(vb):
            if not used_b[j] and math.hypot(pt[0] - q[0], pt[1] - q[1]) <= pos_tol_mil:
                used_b[j] = True
                found = True
                break
        if not found:
            res.vias_unmatched.append(pt)
    used_a = [False] * len(va)
    for q in vb:
        found = False
        for j, pt in enumerate(va):
            if not used_a[j] and math.hypot(pt[0] - q[0], pt[1] - q[1]) <= pos_tol_mil:
                used_a[j] = True
                found = True
                break
        if not found:
            res.vias_unmatched.append(q)

    # copper statistics per net
    sa, sb = copper_stats(a), copper_stats(b)
    res.nets_only_a = sorted(set(sa) - set(sb))
    res.nets_only_b = sorted(set(sb) - set(sa))
    for net in sorted(set(sa) & set(sb)):
        na, nb = sa[net], sb[net]
        if na.track_count != nb.track_count:
            res.copper_diffs.append(
                f"{net}: track_count {na.track_count} vs {nb.track_count}"
            )
            continue
        la, lb = na.track_len_mil, nb.track_len_mil
        if max(la, lb) > 0 and abs(la - lb) / max(la, lb) > len_tol:
            res.copper_diffs.append(f"{net}: copper_len {la:.0f} vs {lb:.0f} mil")
        if na.via_count != nb.via_count:
            res.copper_diffs.append(f"{net}: via {na.via_count} vs {nb.via_count}")
        if na.polygon_count != nb.polygon_count:
            res.copper_diffs.append(
                f"{net}: polygon {na.polygon_count} vs {nb.polygon_count}"
            )
    return res


def render_pcbdiff_report(res: PcbDiffResult, name_a: str, name_b: str) -> str:
    L: list[str] = []
    w = L.append
    w("# PCB 级验证报告")
    w("")
    w(f"| A | `{name_a}` |")
    w(f"|---|---|")
    w(f"| B | `{name_b}` |")
    w("")
    w(f"## 总体结论：**{res.grade}**")
    w("")
    if res.alignment:
        w(f"- 坐标对齐：{res.alignment}")
    w("")
    w(f"- 板框：A {res.outline_a[0]:.0f}×{res.outline_a[1]:.0f} mil vs "
      f"B {res.outline_b[0]:.0f}×{res.outline_b[1]:.0f} mil → {'一致' if res.outline_ok else '不一致'}")
    w(f"- 元件：公共 {res.comps_common}，移位 {len(res.comps_moved)}，"
      f"A 独有 {len(res.comps_only_a)}，B 独有 {len(res.comps_only_b)}")
    w(f"- 焊盘位置：检查 {res.pads_checked}，偏移 {len(res.pads_moved)}")
    w(f"- 过孔：A {res.vias_a} vs B {res.vias_b}，未配对 {len(res.vias_unmatched)}")
    w(f"- 铜皮差异项：{len(res.copper_diffs)}；A 独有网络 {len(res.nets_only_a)}，"
      f"B 独有网络 {len(res.nets_only_b)}")
    w("")
    for title, items in (("移位元件", res.comps_moved), ("偏移焊盘", res.pads_moved),
                         ("铜皮差异", res.copper_diffs),
                         ("A 独有元件", res.comps_only_a), ("B 独有元件", res.comps_only_b),
                         ("A 独有网络", res.nets_only_a), ("B 独有网络", res.nets_only_b)):
        if items:
            w(f"### {title}（{len(items)}）")
            w("")
            for it in items[:50]:
                w(f"- `{it}`")
            w("")
    return "\n".join(L)
