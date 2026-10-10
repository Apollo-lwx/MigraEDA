"""Audit trail and rollback for migrations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any


def default_audit_root() -> Path:
    env = os.environ.get("MIGRAEDA_AUDIT_DIR")
    if env:
        return Path(env)
    return Path.home() / ".migraeda" / "audit"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def new_migration_id() -> str:
    ts = time.strftime("%Y%m%dT%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def record_migration(
    *,
    migration_id: str,
    source_epro: Path,
    outdir: Path,
    artifacts: list[str],
    dry_run: bool,
    diff_grade: str,
    extra: dict[str, Any] | None = None,
    audit_root: Path | None = None,
) -> Path:
    """Write an audit record under audit_root/<migration_id>/."""
    root = Path(audit_root) if audit_root else default_audit_root()
    dest = root / migration_id
    dest.mkdir(parents=True, exist_ok=True)

    source_hash = file_sha256(source_epro) if source_epro.is_file() else ""
    artifact_hashes = {}
    for rel in artifacts:
        p = outdir / rel if not Path(rel).is_absolute() else Path(rel)
        if p.is_file():
            artifact_hashes[rel] = file_sha256(p)

    # snapshot list for rollback (paths relative to outdir)
    record = {
        "migration_id": migration_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_epro": str(source_epro.resolve()),
        "source_sha256": source_hash,
        "outdir": str(outdir.resolve()),
        "artifacts": artifacts,
        "artifact_sha256": artifact_hashes,
        "dry_run": dry_run,
        "diff_grade": diff_grade,
        "extra": extra or {},
        "status": "active",
    }
    (dest / "record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # also mirror into outdir
    mirror = outdir / ".migraeda" / migration_id
    mirror.mkdir(parents=True, exist_ok=True)
    (mirror / "record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def load_record(migration_id: str, audit_root: Path | None = None) -> dict[str, Any]:
    root = Path(audit_root) if audit_root else default_audit_root()
    path = root / migration_id / "record.json"
    if not path.is_file():
        raise FileNotFoundError(f"audit record not found: {migration_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def rollback(migration_id: str, audit_root: Path | None = None) -> dict[str, Any]:
    """Remove artifacts listed in the audit record and mark rolled_back."""
    record = load_record(migration_id, audit_root=audit_root)
    if record.get("status") == "rolled_back":
        return {"migration_id": migration_id, "status": "already_rolled_back"}

    outdir = Path(record["outdir"])
    removed: list[str] = []
    for rel in record.get("artifacts") or []:
        p = outdir / rel
        if p.is_file():
            p.unlink()
            removed.append(rel)
        elif p.is_dir():
            shutil.rmtree(p)
            removed.append(rel)

    record["status"] = "rolled_back"
    record["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record["removed"] = removed

    root = Path(audit_root) if audit_root else default_audit_root()
    dest = root / migration_id
    (dest / "record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    mirror = outdir / ".migraeda" / migration_id / "record.json"
    if mirror.parent.is_dir():
        mirror.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {"migration_id": migration_id, "status": "rolled_back", "removed": removed}
