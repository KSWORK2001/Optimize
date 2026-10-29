"""Command line interface for the optimization prototype.

Commands:
  hardware      show the detected hardware profile
  demo          full optimization loop against the synthetic game (any OS)
  optimize      run the loop for a registered game adapter
  benchmark     capture N baseline runs and report variance
  restore       one-click restore of a game configuration backup
  report        render a self-contained HTML report (charts, trials) for a session
  export        export a session profile as portable JSON
  apply-config  apply an exported profile (catalog-validated, backed up first)
  history       list saved sessions

Safety defaults: nothing is applied without --apply; every optimize/benchmark
session starts by backing up the configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from optimize import __version__
from optimize.adapters.base import GameAdapter, GameAdapterError
from optimize.adapters.synthetic import AURORA_CATALOG, SyntheticGameAdapter
from optimize.db import ProfileDatabase
from optimize.engine.scoring import settings_quality
from optimize.engine.search import SearchConfig, run_search
from optimize.hardware.profiler import detect_hardware
from optimize.models import Goal, OptimizationReport, RawRun
from optimize.reporting import export_profile, write_report
from optimize.telemetry.metrics import compute_metrics
from optimize.telemetry.simulated import SimulatedCollector

VERDICT_MARKER = {"kept": "KEEP", "rejected": "REJ ", "inconclusive": "INC "}


def default_data_root() -> Path:
    env = os.environ.get("PC_OPTIMIZE_HOME")
    return Path(env) if env else Path.home() / ".pc-optimize"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pc-optimize",
        description="Hardware-aware PC game optimization prototype "
        "(measure, test supported settings, verify, roll back).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data-dir",
        default=None,
        help="tool data directory (default: ~/.pc-optimize or PC_OPTIMIZE_HOME)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("hardware", help="show the detected hardware profile",
                   parents=[common])

    demo = sub.add_parser(
        "demo", help="run the full optimization loop on the synthetic game",
        parents=[common],
    )
    demo.add_argument("--game", default=AURORA_CATALOG.game_id, help="game adapter id")
    _add_common_options(demo)
    demo.add_argument(
        "--apply",
        action="store_true",
        help="apply the winning configuration (default: restore original)",
    )

    opt = sub.add_parser("optimize", help="run the optimization loop for a game",
                         parents=[common])
    opt.add_argument("--game", default=AURORA_CATALOG.game_id, help="game adapter id")
    _add_common_options(opt)
    opt.add_argument(
        "--apply",
        action="store_true",
        help="apply the winning configuration (default: restore original)",
    )

    bench = sub.add_parser("benchmark", help="capture baseline runs and report variance",
                            parents=[common])
    bench.add_argument("--game", default=AURORA_CATALOG.game_id, help="game adapter id")
    bench.add_argument("--runs", type=int, default=3)
    bench.add_argument("--seconds", type=float, default=20.0)

    restore = sub.add_parser("restore", help="restore a game configuration backup",
                             parents=[common])
    restore.add_argument("--game", default=AURORA_CATALOG.game_id, help="game adapter id")
    restore.add_argument("--backup", default=None, help="backup id (default: latest)")

    report = sub.add_parser("report", help="render an HTML report for a session",
                            parents=[common])
    report.add_argument("--session", type=int, default=None,
                        help="session id (default: most recent)")
    report.add_argument("--out", default=None,
                        help="output file (default: <data-dir>/reports/session-<id>.html)")

    export = sub.add_parser("export", help="export a session profile as JSON",
                            parents=[common])
    export.add_argument("--session", type=int, default=None,
                        help="session id (default: most recent)")
    export.add_argument("--out", "-o", default=None,
                        help="output file (default: <data-dir>/exports/session-<id>-profile.json)")

    apply_cfg = sub.add_parser(
        "apply-config", help="apply a settings profile exported by this tool",
        parents=[common],
    )
    apply_cfg.add_argument("--game", default=AURORA_CATALOG.game_id, help="game adapter id")
    apply_cfg.add_argument("--file", required=True, help="profile JSON file to apply")

    hist = sub.add_parser("history", help="list saved sessions", parents=[common])
    hist.add_argument("--limit", type=int, default=20)

    return parser


def _add_common_options(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--goal",
        default=Goal.BALANCED.value,
        choices=[g.value for g in Goal],
        help="optimization target (default: balanced)",
    )
    sub.add_argument("--trials", type=int, default=6, help="max single-setting trials")
    sub.add_argument("--runs", type=int, default=2, help="benchmark runs per config")
    sub.add_argument("--seconds", type=float, default=15.0, help="capture seconds per run")
    sub.add_argument("--fps-target", type=float, default=None)
    sub.add_argument("--quality-floor", type=float, default=None)
    sub.add_argument(
        "--real-hardware",
        action="store_true",
        help="query real hardware instead of the simulated profile (Windows)",
    )


def make_adapter(game_id: str, data_root: Path) -> GameAdapter:
    if game_id == SyntheticGameAdapter.game_id:
        return SyntheticGameAdapter(data_root)
    raise GameAdapterError(
        f"no adapter registered for {game_id!r}; "
        f"registered games: {SyntheticGameAdapter.game_id} "
        "(real-game adapters are added one per title, see README Phase 2)"
    )


def cmd_hardware(args: argparse.Namespace) -> int:
    profile = detect_hardware(prefer_simulated=not getattr(args, "real_hardware", False))
    print(f"Hardware profile (source: {profile.source})")
    print(f"  CPU            {profile.cpu_model} ({profile.cpu_cores} threads)")
    print(f"  GPU            {profile.gpu_model}")
    print(f"  VRAM           {profile.vram_mb or '?'} MB")
    print(f"  RAM            {profile.ram_gb or '?'} GB")
    print(f"  Display        {profile.display_resolution} @ {profile.refresh_rate_hz} Hz")
    print(f"  Driver         {profile.driver_version or 'unknown'}")
    print(f"  OS             {profile.os}")
    return 0


def cmd_optimize(args: argparse.Namespace, demo_banner: bool = False) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    try:
        adapter = make_adapter(args.game, data_root)
    except GameAdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not adapter.detect():
        print(f"error: game {args.game!r} is not installed/detectable", file=sys.stderr)
        return 1

    drift = adapter.unknown_settings_keys()
    if drift:
        print(f"warning: config contains unknown settings (game updated? adapter "
              f"out of date?): {', '.join(sorted(drift))}")
        print("         they will be left untouched and excluded from optimization")

    hardware = detect_hardware(prefer_simulated=not args.real_hardware)
    goal = Goal(args.goal)

    if demo_banner:
        print("=" * 72)
        print("PC Game Optimization Engine — Milestone 1 prototype")
        print("Synthetic game + simulated telemetry: validates the full loop")
        print("(profile -> backup -> baseline -> trials -> verdict -> rollback).")
        print("=" * 72)

    print("[1/6] Hardware")
    print(f"      {hardware.gpu_model}, {hardware.cpu_model}, {hardware.vram_mb} MB VRAM")
    print(f"      {hardware.display_resolution} @ {hardware.refresh_rate_hz} Hz display")

    backup = adapter.backup("pre-optimize")
    print(f"[2/6] Backed up current configuration ({backup.backup_id})")

    collector = SimulatedCollector(adapter.catalog())
    config = SearchConfig(
        runs_per_config=args.runs,
        max_trials=args.trials,
        capture_seconds=args.seconds,
        fps_target=args.fps_target,
        quality_floor=args.quality_floor,
    )
    print(f"[3/6] Baseline: {args.runs} run(s) x {args.seconds:.0f}s ...")
    report = run_search(adapter, collector, hardware, goal, config)
    report.backup_id = backup.backup_id

    base = report.baseline_metrics
    base_fps = statistics.fmean([m.avg_fps for m in base])
    base_low = statistics.fmean([m.fps_1p_low for m in base])
    print(f"      avg {base_fps:.1f} FPS, 1% low {base_low:.1f}, "
          f"consistency {statistics.fmean([m.consistency for m in base]):.2f}, "
          f"bottleneck: {report.bottleneck}")

    print(f"[4/6] Candidate trials (budget {args.trials})")
    for i, trial in enumerate(report.trials, 1):
        marker = VERDICT_MARKER.get(trial.verdict, "????")
        print(
            f"      {i}. [{marker}] {trial.candidate.label:<42} "
            f"avg {trial.metrics.avg_fps:6.1f} ({trial.gain_pct:+5.1f}%)  "
            f"score {trial.score:.3f}"
        )
        if trial.reason:
            print(f"          {trial.reason}")

    # ---- Apply or restore (explicit approval required) -----------------------
    if args.apply and report.recommendation == "apply-candidate" and report.best_settings:
        changes = {
            k: v
            for k, v in report.best_settings.items()
            if report.baseline_settings.get(k) != v
        }
        adapter.apply_changes(changes)
        report.applied = True
        print("[5/6] Applied the winning configuration:")
        for key, value in changes.items():
            print(f"      {key}: {report.baseline_settings.get(key)} -> {value}")
        print(f"      rollback anytime with: pc-optimize restore --game {args.game}")
    else:
        current = adapter.read_settings()
        if current != report.baseline_settings:
            adapter.restore(backup.backup_id)
        print("[5/6] Original configuration verified/restored "
              "(nothing is applied without --apply)")

    print("[6/6] Result")
    if report.recommendation == "apply-candidate" and report.best_metrics is not None:
        delta = report.best_metrics.avg_fps - base_fps
        best_quality = settings_quality(adapter.catalog(), report.best_settings or {})
        print(f"      best: {report.best_score:.3f} vs baseline {report.baseline_score:.3f} "
              f"({delta:+.1f} FPS avg, quality {report.baseline_quality:.2f} -> "
              f"{best_quality:.2f})")
    else:
        print("      no supported change is a verified improvement for this goal "
              "(see verdicts above)")
    for note in report.notes:
        print(f"      note: {note}")

    db = ProfileDatabase(data_root / "profiles.db")
    try:
        session_id = db.save_session(report)
    finally:
        db.close()
    print(f"      session {session_id} saved to {data_root / 'profiles.db'}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    try:
        adapter = make_adapter(args.game, data_root)
    except GameAdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not adapter.detect():
        print(f"error: game {args.game!r} is not installed/detectable", file=sys.stderr)
        return 1

    hardware = detect_hardware()
    collector = SimulatedCollector(adapter.catalog())
    settings = adapter.read_settings()

    print(f"Game: {adapter.title}")
    print(f"Baseline runs: {args.runs} x {args.seconds:.0f}s "
          f"(settings: {', '.join(f'{k}={v}' for k, v in sorted(settings.items()))})")

    report = OptimizationReport(
        game_id=adapter.game_id, goal=Goal.BALANCED, hardware=hardware,
        baseline_settings=dict(settings), recommendation="benchmark-only",
    )
    metrics_list = []
    for i in range(args.runs):
        capture = collector.run(settings, hardware, args.seconds, seed=7000 + i)
        metrics = compute_metrics(capture)
        metrics_list.append(metrics)
        report.baseline_metrics.append(metrics)
        report.raw_runs.append(
            RawRun("baseline", dict(settings), metrics, capture.frame_times_ms)
        )
        print(
            f"  run {i + 1}: avg {metrics.avg_fps:6.1f} FPS | "
            f"1% low {metrics.fps_1p_low:6.1f} | "
            f"p99 frame {metrics.p99_frame_time_ms:5.2f} ms | "
            f"spikes {metrics.spike_ratio * 100:4.1f}%"
        )

    avgs = [m.avg_fps for m in metrics_list]
    cv = (statistics.pstdev(avgs) / statistics.fmean(avgs) * 100.0) if len(avgs) > 1 else 0.0
    print(f"  run-to-run variance: ±{cv:.1f}% "
          f"(gains smaller than this are inconclusive)")

    db = ProfileDatabase(data_root / "profiles.db")
    try:
        session_id = db.save_session(report)
    finally:
        db.close()
    print(f"  saved as session {session_id}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    try:
        adapter = make_adapter(args.game, data_root)
    except GameAdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        backup = adapter.restore(args.backup) if args.backup else adapter.restore_latest()
    except Exception as exc:  # surface backup corruption as a clean CLI error
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if backup is None:
        print("error: no backups found for this game", file=sys.stderr)
        return 1
    print(f"Restored {len(backup.files)} config file(s) from backup {backup.backup_id} "
          f"(created {backup.created}).")
    for path in backup.files:
        print(f"  {path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    db_path = data_root / "profiles.db"
    if not db_path.exists():
        print(f"error: no profile database at {db_path}", file=sys.stderr)
        return 1
    out = (
        Path(args.out)
        if args.out
        else data_root / "reports" / f"session-{args.session or 'latest'}.html"
    )
    try:
        write_report(db_path, out, session_id=args.session)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Report written to {out}")
    print("Open it in a browser: charts and trial verdicts are self-contained.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    db_path = data_root / "profiles.db"
    if not db_path.exists():
        print(f"error: no profile database at {db_path}", file=sys.stderr)
        return 1
    out = (
        Path(args.out)
        if args.out
        else data_root / "exports" / f"session-{args.session or 'latest'}-profile.json"
    )
    try:
        profile = export_profile(db_path, out, session_id=args.session)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Exported profile to {out}")
    print(f"  game: {profile['game_id']}, goal: {profile['goal']}, "
          f"{len(profile['changed'])} change(s) vs baseline")
    print("Apply it later with: pc-optimize apply-config --game "
          f"{profile['game_id']} --file {out}")
    return 0


def cmd_apply_config(args: argparse.Namespace) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    try:
        adapter = make_adapter(args.game, data_root)
    except GameAdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    profile_path = Path(args.file)
    if not profile_path.exists():
        print(f"error: profile file not found: {profile_path}", file=sys.stderr)
        return 1
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: profile is not valid JSON: {exc}", file=sys.stderr)
        return 1

    settings = profile.get("settings")
    if not isinstance(settings, dict) or not settings:
        print("error: profile has no 'settings' object", file=sys.stderr)
        return 1
    profile_game = profile.get("game_id")
    if profile_game and profile_game != adapter.game_id:
        print(
            f"error: profile is for game {profile_game!r}, refusing to apply "
            f"to {adapter.game_id!r}",
            file=sys.stderr,
        )
        return 1

    # Same validation path as the optimizer: nothing outside the catalog is
    # ever written, and the current config is backed up first.
    catalog = adapter.catalog()
    try:
        catalog.validate({k: str(v) for k, v in settings.items()})
    except (ValueError, KeyError) as exc:
        print(f"error: profile rejected by the {adapter.game_id} catalog: {exc}",
              file=sys.stderr)
        return 1

    backup = adapter.backup("pre-apply-config")
    current = adapter.read_settings()
    changes = {k: str(v) for k, v in settings.items() if current.get(k) != str(v)}
    adapter.apply_changes(changes)

    print(f"Applied profile {profile_path.name} to {adapter.game_id} "
          f"(backup {backup.backup_id}):")
    for key in sorted(changes):
        print(f"  {key}: {current.get(key)} -> {changes[key]}")
    if not changes:
        print("  (no effective changes; configuration already matched)")
    print(f"Rollback anytime with: pc-optimize restore --game {adapter.game_id}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    data_root = Path(args.data_dir) if args.data_dir else default_data_root()
    db_path = data_root / "profiles.db"
    if not db_path.exists():
        print("no sessions recorded yet")
        return 0
    db = ProfileDatabase(db_path)
    try:
        sessions = db.recent_sessions(limit=args.limit)
    finally:
        db.close()
    if not sessions:
        print("no sessions recorded yet")
        return 0
    print(f"{'id':>3}  {'when':<20}  {'game':<14}  {'goal':<15}  "
          f"{'base fps':>8}  {'best fps':>8}  {'outcome':<16}  applied")
    for s in sessions:
        print(
            f"{s.session_id:>3}  {s.ts:<20}  {s.game_id:<14}  {s.goal:<15}  "
            f"{s.baseline_avg_fps or '-':>8}  {s.best_avg_fps or '-':>8}  "
            f"{s.recommendation:<16}  {'yes' if s.applied else 'no'}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "hardware": cmd_hardware,
        "demo": cmd_optimize,
        "optimize": cmd_optimize,
        "benchmark": cmd_benchmark,
        "restore": cmd_restore,
        "report": cmd_report,
        "export": cmd_export,
        "apply-config": cmd_apply_config,
        "history": cmd_history,
    }
    handler = handlers[args.command]
    if args.command == "demo":
        return handler(args, demo_banner=True)
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
