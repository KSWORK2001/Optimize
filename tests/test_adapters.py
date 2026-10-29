import pytest

from optimize.adapters.base import GameAdapterError
from optimize.adapters.synthetic import AURORA_CATALOG, SyntheticGameAdapter


@pytest.fixture()
def adapter(tmp_path):
    return SyntheticGameAdapter(tmp_path)


def test_first_install_writes_defaults(adapter):
    settings = adapter.read_settings()
    assert settings == {spec.key: spec.default for spec in AURORA_CATALOG.specs}


def test_apply_changes_validates_values(adapter):
    with pytest.raises(ValueError, match="not a supported value"):
        adapter.apply_changes({"shadow_quality": "extreme"})


def test_apply_changes_rejects_unknown_keys(adapter):
    with pytest.raises(KeyError, match="unknown setting"):
        adapter.apply_changes({"nonexistent_setting": "low"})


def test_apply_changes_merges_without_losing_other_settings(adapter):
    adapter.apply_changes({"shadow_quality": "low"})
    settings = adapter.read_settings()
    assert settings["shadow_quality"] == "low"
    assert settings["resolution_scale"] == "100"  # untouched


def test_backup_and_restore_config(adapter):
    original = adapter.read_settings()
    backup = adapter.backup("baseline")
    adapter.apply_changes({"resolution_scale": "50", "shadow_quality": "low"})
    assert adapter.read_settings() != original
    adapter.restore(backup.backup_id)
    assert adapter.read_settings() == original


def test_unreadable_config_raises_clean_error(tmp_path):
    adapter = SyntheticGameAdapter(tmp_path, install=False)
    adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
    adapter.config_path.write_text("{not json")
    with pytest.raises(GameAdapterError, match="unreadable config"):
        adapter.read_settings()


def test_catalog_defaults_are_valid(adapter):
    # Defaults must always be part of the supported value list.
    catalog = adapter.catalog()
    for spec in catalog.specs:
        assert spec.default in spec.value_names
