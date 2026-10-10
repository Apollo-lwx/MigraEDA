"""diff_v0: compare ProjectStats with PASS/WARN/FAIL grading."""

from __future__ import annotations

from migraeda.models import DiffCheck, DiffGrade, DiffResult, ProjectStats


def _worst(a: DiffGrade, b: DiffGrade) -> DiffGrade:
    order = {DiffGrade.PASS: 0, DiffGrade.WARN: 1, DiffGrade.FAIL: 2}
    return a if order[a] >= order[b] else b


def diff_stats(source: ProjectStats, target: ProjectStats) -> DiffResult:
    """Compare source vs target stats (diff_v0 rules)."""
    checks: list[DiffCheck] = []

    # components
    if source.component_count == target.component_count:
        checks.append(
            DiffCheck(
                name="component_count",
                grade=DiffGrade.PASS,
                message=f"component count match: {source.component_count}",
                source_value=source.component_count,
                target_value=target.component_count,
            )
        )
    else:
        checks.append(
            DiffCheck(
                name="component_count",
                grade=DiffGrade.FAIL,
                message=(
                    f"component count mismatch: source={source.component_count} "
                    f"target={target.component_count}"
                ),
                source_value=source.component_count,
                target_value=target.component_count,
            )
        )

    src_nets = set(source.net_names)
    tgt_nets = set(target.net_names)
    only_src = sorted(src_nets - tgt_nets)
    only_tgt = sorted(tgt_nets - src_nets)
    sym = len(only_src) + len(only_tgt)
    if sym == 0:
        checks.append(
            DiffCheck(
                name="net_names",
                grade=DiffGrade.PASS,
                message=f"net name set match ({len(src_nets)} nets)",
                source_value=sorted(src_nets),
                target_value=sorted(tgt_nets),
            )
        )
    elif sym <= 2:
        checks.append(
            DiffCheck(
                name="net_names",
                grade=DiffGrade.WARN,
                message=(
                    f"net name set nearly match (symmetric diff={sym}); "
                    f"only_source={only_src} only_target={only_tgt}"
                ),
                source_value=sorted(src_nets),
                target_value=sorted(tgt_nets),
            )
        )
    else:
        checks.append(
            DiffCheck(
                name="net_names",
                grade=DiffGrade.FAIL,
                message=(
                    f"net name set mismatch (symmetric diff={sym}); "
                    f"only_source={only_src} only_target={only_tgt}"
                ),
                source_value=sorted(src_nets),
                target_value=sorted(tgt_nets),
            )
        )

    via_delta = abs(source.via_count - target.via_count)
    if via_delta == 0:
        checks.append(
            DiffCheck(
                name="via_count",
                grade=DiffGrade.PASS,
                message=f"via count match: {source.via_count}",
                source_value=source.via_count,
                target_value=target.via_count,
            )
        )
    elif via_delta == 1:
        checks.append(
            DiffCheck(
                name="via_count",
                grade=DiffGrade.WARN,
                message=(
                    f"via count off-by-one: source={source.via_count} "
                    f"target={target.via_count}"
                ),
                source_value=source.via_count,
                target_value=target.via_count,
            )
        )
    else:
        checks.append(
            DiffCheck(
                name="via_count",
                grade=DiffGrade.FAIL,
                message=(
                    f"via count mismatch: source={source.via_count} "
                    f"target={target.via_count}"
                ),
                source_value=source.via_count,
                target_value=target.via_count,
            )
        )

    overall = DiffGrade.PASS
    for c in checks:
        overall = _worst(overall, c.grade)

    summary = {
        DiffGrade.PASS: "All diff_v0 checks passed.",
        DiffGrade.WARN: "Migration usable with warnings — review net/via diffs.",
        DiffGrade.FAIL: "Migration failed verification — do not trust without fixes.",
    }[overall]

    return DiffResult(
        grade=overall,
        checks=checks,
        source=source,
        target=target,
        summary=summary,
    )
