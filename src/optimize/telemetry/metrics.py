"""Frame-time statistics and run-to-run variance checks.

README requirements covered here:
- 1% low FPS with a documented calculation method.
- Frame-time distribution and spikes (raw samples are retained upstream).
- 'Treat results as inconclusive if benchmark variance is larger than the
  observed gain.'
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from optimize.models import BenchmarkMetrics, CaptureResult


def compute_metrics(capture: CaptureResult) -> BenchmarkMetrics:
    """Aggregate one capture into comparable metrics.

    1% low method: the worst 1% of frame times (highest ms) are averaged and
    inverted to FPS. With fewer than 100 samples the worst single frame is
    used, which is the degenerate case of the same definition.
    """
    frames = list(capture.frame_times_ms)
    if not frames:
        return BenchmarkMetrics(
            avg_fps=0.0, fps_1p_low=0.0, mean_frame_time_ms=0.0,
            p99_frame_time_ms=0.0, std_frame_time_ms=0.0, consistency=0.0,
            spike_ratio=1.0, frame_count=0, duration_s=0.0,
            crashed=capture.crashed,
        )

    mean_ms = statistics.fmean(frames)
    std_ms = statistics.pstdev(frames) if len(frames) > 1 else 0.0
    ordered = sorted(frames)
    tail_count = max(1, len(frames) // 100)
    worst_tail = ordered[-tail_count:]
    worst_avg_ms = statistics.fmean(worst_tail)

    p99_index = min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)
    median_ms = statistics.median(frames)

    # Dispersion-based consistency: 1.0 means perfectly flat frame times.
    consistency = 0.0 if mean_ms <= 0 else max(0.0, 1.0 - std_ms / mean_ms)
    spike_threshold = 2.0 * median_ms
    spikes = sum(1 for ft in frames if ft > spike_threshold)

    return BenchmarkMetrics(
        avg_fps=1000.0 / mean_ms,
        fps_1p_low=1000.0 / worst_avg_ms,
        mean_frame_time_ms=mean_ms,
        p99_frame_time_ms=ordered[p99_index],
        std_frame_time_ms=std_ms,
        consistency=consistency,
        spike_ratio=spikes / len(frames),
        frame_count=len(frames),
        duration_s=sum(frames) / 1000.0,
        crashed=capture.crashed,
    )


@dataclass(frozen=True)
class RunComparison:
    """Comparison of a candidate against the baseline across repeated runs."""

    baseline_avg_fps: float
    candidate_avg_fps: float
    gain_pct: float
    noise_pct: float          # run-to-run variation of the average FPS
    significant: bool
    inconclusive_reason: str = ""


def _cv_pct(values: list[float]) -> float:
    """Coefficient of variation within one group of run averages, in percent."""
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return statistics.pstdev(values) / mean * 100.0 if mean > 0 else 0.0


def compare_runs(
    baseline: list[BenchmarkMetrics],
    candidate: list[BenchmarkMetrics],
    min_gain_pct: float = 3.0,
    noise_factor: float = 2.0,
) -> RunComparison:
    """Decide whether an observed gain is larger than natural benchmark variance.

    The noise band is `noise_factor` times the larger of the two groups'
    within-group coefficients of variation of per-run average FPS. (Pooling
    both groups would inflate the estimate whenever the candidate genuinely
    differs from the baseline, masking real regressions.) A gain must also
    clear an absolute floor (`min_gain_pct`) so tiny fractional gains on
    ultra-stable systems are not over-read; with a single run per group no
    variance can be estimated, so only the floor applies.
    """
    if not baseline or not candidate:
        return RunComparison(0.0, 0.0, 0.0, 0.0, False, "missing runs")

    base_avgs = [m.avg_fps for m in baseline]
    cand_avgs = [m.avg_fps for m in candidate]
    base_avg = statistics.fmean(base_avgs)
    cand_avg = statistics.fmean(cand_avgs)

    if base_avg <= 0:
        return RunComparison(0.0, cand_avg, 0.0, 0.0, False, "invalid baseline")

    gain_pct = (cand_avg - base_avg) / base_avg * 100.0

    noise_pct = noise_factor * max(_cv_pct(base_avgs), _cv_pct(cand_avgs))
    threshold = max(min_gain_pct, noise_pct)

    significant = abs(gain_pct) >= threshold
    reason = ""
    if not significant:
        reason = (
            f"gain {gain_pct:+.1f}% is within the noise band "
            f"(±{threshold:.1f}%); treat as inconclusive"
        )
    return RunComparison(base_avg, cand_avg, gain_pct, noise_pct, significant, reason)
