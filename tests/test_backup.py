import json

import pytest

from optimize.adapters.backup import BackupError, BackupManager, atomic_write_text


@pytest.fixture()
def game_env(tmp_path):
    config = tmp_path / "game" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"shadow": "high"}\n')
    manager = BackupManager(tmp_path / "game")
    return config, manager


def test_backup_and_restore_round_trip(game_env):
    config, manager = game_env
    backup = manager.create([config], "baseline")
    assert backup.backup_id.endswith("-baseline")
    assert (backup.directory / "manifest.json").exists()

    config.write_text('{"shadow": "low"}\n')  # simulate a later change
    manager.restore(backup.backup_id)
    assert config.read_text() == '{"shadow": "high"}\n'


def test_restore_verifies_hashes(game_env):
    config, manager = game_env
    backup = manager.create([config], "baseline")
    stored = backup.directory / "00__settings.json"
    stored.write_text("tampered")
    with pytest.raises(BackupError, match="corrupted"):
        manager.restore(backup.backup_id)


def test_restore_unknown_backup_id(game_env):
    _config, manager = game_env
    with pytest.raises(BackupError, match="not found"):
        manager.restore("does-not-exist")


def test_latest_returns_most_recent(game_env):
    config, manager = game_env
    first = manager.create([config], "first")
    config.write_text('{"shadow": "medium"}\n')
    second = manager.create([config], "second")
    latest = manager.latest()
    assert latest.backup_id == second.backup_id
    assert latest.backup_id != first.backup_id


def test_audit_log_records_actions(game_env):
    config, manager = game_env
    backup = manager.create([config], "baseline")
    manager.restore(backup.backup_id)
    lines = [json.loads(line) for line in manager.audit.path.read_text().splitlines()]
    actions = [entry["action"] for entry in lines]
    assert actions == ["backup-created", "backup-restored"]
    assert all("ts" in entry for entry in lines)


def test_backup_requires_existing_files(tmp_path):
    manager = BackupManager(tmp_path / "empty")
    with pytest.raises(BackupError, match="no config files"):
        manager.create([tmp_path / "missing.json"], "baseline")


def test_atomic_write_leaves_no_temp_file(tmp_path):
    target = tmp_path / "cfg" / "settings.json"
    atomic_write_text(target, '{"a": 1}\n')
    assert target.read_text() == '{"a": 1}\n'
    leftovers = [p for p in target.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_atomic_write_replaces_existing_content(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"
