"""Likely-bottleneck estimation from telemetry (README: optimization loop step)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from optimize.models import CaptureResult

GPU_BOUND_UTIL = 90.0       # percent, sustained
UTIL_GAP = 10.0             # bottleneck side must lead by this much
VRAM_PRESSURE = 0.95        # used/total at which memory is the constraint


def estimate_bottleneck(
    captures: Sequence[CaptureResult],
    vram_total_mb: int | None = None,
) -> str:
    """Classify the likely bottleneck as gpu / cpu / memory / unknown.

    Heuristic, clearly labeled as an estimate: high sustained utilization on
    one side while the other idles points at that side; near-full VRAM points
    at memory. Missing telemetry yields 'unknown' rather than a guess.
    """
    cpu_samples = [c.cpu_util_pct for c in captures if c.cpu_util_pct is not None]
    gpu_samples = [c.gpu_util_pct for c in captures if c.gpu_util_pct is not None]
    vram_samples = [c.vram_used_mb for c in captures if c.vram_used_mb is not None]

    if vram_total_mb and vram_samples and max(vram_samples) / vram_total_mb >= VRAM_PRESSURE:
        return "memory"

    if not cpu_samples or not gpu_samples:
        return "unknown"

    cpu = statistics.fmean(cpu_samples)
    gpu = statistics.fmean(gpu_samples)

    if gpu >= GPU_BOUND_UTIL and gpu >= cpu + UTIL_GAP:
        return "gpu"
    if cpu >= GPU_BOUND_UTIL and cpu >= gpu + UTIL_GAP:
        return "cpu"
    return "unknown"
