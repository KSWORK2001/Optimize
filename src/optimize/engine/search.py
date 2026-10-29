"""The bounded optimization loop (README: 'Optimization loop' diagram).

baseline -> estimate bottleneck -> ranked candidates -> one-at-a-time trials
-> keep/reject/inconclusive -> optional combined trial -> recommend or
no-change. Every trial is restored to the baseline configuration afterward;
nothing is applied by this module. Applying the recommendation is the
orchestrator's job and requires explicit user approval.

Stop conditions: single-trial budget exhausted, FPS target reached, or no
kept improvements.
"""

from __future__ import annotations

from dataclasses import dataclass

from optimize.adapters.base import GameAdapter
from optimize.engine.bottleneck import estimate_bottleneck
from optimize.engine.candidates import combined_candidate, generate_candidates
from optimize.engine.scoring import ScoreResult, score_run, settings_quality
from optimize.models import (
    BenchmarkMetrics,
    Candidate,
    CaptureResult,
    Goal,
    HardwareProfile,
    OptimizationReport,
    RawRun,
    TrialResult,
)
from optimize.telemetry.collector import BenchmarkCollector
from optimize.telemetry.metrics import compare_runs, compute_metrics

_EPS = 1e-9


@dataclass(frozen=True)
class SearchConfig:
    runs_per_config: int = 2
    max_trials: int = 6          # single-setting trials; combined trial is +1
    capture_seconds: float = 15.0
    min_gain_pct: float = 3.0    # absolute significance floor
    seed_base: int = 1000
    fps_target: float | None = None      # default: display refresh rate
    quality_floor: float | None = None   # default: per-goal tolerance


def run_search(
    adapter: GameAdapter,
    collector: BenchmarkCollector,
    hardware: HardwareProfile,
    goal: Goal,
    config: SearchConfig | None = None,
) -> OptimizationReport:
    cfg = config or SearchConfig()
    catalog = adapter.catalog()
    baseline_settings = dict(adapter.read_settings())

    report = OptimizationReport(
        game_id=catalog.game_id,
        goal=goal,
        hardware=hardware,
        baseline_settings=baseline_settings,
    )

    def capture(
        settings: dict[str, str], label: str, seed_block: int
    ) -> tuple[list[BenchmarkMetrics], list[CaptureResult]]:
        captures = [
            collector.run(
                settings, hardware, cfg.capture_seconds, cfg.seed_base + seed_block + i
            )
            for i in range(cfg.runs_per_config)
        ]
        metrics = [compute_metrics(c) for c in captures]
        for cap, met in zip(captures, metrics, strict=True):
            report.raw_runs.append(RawRun(label, dict(settings), met, cap.frame_times_ms))
        return metrics, captures

    # ---- Baseline -----------------------------------------------------------
    baseline_metrics, baseline_caps = capture(baseline_settings, "baseline", 0)
    report.baseline_metrics = baseline_metrics
    report.bottleneck = estimate_bottleneck(baseline_caps, hardware.vram_mb or None)
    report.notes.append(f"bottleneck estimate: {report.bottleneck}")

    target_fps = float(cfg.fps_target or hardware.refresh_rate_hz or 60)
    report.notes.append(f"fps target: {target_fps:.0f}")

    baseline_quality = settings_quality(catalog, baseline_settings)
    baseline_score = _avg_score(baseline_metrics, baseline_quality, goal, target_fps, cfg)
    report.baseline_score = baseline_score.total
    report.baseline_quality = baseline_quality
    if baseline_score.missing:
        report.notes.append(
            "metrics not yet collected (excluded from score): "
            + ", ".join(baseline_score.missing)
        )

    # ---- Ranked candidate trials --------------------------------------------
    candidates = generate_candidates(
        catalog, baseline_settings, report.bottleneck, limit=cfg.max_trials
    )
    kept: list[TrialResult] = []

    def evaluate(
        cand_label: str, changes: dict[str, str], seed_block: int
    ) -> TrialResult:
        trial_settings = {**baseline_settings, **changes}
        trial_quality = settings_quality(catalog, trial_settings)
        adapter.apply_changes(changes)
        try:
            trial_metrics, _caps = capture(trial_settings, cand_label, seed_block)
        finally:
            # Always return to the baseline configuration before the next step.
            adapter.apply_changes({k: baseline_settings[k] for k in changes})

        trial_score = _avg_score(trial_metrics, trial_quality, goal, target_fps, cfg)
        comparison = compare_runs(baseline_metrics, trial_metrics, cfg.min_gain_pct)

        if any(m.crashed for m in trial_metrics):
            verdict, reason = "rejected", "benchmark crashed or produced invalid data"
        elif not trial_score.quality_floor_ok:
            verdict, reason = (
                "rejected",
                f"estimated image quality {trial_quality:.2f} is below the "
                f"tolerance floor for this goal",
            )
        elif not comparison.significant:
            verdict, reason = "inconclusive", comparison.inconclusive_reason
        elif trial_score.total <= baseline_score.total + _EPS:
            verdict, reason = (
                "rejected",
                "measured gain does not improve the weighted score for this goal",
            )
        else:
            verdict, reason = "kept", comparison.inconclusive_reason

        return TrialResult(
            candidate=Candidate(label=cand_label, changes=changes),
            settings=trial_settings,
            metrics=_aggregate(trial_metrics),
            score=trial_score.total,
            quality=trial_quality,
            verdict=verdict,
            reason=reason,
            gain_pct=comparison.gain_pct,
            significant=comparison.significant,
        )

    for index, cand in enumerate(candidates):
        if index >= cfg.max_trials:
            break
        result = evaluate(cand.label, cand.changes, 100 * (index + 1))
        report.trials.append(result)
        if result.verdict == "kept":
            kept.append(result)
            best_fps = max(m.avg_fps for m in [result.metrics])
            if best_fps >= target_fps:
                report.notes.append(
                    f"target {target_fps:.0f} FPS reached at trial {index + 1}; stopping early"
                )
                break

    # ---- One combined trial of the individually winning settings -------------
    if len(kept) >= 2:
        combo = combined_candidate(
            catalog, baseline_settings, [t.candidate for t in kept]
        )
        if combo is not None:
            result = evaluate(combo.label, combo.changes, 9900)
            report.trials.append(result)
            if result.verdict == "kept":
                kept.append(result)

    best = max(kept, key=lambda t: t.score) if kept else None
    if best is not None and best.score > baseline_score.total + _EPS:
        report.best_settings = best.settings
        report.best_metrics = best.metrics
        report.best_score = best.score
        report.recommendation = "apply-candidate"
    else:
        report.recommendation = "no-change"
        report.notes.append(
            "no candidate beat the baseline score under this goal's constraints; "
            "the original configuration is kept"
        )
    return report


