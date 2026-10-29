import math

import pytest

from optimize.models import BenchmarkMetrics, CaptureResult
from optimize.telemetry.metrics import compare_runs, compute_metrics


def test_metrics_flat_frame_times():
    capture = CaptureResult(frame_times_ms=(10.0,) * 1000)
    m = compute_metrics(capture)
    assert m.avg_fps == pytest.approx(100.0)
    assert m.fps_1p_low == pytest.approx(100.0)  # all frames identical
    assert m.consistency == pytest.approx(1.0)
    assert m.spike_ratio == pytest.approx(0.0)
    assert m.crashed is False


def test_metrics_one_percent_low_method():
    # 990 frames at 10 ms and 10 frames at 50 ms: worst 1% averages 50 ms.
    frames = [10.0] * 990 + [50.0] * 10
    m = compute_metrics(CaptureResult(frame_times_ms=tuple(frames)))
    assert m.frame_count == 1000
    assert m.fps_1p_low == pytest.approx(1000.0 / 50.0)
    assert m.avg_fps == pytest.approx(1000.0 / (10.0 * 0.99 + 50.0 * 0.01))


def test_metrics_small_sample_uses_worst_frame():
    m = compute_metrics(CaptureResult(frame_times_ms=(10.0, 10.0, 40.0)))
    assert m.fps_1p_low == pytest.approx(1000.0 / 40.0)


def test_metrics_spikes_counted_against_median():
    frames = [10.0] * 100 + [31.0] * 3  # 31 ms > 2x median (10 ms)
    m = compute_metrics(CaptureResult(frame_times_ms=tuple(frames)))
    assert m.spike_ratio == pytest.approx(3.0 / 103)


def test_metrics_empty_capture():
    m = compute_metrics(CaptureResult(frame_times_ms=()))
    assert m.avg_fps == 0.0
    assert m.frame_count == 0


def test_metrics_crash_flag_propagates():
    m = compute_metrics(CaptureResult(frame_times_ms=(10.0,) * 10, crashed=True))
    assert m.crashed is True


def _run(avg_fps: float) -> BenchmarkMetrics:
    frame_ms = 1000.0 / avg_fps
    return BenchmarkMetrics(
        avg_fps=avg_fps, fps_1p_low=avg_fps * 0.8, mean_frame_time_ms=frame_ms,
        p99_frame_time_ms=frame_ms * 1.2, std_frame_time_ms=frame_ms * 0.05,
        consistency=0.95, spike_ratio=0.0, frame_count=1000,
        duration_s=1.0 / avg_fps * 1000,
    )


def test_compare_runs_significant_gain():
    baseline = [_run(60.0), _run(60.5)]
    candidate = [_run(70.0), _run(70.5)]
    cmp = compare_runs(baseline, candidate)
    assert cmp.significant is True
    assert cmp.gain_pct == pytest.approx(100.0 * (70.25 - 60.25) / 60.25, abs=0.5)


def test_compare_runs_gain_within_noise_is_inconclusive():
    baseline = [_run(60.0), _run(62.0)]
    candidate = [_run(60.5), _run(62.5)]  # ~0.8% gain, noise ~3x larger
    cmp = compare_runs(baseline, candidate, min_gain_pct=3.0)
    assert cmp.significant is False
    assert "inconclusive" in cmp.inconclusive_reason


def test_compare_runs_small_gain_below_absolute_floor():
    baseline = [_run(60.0), _run(60.0)]
    candidate = [_run(60.1), _run(60.1)]  # 0.17% gain, tiny variance
    cmp = compare_runs(baseline, candidate, min_gain_pct=3.0)
    assert cmp.significant is False


def test_compare_runs_requires_both_groups():
    cmp = compare_runs([], [_run(60.0)])
    assert cmp.significant is False
    assert cmp.inconclusive_reason == "missing runs"


def test_p99_frame_time_matches_definition():
    frames = [float(i) for i in range(1, 101)]  # 1..100 ms
    m = compute_metrics(CaptureResult(frame_times_ms=tuple(frames)))
    assert m.p99_frame_time_ms == pytest.approx(99.0)
    assert math.isfinite(m.consistency)
