"""Game adapter layer (README: main module 3).

Each adapter defines how to identify the game, which settings are supported,
how to read/apply/restore them, and whether a restart is required. There is
deliberately no universal config editor: adapters are isolated and the
catalog is the single source of truth for what may be changed.

ConfigFileAdapter implements the common case of a JSON settings file with
atomic writes, catalog validation, backups, and the audit log. A real game
adapter only has to supply the path, the catalog, and detection logic.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path

from optimize.adapters.backup import Backup, BackupManager, atomic_write_text
from optimize.models import SettingsCatalog


class GameAdapterError(RuntimeError):
    pass


class GameAdapter(ABC):
    game_id: str
    title: str

    def __init__(self, data_root: Path) -> None:
        self.game_root = data_root / self.game_id
        self.backups = BackupManager(self.game_root)

    @abstractmethod
    def catalog(self) -> SettingsCatalog: ...

    @abstractmethod
    def detect(self) -> bool:
        """Return True if the game is installed and its config is reachable."""

    @abstractmethod
    def read_settings(self) -> dict[str, str]: ...

    @abstractmethod
    def write_settings(self, settings: Mapping[str, str]) -> None:
        """Persist a full, already-validated settings mapping atomically."""

    def apply_changes(self, changes: Mapping[str, str]) -> dict[str, str]:
        """Validate changes against the catalog, merge over current, write once.

        This is the only path the optimizer may use to modify a game.
        """
        game_catalog = self.catalog()
        game_catalog.validate(changes)  # never apply unvalidated values
        current = self.read_settings()
        merged = {**current, **{k: str(v) for k, v in changes.items()}}
        self.write_settings(merged)
        return merged

    def backup(self, label: str) -> Backup:
        return self.backups.create([self._primary_config()], label)

    def restore(self, backup_id: str) -> Backup:
        return self.backups.restore(backup_id)

    def restore_latest(self) -> Backup | None:
        latest = self.backups.latest()
        return self.backups.restore(latest.backup_id) if latest else None

    @abstractmethod
    def _primary_config(self) -> Path: ...


class ConfigFileAdapter(GameAdapter):
    """Adapter for games that store settings in a single JSON document."""

    def __init__(self, data_root: Path, config_path: Path | None = None) -> None:
        super().__init__(data_root)
        if config_path is not None:
            self._config_path = config_path

    def _primary_config(self) -> Path:
        return self.config_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    def detect(self) -> bool:
        return self.config_path.exists()

    def read_settings(self) -> dict[str, str]:
        if not self.config_path.exists():
            raise GameAdapterError(f"config file not found: {self.config_path}")
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GameAdapterError(f"unreadable config {self.config_path}: {exc}") from exc
        return {str(k): str(v) for k, v in data.items()}

    def unknown_settings_keys(self) -> list[str]:
        """Keys present in the config but absent from the catalog.

        Usually means a game update introduced settings this adapter version
        does not know; the tool warns and never touches them (README:
        'Handle game updates by invalidating profiles when compatibility is
        uncertain').
        """
        catalog_keys = {spec.key for spec in self.catalog().specs}
        return [key for key in self.read_settings() if key not in catalog_keys]

    def write_settings(self, settings: Mapping[str, str]) -> None:
        self.catalog().validate(settings)
        payload = json.dumps(dict(sorted(settings.items())), indent=2)
        atomic_write_text(self.config_path, payload + "\n")
        self.backups.audit.append(
            "settings-written",
            file=str(self.config_path),
            settings=dict(settings),
        )
