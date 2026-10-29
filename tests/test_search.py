"""End-to-end tests of the bounded search loop (Milestone 1 behavior)."""

import pytest

from optimize.adapters.synthetic import AURORA_CATALOG, SyntheticGameAdapter
from optimize.engine.search import SearchConfig, run_search
from optimize.hardware.profiler import SimulatedProfiler
from optimize.models import CaptureResult, Goal, SettingsCatalog
from optimize.telemetry.simulated import SimulatedCollector


@pytest.fixture()
def hardware():
    return SimulatedProfiler().profile()


@pytest.fixture()
def adapter(tmp_path):
    return SyntheticGameAdapter(tmp_path)


def _baseline():
    return {spec.key: spec.default for spec in AURORA_CATALOG.specs}


def test_search_finds_improvement_and_restores_original(adapter, hardware):
    config = SearchConfig(runs_per_config=2, max_trials=5, capture_seconds=5.0)
    report = run_search(adapter, SimulatedCollector(AURORA_CATALOG), hardware,
                        Goal.BALANCED, config)

    assert report.recommendation == "apply-candidate"
    assert report.best_settings is not None
    assert report.best_score > report.baseline_score
    assert report.bottleneck == "gpu"

    kept = [t for t in report.trials if t.verdict == "kept"]
    assert kept, "at least one candidate must be a measured improvement"
    assert all(t.significant for t in kept)

    # The loop must never leave a trial configuration behind.
    assert adapter.read_settings() == _baseline()
    # Raw frame times are retained for every run (README: keep raw samples).
    assert report.raw_runs and all(r.frame_times_ms for r in report.raw_runs)


def test_search_respects_trial_budget(adapter, hardware):
    config = SearchConfig(runs_per_config=2, max_trials=3, capture_seconds=5.0)
    report = run_search(adapter, SimulatedCollector(AURORA_CATALOG), hardware,
                        Goal.BALANCED, config)
    # 3 single-setting trials max, plus at most one combined trial.
    assert len(report.trials) <= 4


def test_search_stops_early_when_target_reached(adapter, hardware):
    config = SearchConfig(runs_per_config=2, max_trials=6, capture_seconds=5.0,
                          fps_target=75.0)
    report = run_search(adapter, SimulatedCollector(AURORA_CATALOG), hardware,
                        Goal.BALANCED, config)
    assert any("target" in note for note in report.notes)


def test_visual_quality_goal_rejects_quality_regression(adapter, hardware):
    config = SearchConfig(runs_per_config=2, max_trials=5, capture_seconds=5.0)
    report = run_search(adapter, SimulatedCollector(AURORA_CATALOG), hardware,
                        Goal.VISUAL_QUALITY, config)
    # Every cheapening candidate loses more quality score than it gains,
    # so the correct recommendation under this goal is no-change.
    assert report.recommendation == "no-change"
    assert report.best_settings is None
    assert adapter.read_settings() == _baseline()


class _RegressionCollector(SimulatedCollector):
    """Simulates a game where dropping resolution scale backfires (worse pacing)."""

    def __init__(self, catalog: SettingsCatalog) -> None:
        super().__init__(catalog)
        self.saw_regressed_config = False

    def run(self, settings, hardware, seconds=20.0, seed=0):
        capture = super().run(settings, hardware, seconds, seed)
        if str(settings.get("resolution_scale")) == "50":
            self.saw_regressed_config = True
            degraded = tuple(ft * 1.5 for ft in capture.frame_times_ms)
            capture = CaptureResult(
                frame_times_ms=degraded,
                cpu_util_pct=capture.cpu_util_pct,
                gpu_util_pct=capture.gpu_util_pct,
                vram_used_mb=capture.vram_used_mb,
            )
        return capture


def test_regression_is_rejected_and_not_applied(adapter, hardware):
    collector = _RegressionCollector(AURORA_CATALOG)
    report = run_search(adapter, collector, hardware, Goal.BALANCED,
                        SearchConfig(runs_per_config=2, max_trials=5,
                                     capture_seconds=5.0))
    assert collector.saw_regressed_config
    scale_trials = [
        t for t in report.trials if "resolution_scale" in t.candidate.changes
        and t.candidate.changes["resolution_scale"] == "50"
    ]
    for trial in scale_trials:
        assert trial.verdict == "rejected"
        assert trial.gain_pct < 0
    # Whatever was recommended, the on-disk config is back at the baseline.
    assert adapter.read_settings() == _baseline()


def test_combined_trial_only_from_individually_winning_settings(adapter, hardware):
    config = SearchConfig(runs_per_config=2, max_trials=6, capture_seconds=5.0)
    report = run_search(adapter, SimulatedCollector(AURORA_CATALOG), hardware,
                        Goal.BALANCED, config)
    combos = [t for t in report.trials if t.candidate.label.startswith("combined")]
    if combos:
        kept_keys = {
            next(iter(t.candidate.changes))
            for t in report.trials
            if t.verdict == "kept" and not t.candidate.label.startswith("combined")
        }
        assert set(combos[0].candidate.changes) <= kept_keys
