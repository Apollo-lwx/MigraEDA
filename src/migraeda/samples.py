"""Discovery and classification of user-provided design samples.

Convention (see samples/README.md): samples/<project>/<files>, classified
by extension; the directory is gitignored except its README. This module is
the single place that knows the convention — generic parsers never hardcode
sample paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# extension -> logical role
ROLES: dict[str, str] = {
    ".eprj": "lceda_project",
    ".epro": "lceda_pro_archive",
    ".epcb": "lceda_pcb",
    ".schdoc": "altium_schematic",
    ".pcbdoc": "altium_pcb",
    ".schlib": "altium_symbol_lib",
    ".pcblib": "altium_footprint_lib",
    ".prjpcb": "altium_project",
}

_ROLE_LABELS = {
    "lceda_project": "嘉立创工程",
    "lceda_pro_archive": "嘉立创专业版包",
    "lceda_pcb": "嘉立创PCB",
    "altium_schematic": "AD原理图",
    "altium_pcb": "AD PCB",
    "altium_symbol_lib": "AD符号库",
    "altium_footprint_lib": "AD封装库",
    "altium_project": "AD工程",
}


@dataclass
class SampleSet:
    """All discovered files of one sample project."""

    name: str
    path: Path
    files: dict[str, list[Path]] = field(default_factory=dict)

    def roles(self) -> list[str]:
        return sorted(self.files)

    def first(self, role: str) -> Path | None:
        items = self.files.get(role)
        return items[0] if items else None

    def summary(self) -> str:
        parts = []
        for role in self.roles():
            label = _ROLE_LABELS.get(role, role)
            n = len(self.files[role])
            parts.append(f"{label}×{n}" if n > 1 else label)
        return ", ".join(parts) if parts else "(空)"


def classify(path: Path) -> str | None:
    """Return the logical role for a file, or None if not a design file."""
    return ROLES.get(path.suffix.lower())


def scan_samples(root: str | Path = "samples") -> dict[str, SampleSet]:
    """Scan samples/<project>/ and classify files by role."""
    root = Path(root)
    out: dict[str, SampleSet] = {}
    if not root.is_dir():
        return out
    for proj_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        ss = SampleSet(name=proj_dir.name, path=proj_dir)
        for f in sorted(proj_dir.iterdir()):
            if not f.is_file():
                continue  # .migraeda/ and other subdirs are ignored by convention
            role = classify(f)
            if role:
                ss.files.setdefault(role, []).append(f)
        out[proj_dir.name] = ss
    return out


def describe(root: str | Path = "samples") -> str:
    """Human-readable listing used by `migraeda samples`."""
    sets = scan_samples(root)
    if not sets:
        return (
            "samples/ 下还没有项目。按 samples/README.md 的规范投递："
            "samples/<项目名>/<设计文件>。"
        )
    lines = []
    for name, ss in sets.items():
        lines.append(f"{name}: {ss.summary()}")
        for role in ss.roles():
            for f in ss.files[role]:
                lines.append(f"    [{_ROLE_LABELS.get(role, role)}] {f.name}")
    return "\n".join(lines)
