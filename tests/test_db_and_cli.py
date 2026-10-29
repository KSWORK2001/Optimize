import json
import sqlite3
import sys

import pytest

from optimize.adapters.synthetic import SyntheticGameAdapter
from optimize.cli import main
from optimize.db import ProfileDatabase
from optimize.engine.search import SearchConfig, run_search
from optimize.hardware.profiler import SimulatedProfiler
from optimize.models import Goal
from optimize.telemetry.simulated import SimulatedCollector


def _make_report(tmp_path):
    adapter = SyntheticGameAdapter(tmp_path)
    report = run_search(
        adapter, SimulatedCollector(adapter.catalog()), SimulatedProfiler().profile(),
        Goal.BALANCED, SearchConfig(runs_per_config=2, max_trials=2, capture_seconds=3.0),
    )
    return adapter, report


def test_database_round_trip(tmp_path):
    _adapter, report = _make_report(tmp_path)
    db = ProfileDatabase(tmp_path / "profiles.db")
    try:
        session_id = db.save_session(report)
        sessions = db.recent_sessions()
    finally:
        db.close()

    assert len(sessions) == 1
    summary = sessions[0]
    assert summary.session_id == session_id
    assert summary.game_id == report.game_id
    assert summary.goal == report.goal.value
    assert summary.recommendation == report.recommendation

    conn = sqlite3.connect(tmp_path / "profiles.db")
    rows = conn.execute(
        "SELECT label, settings_json, frame_times_json FROM runs WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    conn.close()
    assert rows, "every benchmark run must be stored"
    for _label, settings_json, frames_json in rows:
        assert isinstance(json.loads(settings_json), dict)
        frames = json.loads(frames_json)
        assert frames and all(f > 0 for f in frames)


def test_multiple_sessions_ordered_recent_first(tmp_path):
    db = ProfileDatabase(tmp_path / "profiles.db")
    try:
        ids = []
        for _ in range(3):
            _, report = _make_report(tmp_path)
            ids.append(db.save_session(report))
        assert [s.session_id for s in db.recent_sessions()] == list(reversed(ids))
    finally:
        db.close()


# ---- CLI ---------------------------------------------------------------------


def test_cli_demo_restores_by_default(tmp_path, capsys):
    exit_code = main(["demo", "--data-dir", str(tmp_path), "--trials", "3",
                      "--runs", "2", "--seconds", "3"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Original configuration verified/restored" in out

    adapter = SyntheticGameAdapter(tmp_path)
    assert adapter.read_settings() == {
        spec.key: spec.default for spec in adapter.catalog().specs
    }


def test_cli_demo_apply_persists_winning_config(tmp_path, capsys):
    assert main(["demo", "--data-dir", str(tmp_path), "--trials", "3",
                 "--runs", "2", "--seconds", "3", "--apply"]) == 0
    adapter = SyntheticGameAdapter(tmp_path)
    settings = adapter.read_settings()
    assert settings["resolution_scale"] != "100"  # winning change persisted

    # One-click rollback returns to the pre-optimize backup.
    assert main(["restore", "--game", "aurora-plains", "--data-dir", str(tmp_path)]) == 0
    assert adapter.read_settings()["resolution_scale"] == "100"


def test_cli_history_lists_sessions(tmp_path, capsys):
    main(["demo", "--data-dir", str(tmp_path), "--trials", "2", "--runs", "2",
          "--seconds", "3"])
    capsys.readouterr()
    assert main(["history", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "aurora-plains" in out
    assert "apply-candidate" in out


def test_cli_unknown_game_fails_cleanly(tmp_path, capsys):
    assert main(["optimize", "--game", "not-a-game", "--data-dir", str(tmp_path)]) == 1
    assert "no adapter registered" in capsys.readouterr().err


def test_cli_benchmark_reports_variance(tmp_path, capsys):
    assert main(["benchmark", "--data-dir", str(tmp_path), "--runs", "2",
                 "--seconds", "3"]) == 0
    out = capsys.readouterr().out
    assert "run 1" in out and "run-to-run variance" in out


@pytest.mark.skipif(sys.platform == "win32", reason="asserts the fallback path")
def test_detect_hardware_falls_back_to_simulated():
    from optimize.hardware.profiler import detect_hardware

    profile = detect_hardware()
    assert profile.source == "simulated"
    assert profile.vram_mb > 0
