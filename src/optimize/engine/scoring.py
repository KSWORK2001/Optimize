"""Weighted scoring and hard constraints (README: 'Performance metrics and scoring').

Implements the conceptual score formula with per-goal weights. Metrics that
are unavailable in this prototype (latency, power, thermal) are treated as
missing data: their weight is dropped and the remaining weights are
re-normalized, and the omission is reported — never silently scored as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from optimize.models import BenchmarkMetrics, Goal, SettingsCatalog, SettingsState

# Component weights per goal. 'latency', 'power', and 'thermal' are listed for
# completeness; they stay None in this prototype until telemetry exists.
GOAL_WEIGHTS: dict[Goal, dict[str, float]] = {
    Goal.COMPETITIVE: {"fps": 0.30, "consistency": 0.45, "quality": 0.15, "latency": 0.10},
    Goal.HIGH_FPS: {"fps": 0.60, "consistency": 0.20, "quality": 0.20},
    Goal.BALANCED: {"fps": 0.40, "consistency": 0.30, "quality": 0.30},
    Goal.VISUAL_QUALITY: {"fps": 0.15, "consistency": 0.25, "quality": 0.60},
}

# Default minimum estimated image quality per goal (hard constraint, the
# user's tolerance floor; overridable on the command line).
DEFAULT_QUALITY_FLOOR: dict[Goal, float] = {
    Goal.COMPETITIVE: 0.55,
    Goal.HIGH_FPS: 0.55,
    Goal.BALANCED: 0.70,
    Goal.VISUAL_QUALITY: 0.85,
}


@dataclass
class ScoreResult:
    total: float
    components: dict[str, float] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    quality_floor_ok: bool = True


def settings_quality(catalog: SettingsCatalog, settings: SettingsState) -> float:
    """Estimated image quality of a configuration (0..1), equally weighted
    across settings. A design sketch, not a validated perceptual metric."""
    scores = []
    for spec in catalog.specs:
        value = str(settings.get(spec.key, spec.default))
        scores.append(spec.spec_for(value).quality)
    return sum(scores) / len(scores) if scores else 1.0


def score_run(
    metrics: BenchmarkMetrics,
    quality: float,
    goal: Goal,
    target_fps: float,
    quality_floor: float | None = None,
) -> ScoreResult:
    """Score one benchmark run for the selected goal.

    fps is normalized against target_fps (default: the display refresh rate),
    capped at 1.0 so overshooting a target adds nothing; consistency and
    quality are already 0..1.
    """
    weights = GOAL_WEIGHTS[goal]
    floor = DEFAULT_QUALITY_FLOOR[goal] if quality_floor is None else quality_floor

    available: dict[str, float] = {
        "fps": min(1.0, metrics.avg_fps / target_fps) if target_fps > 0 else 0.0,
        "consistency": max(0.0, min(1.0, metrics.consistency)),
        "quality": max(0.0, min(1.0, quality)),
    }
    missing = [name for name in weights if name not in available]

    used = {name: weight for name, weight in weights.items() if name in available}
    weight_sum = sum(used.values())
    total = (
        sum(used[name] * available[name] for name in used) / weight_sum
        if weight_sum > 0
        else 0.0
    )

    return ScoreResult(
        total=round(total, 4),
        components={k: round(v, 4) for k, v in available.items()},
        missing=missing,
        quality_floor_ok=quality >= floor,
    )
