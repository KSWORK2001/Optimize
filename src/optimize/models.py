"""Shared data model: hardware profile, benchmark metrics, goals, settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Goal(str, Enum):
    """Optimization target selected by the user (README: 'Proposed user experience' step 3)."""

    COMPETITIVE = "competitive"          # stable frame times and low latency
    HIGH_FPS = "high-fps"                # approach a chosen FPS target
    BALANCED = "balanced"                # trade off fps, quality, latency
    VISUAL_QUALITY = "visual-quality"    # preserve image quality


# A game configuration: setting key -> value, values always stored as strings.
SettingsState = Mapping[str, str]


@dataclass(frozen=True)
class HardwareProfile:
    """Only the information needed for optimization (README: 'Hardware profiler')."""

    cpu_model: str
    cpu_cores: int
    gpu_model: str
    vram_mb: int
    ram_gb: int
    display_resolution: str
    refresh_rate_hz: int
    os: str
    driver_version: str | None = None
    # Identifies where the data came from, e.g. "windows-cim" or "simulated".
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Aggregated statistics over one benchmark run.

    The 1% low is computed as: take the worst 1% of frame times (highest ms),
    average them, and convert to FPS (1000 / avg). This documents the method
    as required by README: 'Telemetry and benchmark collector'.
    """

    avg_fps: float
    fps_1p_low: float
    mean_frame_time_ms: float
    p99_frame_time_ms: float
    std_frame_time_ms: float
    consistency: float            # 0..1, derived from frame-time dispersion
    spike_ratio: float            # fraction of frames slower than 2x the median
    frame_count: int
    duration_s: float
    crashed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaptureResult:
    """Raw output of one telemetry capture, before aggregation."""

    frame_times_ms: tuple[float, ...]
    cpu_util_pct: float | None = None
    gpu_util_pct: float | None = None
    vram_used_mb: int | None = None
    crashed: bool = False


@dataclass(frozen=True)
class SettingValue:
    """One valid value of a game setting with its estimated costs.

    gpu_ms / cpu_ms are marginal frame-time costs at a reference hardware tier,
    used only to rank candidates (heuristic, not a performance guarantee).
    vram_mb is the approximate memory footprint of this value.
    quality is the estimated image-quality contribution (0..1).
    """

    value: str
    quality: float
    gpu_ms: float = 0.0
    cpu_ms: float = 0.0
    vram_mb: int = 0


@dataclass(frozen=True)
class SettingSpec:
    """Definition of one supported setting (README: 'Game adapter layer')."""

    key: str
    label: str
    values: tuple[SettingValue, ...]
    default: str
    restart_required: bool = False
    # Which resource this setting mostly loads: "gpu", "cpu", or "memory".
    bottleneck: str = "gpu"

    def spec_for(self, value: str) -> SettingValue:
        for v in self.values:
            if v.value == value:
                return v
        raise ValueError(
            f"{self.key}: {value!r} is not a supported value "
            f"(supported: {[v.value for v in self.values]})"
        )

    @property
    def value_names(self) -> list[str]:
        return [v.value for v in self.values]


@dataclass(frozen=True)
class SettingsCatalog:
    """The full, documented list of settings a game adapter supports."""

    game_id: str
    title: str
    specs: tuple[SettingSpec, ...]

    def spec(self, key: str) -> SettingSpec:
        for s in self.specs:
            if s.key == key:
                return s
        raise KeyError(f"unknown setting {key!r}")

    def validate(self, settings: Mapping[str, Any]) -> None:
        """Reject anything outside the supported list — never apply unvalidated values."""
        for key, value in settings.items():
            self.spec(key).spec_for(str(value))


@dataclass
class Candidate:
    """One bounded change to evaluate: current state + a single-setting (or small
    known-related group) modification."""

    label: str
    changes: dict[str, str]          # setting key -> proposed value
    expected_gpu_delta_ms: float = 0.0
    expected_cpu_delta_ms: float = 0.0

    @property
    def expected_gain_ms(self) -> float:
        return self.expected_gpu_delta_ms + self.expected_cpu_delta_ms


@dataclass
class TrialResult:
    """Outcome of benchmarking one candidate."""

    candidate: Candidate
    settings: dict[str, str]
    metrics: BenchmarkMetrics
    score: float
    quality: float
    verdict: str                      # "kept" | "rejected" | "inconclusive"
    reason: str = ""
    gain_pct: float = 0.0
    significant: bool = False


@dataclass(frozen=True)
class RawRun:
    """One stored benchmark run, raw samples included ('retain raw frame-time
    samples rather than relying only on average FPS')."""

    label: str
    settings: dict[str, str]
    metrics: BenchmarkMetrics
    frame_times_ms: tuple[float, ...]


@dataclass
class OptimizationReport:
    """Everything the user needs to see to audit an optimization session."""

    game_id: str
    goal: Goal
    hardware: HardwareProfile
    baseline_settings: dict[str, str]
    baseline_metrics: list[BenchmarkMetrics] = field(default_factory=list)
    baseline_score: float = 0.0
    baseline_quality: float = 1.0
    bottleneck: str = "unknown"
    trials: list[TrialResult] = field(default_factory=list)
    best_settings: dict[str, str] | None = None
    best_metrics: BenchmarkMetrics | None = None
    best_score: float = 0.0
    recommendation: str = "no-change"
    applied: bool = False
    backup_id: str | None = None
    notes: list[str] = field(default_factory=list)
    raw_runs: list[RawRun] = field(default_factory=list)
