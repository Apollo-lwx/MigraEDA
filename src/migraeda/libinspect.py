"""Structural self-inspection for library/design files.

`migraeda libinspect <path>` prints ONLY structural metadata (container
directory tree, stream sizes, record-type histograms, parse summaries) —
no symbol graphics, no net data. When a parser fails on a private file,
the user can paste this output for debugging without sharing the design.
"""

from __future__ import annotations

import struct
import traceback
import zipfile
from collections import Counter
from pathlib import Path

import olefile


def _sniff(path: Path) -> str:
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if head.startswith(b"SQLite format 3"):
        return "sqlite"
    if head.startswith(b"|HEADER"):
        return "ascii"
    if zipfile.is_zipfile(path):
        return "zip"
    return "unknown"


def _ole_tree(path: Path) -> list[str]:
    lines: list[str] = []
    ole = olefile.OleFileIO(str(path))
    try:
        for entry in ole.listdir(streams=True, storages=True):
            name = "/".join(entry)
            try:
                size = ole.get_size(entry)
                lines.append(f"  {name}  ({size} B)")
            except Exception:
                lines.append(f"  {name}/")
    finally:
        ole.close()
    return lines


def inspect_library(path: str | Path) -> str:
    path = Path(path)
    L: list[str] = []
    w = L.append
    w(f"file: {path.name}  ({path.stat().st_size} bytes)")
    kind = _sniff(path)
    w(f"container: {kind}")

    if kind == "ascii":
        w("ASCII variant detected.")
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        w(f"first line: {first[:120]}")
        return "\n".join(L)

    if kind != "ole":
        w("(非 OLE 容器，仅显示类型信息)")
        return "\n".join(L)

    w("\n-- 目录树（仅结构，无内容）--")
    tree = _ole_tree(path)
    L.extend(tree[:200])
    if len(tree) > 200:
        w(f"  ... 共 {len(tree)} 项")

    suf = path.suffix.lower()
    w("\n-- 解析器自检 --")
    try:
        if suf == ".schlib":
            from migraeda.schlib import parse_schlib

            lib = parse_schlib(path)
            w(f"symbols: {len(lib.symbols)}")
            for name, sym in list(lib.symbols.items())[:10]:
                w(f"  {name}: {len(sym.pins)} pins")
        elif suf == ".pcblib":
            from migraeda.pcblib import parse_pcblib

            lib = parse_pcblib(path)
            w(f"footprints: {len(lib.footprints)}")
            for name, fp in list(lib.footprints.items())[:10]:
                w(f"  {name}: {len(fp.pads)} pads")
        elif suf == ".pcbdoc":
            from migraeda.pcbdoc import parse_pcbdoc

            nl = parse_pcbdoc(path)
            w(f"components={len(nl.components)} nets={len(nl.nets)} pads={len(nl.pads)} "
              f"vias={len(nl.vias)} tracks={len(nl.tracks)}")
        elif suf == ".schdoc":
            from migraeda.schdoc import parse_schdoc

            m = parse_schdoc(path)
            w(f"components={len(m.components)} pins={len(m.pin_nets)} "
              f"nets={len(m.net_members())}")
        else:
            w(f"(暂无 {suf} 的自检器，目录树已可诊断)")
    except Exception:
        w("解析失败， traceback（把这段发给开发者即可定位，不含图形数据）:")
        w("```")
        w(traceback.format_exc())
        w("```")
    return "\n".join(L)
