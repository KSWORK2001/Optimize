"""Deterministic simulated collector for development, CI, and the demo.

Implements the same BenchmarkCollector interface as the PresentMon wrapper,
but derives frame times from an explicit performance model driven by the
game's settings catalog:

    gpu_frame_ms = base + sum(gpu_ms of each setting value)
    cpu_frame_ms = base + sum(cpu_ms of each setting value)
    frame_ms     = max(gpu, cpu) + overlap_penalty * min(gpu, cpu)

The max() models a pipelined renderer: the slower side bounds the frame rate,
so improvements on the non-bottleneck side correctly produce no gain. If the
estimated VRAM footprint exceeds the hardware budget, texture thrashing adds
frame-time spikes — the kind of regression the optimizer must reject.

Reported CPU/GPU utilizations are the busy fractions of each side, which is
what the bottleneck estimator consumes. Every run is reproducible from its
seed.
"""

from __future__ import annotations

import random
from collections.abc import Mapping

from optimize.models import CaptureResult, HardwareProfile, SettingsCatalog
from optimize.telemetry.collector import BenchmarkCollector

GPU_BASE_MS = 0.8
CPU_BASE_MS = 2.2
OVERLAP_PENALTY = 0.15
VRAM_BASE_MB = 3200
JITTER_SIGMA = 0.04          # relative per-frame jitter
SPIKE_PROBABILITY = 0.003    # background hitch probability per frame
THRASH_SPIKE_PROBABILITY = 0.05
SPIKE_MIN_MULTIPLIER = 1.8
SPIKE_MAX_MULTIPLIER = 3.8
MIN_FRAME_TIME_MS = 0.5


def estimate_frames(
    catalog: SettingsCatalog, settings: Mapping[str, str]
) -> tuple[float, float, int]:
    """Return (gpu_frame_ms, cpu_frame_ms, vram_used_mb) for a configuration."""
    gpu_ms, cpu_ms, vram_mb = GPU_BASE_MS, CPU_BASE_MS, VRAM_BASE_MB
    for spec in catalog.specs:
        value = spec.spec_for(str(settings.get(spec.key, spec.default)))
        gpu_ms += value.gpu_ms
        cpu_ms += value.cpu_ms
        vram_mb += value.vram_mb
    return gpu_ms, cpu_ms, vram_mb


class SimulatedCollector(BenchmarkCollector):
    """Reproducible stand-in for real telemetry, driven by the settings catalog."""

    def __init__(self, catalog: SettingsCatalog) -> None:
        self.catalog = catalog

    def run(
        self,
        settings: Mapping[str, str],
        hardware: HardwareProfile,
        seconds: float = 20.0,
        seed: int = 0,
    ) -> CaptureResult:
        rng = random.Random(seed)
        gpu_ms, cpu_ms, vram_mb = estimate_frames(self.catalog, settings)

        thrashing = vram_mb > hardware.vram_mb
        if thrashing:
            gpu_ms *= 1.35

        frame_ms = max(gpu_ms, cpu_ms) + OVERLAP_PENALTY * min(gpu_ms, cpu_ms)
        # VSync: the display cannot show frames faster than the refresh rate.
        frame_ms = max(frame_ms, 1000.0 / max(1, hardware.refresh_rate_hz))

        spike_p = THRASH_SPIKE_PROBABILITY if thrashing else SPIKE_PROBABILITY

        frames: list[float] = []
        elapsed_ms = 0.0
        target_ms = seconds * 1000.0
        while elapsed_ms < target_ms:
            sample = rng.gauss(frame_ms, JITTER_SIGMA * frame_ms)
            if rng.random() < spike_p:
                sample *= rng.uniform(SPIKE_MIN_MULTIPLIER, SPIKE_MAX_MULTIPLIER)
            sample = max(MIN_FRAME_TIME_MS, sample)
            frames.append(sample)
            elapsed_ms += sample

        return CaptureResult(
            frame_times_ms=tuple(frames),
            cpu_util_pct=round(100.0 * cpu_ms / frame_ms, 1),
            gpu_util_pct=round(100.0 * gpu_ms / frame_ms, 1),
            vram_used_mb=vram_mb,
        )