def _avg_score(
    metrics: list[BenchmarkMetrics],
    quality: float,
    goal: Goal,
    target_fps: float,
    cfg: SearchConfig,
) -> ScoreResult:
    results = [
        score_run(m, quality, goal, target_fps, cfg.quality_floor) for m in metrics
    ]
    return ScoreResult(
        total=sum(r.total for r in results) / len(results),
        components=results[0].components,
        missing=results[0].missing,
        quality_floor_ok=all(r.quality_floor_ok for r in results),
    )


def _aggregate(metrics: list[BenchmarkMetrics]) -> BenchmarkMetrics:
    """Representative metrics for a configuration: recompute over all frames."""
    frame_count = sum(m.frame_count for m in metrics)
    if frame_count == 0:
        return metrics[0]
    duration = sum(m.duration_s for m in metrics)
    return BenchmarkMetrics(
        avg_fps=1000.0 / (sum(m.mean_frame_time_ms * m.frame_count for m in metrics) / frame_count),
        fps_1p_low=min(m.fps_1p_low for m in metrics),
        mean_frame_time_ms=sum(m.mean_frame_time_ms * m.frame_count for m in metrics) / frame_count,
        p99_frame_time_ms=max(m.p99_frame_time_ms for m in metrics),
        std_frame_time_ms=sum(m.std_frame_time_ms * m.frame_count for m in metrics) / frame_count,
        consistency=sum(m.consistency * m.frame_count for m in metrics) / frame_count,
        spike_ratio=sum(m.spike_ratio * m.frame_count for m in metrics) / frame_count,
        frame_count=frame_count,
        duration_s=duration,
        crashed=any(m.crashed for m in metrics),
    )
