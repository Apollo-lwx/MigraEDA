"""Parse Altium .PcbLib footprint libraries (OLE/CFB container).

Structure (per KiCad's Altium importer docs): one storage directory per
footprint; each directory mirrors the PcbDoc stream layout (Pads6, Tracks6,
Arcs6, Texts6...) plus a `Parameters` stream holding PATTERN=<name>.
"""

from __future__ import annotations

import struct
from pathlib import Path

import olefile

from migraeda.libmodel import LibFootprint, LibPad, Library
from migraeda.pcbdoc import MIL, _decode, _read_props_records

_SHAPE_NAMES = {0: "", 1: "circle", 2: "rect", 3: "octagon", 9: "round-rect"}


def _parse_lib_pads(data: bytes) -> list[LibPad]:
    pads: list[LibPad] = []
    i = 0
    while i < len(data):
        rtype = data[i]
        i += 1
        if rtype != 2:
            break
        name = ""
        x = y = sx = sy = hole = 0
        shape = 0
        layer = 0
        for sr in range(6):
            if i + 4 > len(data):
                break
            (ln,) = struct.unpack_from("<I", data, i)
            i += 4
            sub = data[i : i + ln]
            i += ln
            if sr == 0 and ln >= 1:
                nlen = sub[0]
                name = _decode(sub[1 : 1 + nlen])
            elif sr == 4 and ln >= 52:
                layer = sub[0]
                x, y = struct.unpack_from("<ii", sub, 13)
                sx, sy = struct.unpack_from("<ii", sub, 21)
                hole = struct.unpack_from("<i", sub, 45)[0]
                shape = sub[49]
        pads.append(
            LibPad(number=name, x=x * MIL, y=y * MIL,
                   size_x=sx * MIL, size_y=sy * MIL, hole=hole * MIL,
                   shape=_SHAPE_NAMES.get(shape, str(shape)), layer=str(layer))
        )
    return pads


def parse_pcblib(path: str | Path) -> Library:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    lib = Library(source=f"pcblib:{path.name}")
    ole = olefile.OleFileIO(str(path))
    try:
        # footprint directories sit at the root; skip known non-footprint dirs
        skip = {"Library", "Models", "ModelsNoEmbed"}
        dirs: set[str] = set()
        for entry in ole.listdir(streams=False, storages=True):
            if entry:
                dirs.add(entry[0])
        for d in sorted(dirs - skip):
            fp = LibFootprint(name=d)
            try:
                params_path = [d, "Parameters"]
                if ole.exists(params_path):
                    recs = _read_props_records(ole.openstream(params_path).read())
                    if recs and recs[0].get("PATTERN"):
                        fp.name = recs[0]["PATTERN"]
                pads_path = [d, "Pads6", "Data"]
                if ole.exists(pads_path):
                    fp.pads = _parse_lib_pads(ole.openstream(pads_path).read())
            except Exception as exc:
                lib.notes.append(f"footprint dir {d!r} parse failed: {exc}")
                continue
            if fp.pads:
                xs = [p.x for p in fp.pads]
                ys = [p.y for p in fp.pads]
                fp.bbox = (min(xs), min(ys), max(xs), max(ys))
            lib.footprints[fp.name] = fp
    finally:
        ole.close()
    return lib
