import pytest

from optimize.adapters.synthetic import AURORA_CATALOG
from optimize.engine.bottleneck import estimate_bottleneck
from optimize.engine.candidates import combined_candidate, generate_candidates
from optimize.engine.scoring import score_run, settings_quality
from optimize.models import BenchmarkMetrics, Candidate, CaptureResult, Goal


def _baseline_settings():
    return {spec.key: spec.default for spec in AURORA_CATALOG.specs}


# ---- bottleneck --------------------------------------------------------------


def test_bottleneck_gpu_bound():
    captures = [CaptureResult(frame_times_ms=(10.0,), cpu_util_pct=60.0, gpu_util_pct=97.0)]
    assert estimate_bottleneck(captures, vram_total_mb=8192) == "gpu"


def test_bottleneck_cpu_bound():
    captures = [CaptureResult(frame_times_ms=(10.0,), cpu_util_pct=98.0, gpu_util_pct=55.0)]
    assert estimate_bottleneck(captures, vram_total_mb=8192) == "cpu"


def test_bottleneck_memory_pressure():
    captures = [
        CaptureResult(frame_times_ms=(10.0,), cpu_util_pct=50.0, gpu_util_pct=70.0,
                      vram_used_mb=7900)
    ]
    assert estimate_bottleneck(captures, vram_total_mb=8192) == "memory"


def test_bottleneck_unknown_without_telemetry():
    captures = [CaptureResult(frame_times_ms=(10.0,))]
    assert estimate_bottleneck(captures) == "unknown"


def test_bottleneck_unknown_when_balanced():
    captures = [CaptureResult(frame_times_ms=(10.0,), cpu_util_pct=75.0, gpu_util_pct=78.0)]
    assert estimate_bottleneck(captures) == "unknown"


# ---- candidates --------------------------------------------------------------


def test_candidates_only_cheaper_values():
    current = _baseline_settings()
    candidates = generate_candidates(AURORA_CATALOG, current)
    assert candidates, "defaults are near the top tier, cheaper values must exist"
    for cand in candidates:
        key = next(iter(cand.changes))
        spec = AURORA_CATALOG.spec(key)
        old = spec.spec_for(current[key])
        new = spec.spec_for(cand.changes[key])
        assert (new.gpu_ms + new.cpu_ms) < (old.gpu_ms + old.cpu_ms)


def test_candidates_respect_limit():
    candidates = generate_candidates(AURORA_CATALOG, _baseline_settings(), limit=3)
    assert len(candidates) == 3


def test_candidates_prioritize_bottleneck():
    candidates = generate_candidates(
        AURORA_CATALOG, _baseline_settings(), bottleneck="gpu", limit=6
    )
    specs = [AURORA_CATALOG.spec(next(iter(c.changes))) for c in candidates[:3]]
    assert all(spec.bottleneck == "gpu" for spec in specs)


def test_candidates_empty_when_already_minimal():
    minimal = {spec.key: spec.values[0].value for spec in AURORA_CATALOG.specs}
    assert generate_candidates(AURORA_CATALOG, minimal) == []


def test_combined_candidate_merges_winners():
    base = _baseline_settings()
    winners = [
        Candidate(label="a", changes={"resolution_scale": "80"}),
        Candidate(label="b", changes={"shadow_quality": "medium"}),
        Candidate(label="a-again", changes={"resolution_scale": "50"}),  # dup key
    ]
    combo = combined_candidate(AURORA_CATALOG, base, winners)
    assert combo is not None
    assert combo.changes == {"resolution_scale": "50", "shadow_quality": "medium"}
    assert combo.expected_gain_ms > 0


def test_combined_candidate_needs_two_distinct_settings():
    winners = [Candidate(label="a", changes={"resolution_scale": "80"})]
    assert combined_candidate(AURORA_CATALOG, _baseline_settings(), winners) is None


# ---- scoring -----------------------------------------------------------------


def _metrics(avg_fps: float, consistency: float = 0.9) -> BenchmarkMetrics:
    return BenchmarkMetrics(
        avg_fps=avg_fps, fps_1p_low=avg_fps * 0.8, mean_frame_time_ms=1000 / avg_fps,
        p99_frame_time_ms=1.2 * 1000 / avg_fps, std_frame_time_ms=1.0,
        consistency=consistency, spike_ratio=0.0, frame_count=1000, duration_s=15.0,
    )


def test_score_normalizes_fps_against_target():
    low = score_run(_metrics(60.0), 0.8, Goal.BALANCED, target_fps=120.0)
    high = score_run(_metrics(120.0), 0.8, Goal.BALANCED, target_fps=120.0)
    assert low.components["fps"] == pytest.approx(0.5)
    assert high.components["fps"] == pytest.approx(1.0)
    assert high.total > low.total


def test_score_fps_capped_at_target():
    at = score_run(_metrics(144.0), 0.8, Goal.BALANCED, target_fps=144.0)
    beyond = score_run(_metrics(200.0), 0.8, Goal.BALANCED, target_fps=144.0)
    assert at.total == beyond.total


def test_missing_metrics_are_reported_not_scored_zero():
    result = score_run(_metrics(80.0), 0.8, Goal.COMPETITIVE, target_fps=144.0)
    assert "latency" in result.missing
    assert "latency" not in result.components


def test_competitive_goal_weights_consistency_over_raw_fps():
    smooth_slow = score_run(_metrics(70.0, consistency=0.98), 0.8,
                            Goal.COMPETITIVE, target_fps=144.0)
    choppy_fast = score_run(_metrics(90.0, consistency=0.60), 0.8,
                            Goal.COMPETITIVE, target_fps=144.0)
    assert smooth_slow.total > choppy_fast.total


def test_quality_floor_is_a_hard_constraint():
    below = score_run(_metrics(120.0), 0.50, Goal.VISUAL_QUALITY, target_fps=144.0)
    assert below.quality_floor_ok is False
    above = score_run(_metrics(120.0), 0.90, Goal.VISUAL_QUALITY, target_fps=144.0)
    assert above.quality_floor_ok is True


def test_settings_quality_bounds():
    baseline = settings_quality(AURORA_CATALOG, _baseline_settings())
    minimal = settings_quality(
        AURORA_CATALOG,
        {spec.key: spec.values[0].value for spec in AURORA_CATALOG.specs},
    )
    assert 0.0 < minimal < baseline <= 1.0
