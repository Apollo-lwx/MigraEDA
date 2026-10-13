"""Extract the embedded library (symbols / footprints / devices) from .eprj."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from migraeda.eprj_sqlite import _load_symbols
from migraeda.libmodel import LibDevice, LibFootprint, LibPad, LibPin, Library, LibSymbol


def _nums(spec, limit: int = 3) -> list[float]:
    """Collect numeric scalars from a (possibly nested) spec list."""
    out: list[float] = []

    def walk(item) -> None:
        if len(out) >= limit:
            return
        if isinstance(item, (int, float)):
            out.append(float(item))
        elif isinstance(item, list):
            for sub in item:
                walk(sub)

    if isinstance(spec, list):
        for el in spec:
            walk(el)
    return out


def _parse_footprint(data: str, name: str) -> LibFootprint:
    from migraeda.eprj_sqlite import _maybe_decompress

    data = _maybe_decompress(data)
    fp = LibFootprint(name=name)
    xs: list[float] = []
    ys: list[float] = []
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec[0] != "PAD" or len(rec) < 11:
            continue
        number = str(rec[5])
        x, y = float(rec[6]), float(rec[7])
        hole_nums = _nums(rec[9], 2)
        pad_spec = rec[10] if isinstance(rec[10], list) else []
        size_nums = _nums(pad_spec, 2)
        hole = hole_nums[0] if hole_nums else 0.0
        shape = str(pad_spec[0]) if pad_spec and isinstance(pad_spec[0], str) else ""
        size_x = size_nums[0] if size_nums else 0.0
        size_y = size_nums[1] if len(size_nums) >= 2 else size_x
        fp.pads.append(
            LibPad(number=number, x=x, y=y, size_x=size_x, size_y=size_y,
                   hole=hole, shape=shape, layer=str(rec[4]))
        )
        xs.append(x)
        ys.append(y)
    if xs:
        fp.bbox = (min(xs), min(ys), max(xs), max(ys))
    return fp


def extract_eprj_library(path: str | Path) -> Library:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    lib = Library(source=f"eprj-lib:{path.name}")
    con = sqlite3.connect(str(path))
    try:
        # symbols (docType=2) — reuse the symbol loader used by the schematic parser
        symbols = _load_symbols(con)
        symbols.pop("__by_title__", None)
        for su, sym in symbols.items():
            ls = LibSymbol(name=sym.title)
            for p in sym.pins:
                ls.pins.append(
                    LibPin(number=p.number or p.pin_id, name=p.name,
                           x=p.x, y=p.y, length=p.length, orient=p.orient)
                )
            if ls.pins:
                xs = [p.x for p in ls.pins]
                ys = [p.y for p in ls.pins]
                ls.bbox = (min(xs), min(ys), max(xs), max(ys))
            lib.symbols[ls.name] = ls

        # footprints (docType=4)
        for uuid, title, data in con.execute(
            "SELECT uuid, display_title, dataStr FROM components WHERE docType=4"
        ):
            fp = _parse_footprint(data, title)
            lib.footprints[fp.name] = fp

        # devices (symbol+footprint bindings via attributes not always present;
        # devices table gives the value inventory)
        for du, title, desc in con.execute(
            "SELECT uuid, display_title, description FROM devices"
        ):
            lib.devices[title] = LibDevice(name=title, description=desc)
    finally:
        con.close()
    return lib
