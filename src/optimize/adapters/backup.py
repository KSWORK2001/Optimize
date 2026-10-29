"""Configuration backup, restore, atomic writes, and the audit log.

README: 'Safety and compatibility' — back up before editing, validate before
applying, write atomically, keep an audit log of every change, and provide
one-click restore. Nothing in this module deletes user data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class BackupError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    """Write via temp file + rename so a crash never leaves a truncated config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pc-optimize.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@dataclass(frozen=True)
class Backup:
    backup_id: str
    label: str
    created: str
    files: tuple[Path, ...]     # original locations
    directory: Path


class AuditLog:
    """Append-only JSONL record of every change the tool makes."""

    def __init__(self, root: Path) -> None:
        self.path = root / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, action: str, **details: object) -> None:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "action": action}
        entry.update(details)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")


class BackupManager:
    """Timestamped copies of configuration files plus a verifiable manifest."""

    def __init__(self, game_root: Path) -> None:
        self.root = game_root
        self.backups_dir = game_root / "backups"
        self.audit = AuditLog(game_root)

    def create(self, files: Sequence[Path], label: str) -> Backup:
        existing = [f for f in files if f.exists()]
        if not existing:
            raise BackupError(f"no config files to back up under {self.root}")

        backup_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(label)}"
        target = self.backups_dir / backup_id
        target.mkdir(parents=True, exist_ok=False)

        manifest_entries = []
        for index, original in enumerate(existing):
            stored = target / f"{index:02d}__{original.name}"
            shutil.copy2(original, stored)
            manifest_entries.append(
                {
                    "original": str(original),
                    "stored": stored.name,
                    "sha256": sha256_of(stored),
                    "size": original.stat().st_size,
                }
            )

        manifest = {
            "id": backup_id,
            "label": label,
            "created": datetime.now().isoformat(timespec="seconds"),
            "files": manifest_entries,
        }
        atomic_write_text(target / "manifest.json", json.dumps(manifest, indent=2))
        self.audit.append("backup-created", backup_id=backup_id, files=len(existing))
        return Backup(
            backup_id=backup_id,
            label=label,
            created=manifest["created"],
            files=tuple(existing),
            directory=target,
        )

    def load(self, backup_id: str) -> Backup:
        target = self.backups_dir / backup_id
        manifest_path = target / "manifest.json"
        if not manifest_path.exists():
            raise BackupError(
                f"backup {backup_id!r} not found in {self.backups_dir}; "
                "run 'pc-optimize history' or list the backups directory"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return Backup(
            backup_id=manifest["id"],
            label=manifest["label"],
            created=manifest["created"],
            files=tuple(Path(e["original"]) for e in manifest["files"]),
            directory=target,
        )

    def restore(self, backup_id: str) -> Backup:
        backup = self.load(backup_id)
        manifest = json.loads((backup.directory / "manifest.json").read_text(encoding="utf-8"))
        restored = []
        for entry in manifest["files"]:
            stored = backup.directory / entry["stored"]
            if not stored.exists():
                raise BackupError(f"backup file missing: {stored}")
            if sha256_of(stored) != entry["sha256"]:
                raise BackupError(f"backup file corrupted (hash mismatch): {stored}")
            original = Path(entry["original"])
            atomic_write_text(original, stored.read_text(encoding="utf-8"))
            restored.append(str(original))
        self.audit.append("backup-restored", backup_id=backup_id, files=restored)
        return backup

    def latest(self) -> Backup | None:
        if not self.backups_dir.exists():
            return None
        ids = sorted(p.name for p in self.backups_dir.iterdir() if p.is_dir())
        return self.load(ids[-1]) if ids else None


def _slug(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in text.lower())
    return cleaned.strip("-")[:40] or "backup"
