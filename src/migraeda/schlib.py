"""Parse Altium .SchLib symbol libraries (OLE/CFB container).

Structure (per KiCad's Altium importer docs): one storage directory per
symbol; each symbol directory contains a record stream with the symbol's
primitives in the same record format as .SchDoc (uint32-framed
`|KEY=VALUE|...` records; pins are RECORD=2).
"""

from __future__ import annotations

from pathlib import Path

import olefile

from migraeda.libmodel import LibPin, LibSymbol, Library
from migraeda.schdoc import _int, _loc, _records

_ORIENT_DIRS = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}


def parse_schlib(path: str | Path) -> Library:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    lib = Library(source=f"schlib:{path.name}")
    ole = olefile.OleFileIO(str(path))
    try:
        streams = ole.listdir(streams=True, storages=False)
        # group streams by top-level directory (each = one symbol)
        by_dir: dict[str, list[list[str]]] = {}
        for entry in streams:
            if entry:
                by_dir.setdefault(entry[0], []).append(entry)
        for d, entries in sorted(by_dir.items()):
            if d.lower() in ("library", "models", "modelsnoembed"):
                continue
            # the symbol record stream: the shortest-named stream in the dir
            # (commonly "Data")
            rec_stream = None
            for e in entries:
                if e[-1].lower() in ("data", "fileheader"):
                    rec_stream = e
                    break
            if rec_stream is None:
                rec_stream = min(entries, key=lambda e: len(e))
            try:
                data = ole.openstream(rec_stream).read()
            except Exception:
                lib.notes.append(f"cannot read stream for symbol dir {d!r}, skipped")
                continue
            sym = LibSymbol(name=d)
            for _idx, rec in _records(data):
                if rec.get("RECORD") != "2":
                    continue
                x, y = _loc(rec)
                orient = _int(rec, "PINCONGLOMERATE") & 3
                dx, dy = _ORIENT_DIRS.get(orient, (0, 0))
                ln = _int(rec, "PINLENGTH", 0)
                # hotspot -> into-body is opposite of the pin's orientation
                into = (orient + 2) % 4
                idir = _ORIENT_DIRS[into]
                import math as _m

                sym.pins.append(
                    LibPin(
                        number=rec.get("DESIGNATOR", "") or "?",
                        name=rec.get("NAME", ""),
                        x=x + dx * ln,
                        y=y + dy * ln,
                        length=float(ln),
                        orient=_m.degrees(_m.atan2(idir[1], idir[0])) % 360,
                    )
                )
            if sym.pins:
                xs = [p.x for p in sym.pins]
                ys = [p.y for p in sym.pins]
                sym.bbox = (min(xs), min(ys), max(xs), max(ys))
            lib.symbols[sym.name] = sym
    finally:
        ole.close()
    return lib
