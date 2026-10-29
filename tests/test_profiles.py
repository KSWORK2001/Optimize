"""Profile export/import round trip and game-update drift detection."""

import json

from optimize.adapters.synthetic import SyntheticGameAdapter
from optimize.cli import main


def _demo_applied_settings(tmp_path):
    return SyntheticGameAdapter(tmp_path).read_settings()


def test_export_apply_round_trip(tmp_path, capsys):
    # 1. Optimize and keep the result, then export it.
    assert main(["demo", "--data-dir", str(tmp_path), "--trials", "3", "--runs", "2",
                 "--seconds", "3", "--apply"]) == 0
    optimized = _demo_applied_settings(tmp_path)
    assert main(["export", "--data-dir", str(tmp_path)]) == 0
    profile_path = tmp_path / "exports" / "session-latest-profile.json"
    profile = json.loads(profile_path.read_text())
    assert profile["settings"] == optimized

    # 2. Roll the game back to its original state.
    assert main(["restore", "--data-dir", str(tmp_path)]) == 0
    assert _demo_applied_settings(tmp_path) != optimized

    # 3. Re-apply the exported profile: same settings come back.
    assert main(["apply-config", "--data-dir", str(tmp_path),
                 "--file", str(profile_path)]) == 0
    assert _demo_applied_settings(tmp_path) == optimized


def test_apply_config_rejects_tampered_values(tmp_path):
    assert main(["demo", "--data-dir", str(tmp_path), "--trials", "2", "--runs", "2",
                 "--seconds", "3"]) == 0
    assert main(["export", "--data-dir", str(tmp_path)]) == 0
    profile_path = tmp_path / "exports" / "session-latest-profile.json"

    profile = json.loads(profile_path.read_text())
    profile["settings"]["shadow_quality"] = "ray-traced-ultra"  # not in catalog
    profile_path.write_text(json.dumps(profile))

    before = _demo_applied_settings(tmp_path)
    assert main(["apply-config", "--data-dir", str(tmp_path),
                 "--file", str(profile_path)]) == 1
    assert _demo_applied_settings(tmp_path) == before  # untouched


def test_apply_config_rejects_wrong_game(tmp_path):
    profile = {
        "format": "pc-optimize-profile", "game_id": "some-other-game",
        "settings": {"shadow_quality": "low"},
    }
    path = tmp_path / "other.json"
    path.write_text(json.dumps(profile))
    assert main(["apply-config", "--game", "aurora-plains", "--data-dir", str(tmp_path),
                 "--file", str(path)]) == 1


def test_apply_config_missing_file(tmp_path):
    assert main(["apply-config", "--data-dir", str(tmp_path),
                 "--file", str(tmp_path / "nope.json")]) == 1


def test_apply_config_backs_up_first(tmp_path):
    assert main(["demo", "--data-dir", str(tmp_path), "--trials", "2", "--runs", "2",
                 "--seconds", "3", "--apply"]) == 0
    assert main(["export", "--data-dir", str(tmp_path)]) == 0
    profile_path = tmp_path / "exports" / "session-latest-profile.json"

    assert main(["apply-config", "--data-dir", str(tmp_path),
                 "--file", str(profile_path)]) == 0
    adapter = SyntheticGameAdapter(tmp_path)
    assert adapter.backups.latest() is not None  # a pre-apply-config backup exists
    assert adapter.restore_latest() is not None


def test_unknown_settings_keys_detects_drift(tmp_path):
    adapter = SyntheticGameAdapter(tmp_path)
    assert adapter.unknown_settings_keys() == []

    # Simulate a game update adding a setting our catalog doesn't know.
    settings = adapter.read_settings()
    settings["new_render_feature"] = "on"
    adapter.config_path.write_text(json.dumps(settings))

    assert adapter.unknown_settings_keys() == ["new_render_feature"]
