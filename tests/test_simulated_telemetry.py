import pytest

from optimize.adapters.synthetic import AURORA_CATALOG
from optimize.hardware.profiler import SimulatedProfiler
from optimize.telemetry.metrics import compute_metrics
from optimize.telemetry.simulated import SimulatedCollector


@pytest.fixture()
def collector():
    return SimulatedCollector(AURORA_CATALOG)


@pytest.fixture()
def hardware():
    return SimulatedProfiler().profile()


def _settings(**overrides):
    base = {spec.key: spec.default for spec in AURORA_CATALOG.specs}
    base.update(overrides)
    return base


def test_reproducible_from_seed(collector, hardware):
    a = collector.run(_settings(), hardware, seconds=5.0, seed=42)
    b = collector.run(_settings(), hardware, seconds=5.0, seed=42)
    assert a.frame_times_ms == b.frame_times_ms


def test_cheaper_settings_improve_fps(collector, hardware):
    baseline = compute_metrics(collector.run(_settings(), hardware, 5.0, seed=1))
    cheaper = compute_metrics(
        collector.run(_settings(resolution_scale="50", shadow_quality="low"), hardware, 5.0, seed=1)
    )
    assert cheaper.avg_fps > baseline.avg_fps * 1.2


def test_non_bottleneck_side_change_barely_helps(collector, hardware):
    """Baseline is GPU-bound: CPU-side reductions only shrink the overlap
    penalty (<5%), while a GPU-side reduction is the real lever (>20%)."""
    baseline = compute_metrics(collector.run(_settings(), hardware, 5.0, seed=1))
    cpu_reduced = compute_metrics(
        collector.run(_settings(crowd_density="low", draw_distance="medium"), hardware, 5.0, seed=1)
    )
    gpu_reduced = compute_metrics(
        collector.run(_settings(resolution_scale="50"), hardware, 5.0, seed=1)
    )
    cpu_gain = (cpu_reduced.avg_fps - baseline.avg_fps) / baseline.avg_fps
    gpu_gain = (gpu_reduced.avg_fps - baseline.avg_fps) / baseline.avg_fps
    assert cpu_gain < 0.05
    assert gpu_gain > 0.20


def test_reports_utilization_pointing_at_gpu(collector, hardware):
    capture = collector.run(_settings(), hardware, 5.0, seed=1)
    assert capture.gpu_util_pct > capture.cpu_util_pct
    assert capture.gpu_util_pct >= 85.0


def test_vram_overflow_adds_spikes(collector, hardware):
    normal = compute_metrics(
        collector.run(_settings(texture_quality="high"), hardware, 5.0, seed=3)
    )
    # Simulated card has 6144 MB; ultra textures push past it.
    thrash = compute_metrics(
        collector.run(_settings(texture_quality="ultra"), hardware, 5.0, seed=3)
    )
    assert thrash.spike_ratio > normal.spike_ratio


def test_respects_refresh_rate_cap(collector, hardware):
    cheap = collector.run(
        _settings(resolution_scale="50", shadow_quality="low", anti_aliasing="off",
                  texture_quality="medium", draw_distance="medium", crowd_density="low"),
        hardware, 5.0, seed=5,
    )
    best = compute_metrics(cheap)
    assert best.avg_fps <= hardware.refresh_rate_hz * 1.01
