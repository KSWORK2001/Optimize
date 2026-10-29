"""Self-contained HTML session reports with inline-SVG frame-time charts.

Phase 1 requires displaying average FPS, 1% lows, and frame-time charts.
The report is a single static HTML file with no external assets or scripts,
so it renders offline in any browser and is easy to attach to a bug report.
Reports are generated from the profile database, so they work for any past
session.
"""

from __future__ import annotations

import html
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from optimize.db import ProfileDatabase

_MAX_CHART_POINTS = 1200   # downsample above this to keep files small


@dataclass(frozen=True)
class SessionInfo:
    session_id: int
    ts: str
    game_id: str
    goal: str
    bottleneck: str | None
    hardware: dict
    baseline_settings: dict
    best_settings: dict | None
    baseline_score: float | None
    best_score: float | None
    recommendation: str
    applied: bool
    backup_id: str | None
    notes: list[str]
    trials: list[dict]
    runs: list[dict]


def load_session(db_path: Path, session_id: int | None = None) -> SessionInfo | None:
    db = ProfileDatabase(db_path)
    try:
        if session_id is None:
            recent = db.recent_sessions(limit=1)
            if not recent:
                return None
            session_id = recent[0].session_id
        session = db.get_session(session_id)
        if session is None:
            raise FileNotFoundError(f"session {session_id} not found in {db_path}")
        runs = db.session_runs(session_id)
    finally:
        db.close()
    return SessionInfo(
        session_id=session["id"],
        ts=session["ts"],
        game_id=session["game_id"],
        goal=session["goal"],
        bottleneck=session["bottleneck"],
        hardware=session["hardware"],
        baseline_settings=session["baseline_settings"],
        best_settings=session["best_settings"],
        baseline_score=session["baseline_score"],
        best_score=session["best_score"],
        recommendation=session["recommendation"],
        applied=session["applied"],
        backup_id=session["backup_id"],
        notes=session["notes"],
        trials=session["trials"],
        runs=runs,
    )


def frame_time_chart_svg(
    frame_times: list[float],
    title: str,
    width: int = 780,
    height: int = 240,
    color: str = "#2563eb",
) -> str:
    """Line chart of frame time over the run, with mean and p99 reference lines."""
    if not frame_times:
        return f'<p class="muted">{html.escape(title)}: no frame-time data</p>'

    stride = max(1, math.ceil(len(frame_times) / _MAX_CHART_POINTS))
    samples = frame_times[::stride]
    mean_ms = statistics.fmean(frame_times)
    ordered = sorted(frame_times)
    p99 = ordered[min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)]

    pad_l, pad_r, pad_t, pad_b = 58, 92, 30, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    y_max = max(samples) * 1.05

    def x(i: int) -> float:
        span = len(samples) - 1 or 1
        return pad_l + i * plot_w / span

    def y(ft: float) -> float:
        return pad_t + (1.0 - ft / y_max) * plot_h

    points = " ".join(f"{x(i):.1f},{y(ft):.1f}" for i, ft in enumerate(samples))
    ref_line = (
        f'<line x1="{pad_l}" x2="{pad_l + plot_w}" y1="{y(mean_ms):.1f}" '
        f'y2="{y(mean_ms):.1f}" stroke="#16a34a" stroke-dasharray="5 4" stroke-width="1"/>'
        f'<text x="{pad_l + plot_w + 6}" y="{y(mean_ms) + 4:.1f}" font-size="11" fill="#16a34a">'
        f"mean {mean_ms:.1f} ms</text>"
        f'<line x1="{pad_l}" x2="{pad_l + plot_w}" y1="{y(p99):.1f}" '
        f'y2="{y(p99):.1f}" stroke="#dc2626" stroke-dasharray="5 4" stroke-width="1"/>'
        f'<text x="{pad_l + plot_w + 6}" y="{y(p99) + 4:.1f}" font-size="11" fill="#dc2626">'
        f"p99 {p99:.1f} ms</text>"
    )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{html.escape(title)}">'
        f'<text x="{pad_l}" y="18" font-size="13" font-weight="600" fill="#0f172a">'
        f"{html.escape(title)} "
        f'<tspan fill="#64748b" font-weight="400">'
        f"({len(frame_times)} frames, stride {stride})</tspan></text>"
        f'<line x1="{pad_l}" x2="{pad_l}" y1="{pad_t}" y2="{pad_t + plot_h}" stroke="#cbd5e1"/>'
        f'<line x1="{pad_l}" x2="{pad_l + plot_w}" y1="{pad_t + plot_h}" '
        f'y2="{pad_t + plot_h}" stroke="#cbd5e1"/>'
        f'<text x="6" y="{pad_t + 10}" font-size="11" fill="#64748b">{y_max:.0f} ms</text>'
        f'<text x="6" y="{pad_t + plot_h}" font-size="11" fill="#64748b">0</text>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.4" points="{points}"/>'
        f"{ref_line}</svg>"
    )


_VERDICT_BADGE = {
    "kept": ("kept", "#16a34a"),
    "rejected": ("rejected", "#dc2626"),
    "inconclusive": ("inconclusive", "#64748b"),
}


def _settings_table(settings: dict, changed: dict | None = None) -> str:
    changed = changed or {}
    rows = []
    for key in sorted(settings):
        value = html.escape(str(settings[key]))
        if key in changed:
            rows.append(
                f'<tr><td>{html.escape(key)}</td><td><strong>{value}</strong> '
                f'<span class="muted">(was {html.escape(str(changed[key]))})</span></td></tr>'
            )
        else:
            rows.append(f"<tr><td>{html.escape(key)}</td><td>{value}</td></tr>")
    return f'<table class="settings">{"".join(rows)}</table>'


def _metric_cards(runs: list[dict]) -> str:
    baseline = [r for r in runs if r["label"] == "baseline"]
    others = [r for r in runs if r["label"] != "baseline"]
    if not baseline:
        return ""
    base = _mean(baseline, "avg_fps")

    def card(label: str, value: str, sub: str = "") -> str:
        sub_html = f'<div class="sub">{sub}</div>' if sub else ""
        return f'<div class="card"><div class="card-label">{label}</div>' \
               f'<div class="card-value">{value}</div>{sub_html}</div>'

    cards = [card("baseline avg", f"{base:.1f} FPS", f"{len(baseline)} run(s)")]
    if others:
        best_avg = max(r["metrics"]["avg_fps"] for r in others)
        best_low = min(r["metrics"]["fps_1p_low"] for r in others)
        gain = (best_avg - base) / base * 100 if base else 0
        cards.append(card("best trial avg", f"{best_avg:.1f} FPS", f"{gain:+.1f}% vs baseline"))
        cards.append(card("best 1% low", f"{best_low:.1f} FPS", "worst 1% of frame times"))
    base_low = _mean(baseline, "fps_1p_low")
    base_cons = _mean(baseline, "consistency") * 100
    cards.append(card("baseline 1% low", f"{base_low:.1f} FPS"))
    cards.append(card("baseline consistency", f"{base_cons:.0f}%"))
    return f'<div class="cards">{"".join(cards)}</div>'


def _mean(runs: list[dict], key: str) -> float:
    return statistics.fmean([r["metrics"][key] for r in runs])


def render_session_html(info: SessionInfo) -> str:
    """One static page: summary, metrics, trials, settings, frame-time charts."""
    hw = info.hardware
    changed = {}
    if info.best_settings:
        changed = {
            k: v
            for k, v in info.best_settings.items()
            if info.baseline_settings.get(k) != v
        }

    trials_html = ""
    if info.trials:
        rows = []
        for index, trial in enumerate(info.trials, 1):
            verdict = trial.get("verdict", "unknown")
            badge_text, badge_color = _VERDICT_BADGE.get(verdict, (verdict, "#64748b"))
            reason = html.escape(trial.get("reason", "")) or "—"
            rows.append(
                f'<tr><td>{index}. {html.escape(trial.get("label", "?"))}</td>'
                f'<td>{trial.get("avg_fps", 0):.1f} FPS '
                f'<span class="muted">({trial.get("gain_pct", 0):+.1f}%)</span></td>'
                f'<td>{trial.get("score", 0):.3f}</td>'
                f'<td><span class="badge" style="color:{badge_color}">{badge_text}</span> '
                f'<span class="muted">{reason}</span></td></tr>'
            )
        trials_html = (
            "<h2>Trials</h2><table><tr><th>candidate</th><th>measured</th>"
            f"<th>score</th><th>verdict</th></tr>{''.join(rows)}</table>"
        )

    charts = []
    baseline_runs = [r for r in info.runs if r["label"] == "baseline"]
    if baseline_runs:
        charts.append(
            frame_time_chart_svg(baseline_runs[0]["frame_times_ms"], "Baseline frame times")
        )
    non_baseline = [r for r in info.runs if r["label"] != "baseline"]
    if non_baseline:
        best_run = max(non_baseline, key=lambda r: r["metrics"]["avg_fps"])
        charts.append(
            frame_time_chart_svg(
                best_run["frame_times_ms"],
                f"Best trial frame times — {best_run['label']}",
                color="#7c3aed",
            )
        )

    notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in info.notes) or \
        "<li class='muted'>none</li>"
    applied_text = "applied" if info.applied else "not applied (rollback kept)"
    title = f"Session {info.session_id} — {info.game_id}"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
 body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0;
        background: #f8fafc; color: #0f172a; }}
 .wrap {{ max-width: 860px; margin: 0 auto; padding: 24px 16px 48px; }}
 h1 {{ font-size: 22px; margin: 0 0 4px; }}
 h2 {{ font-size: 15px; margin: 28px 0 8px; color: #334155; }}
 .muted {{ color: #64748b; font-weight: 400; }}
 .meta {{ color: #64748b; font-size: 13px; margin-bottom: 16px; }}
 .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; }}
 .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
         padding: 10px 14px; min-width: 130px; }}
 .card-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
               color: #64748b; }}
 .card-value {{ font-size: 20px; font-weight: 650; margin-top: 2px; }}
 .sub {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
 table {{ border-collapse: collapse; width: 100%; background: #fff;
          border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; }}
 td, th {{ padding: 6px 10px; border-bottom: 1px solid #eef2f7; text-align: left; }}
 tr:last-child td {{ border-bottom: none; }}
 .badge {{ font-size: 12px; font-weight: 600; }}
 .chart {{ width: 100%; height: auto; background: #fff; border: 1px solid #e2e8f0;
          border-radius: 10px; margin: 8px 0; }}
 footer {{ margin-top: 32px; font-size: 12px; color: #64748b;
          border-top: 1px solid #e2e8f0; padding-top: 12px; }}
</style></head><body><div class="wrap">
<h1>{html.escape(info.game_id)} <span class="muted">· {html.escape(info.goal)} goal</span></h1>
<div class="meta">session {info.session_id} · {html.escape(info.ts)} ·
 recommendation: <strong>{html.escape(info.recommendation)}</strong> ({applied_text})
 {'· backup ' + html.escape(info.backup_id) if info.backup_id else ''}</div>

<h2>Hardware</h2>
<table><tr><td>GPU</td><td>{html.escape(str(hw.get('gpu_model', '?')))}</td></tr>
<tr><td>CPU</td><td>{html.escape(str(hw.get('cpu_model', '?')))}</td></tr>
<tr><td>VRAM / RAM</td><td>{hw.get('vram_mb', '?')} MB / {hw.get('ram_gb', '?')} GB</td></tr>
<tr><td>Display</td><td>{html.escape(str(hw.get('display_resolution', '?')))}
 @ {hw.get('refresh_rate_hz', '?')} Hz</td></tr>
<tr><td>Source</td><td>{html.escape(str(hw.get('source', '?')))}</td></tr></table>

<h2>Measurements</h2>
{_metric_cards(info.runs)}
{trials_html}
<h2>Recommended configuration{f' — {len(changed)} change(s)' if changed else ''}</h2>
{_settings_table(info.best_settings or info.baseline_settings, changed)}

<h2>Notes</h2>
<ul>{notes_html}</ul>

<h2>Frame times</h2>
{''.join(charts) or '<p class="muted">no captures stored</p>'}

<footer>Generated by pc-optimize from the local profile database. An optimization
assistant, not a guarantee of higher FPS — see README for methodology and caveats.</footer>
</div></body></html>"""


def write_report(db_path: Path, out_path: Path, session_id: int | None = None) -> Path:
    info = load_session(db_path, session_id)
    if info is None:
        raise FileNotFoundError(
            f"no session {'with id ' + str(session_id) if session_id else ''}in {db_path}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_session_html(info), encoding="utf-8")
    return out_path


def export_profile(db_path: Path, out_path: Path, session_id: int | None = None) -> dict:
    """Write a portable JSON profile (README Phase 4: profile import/export).

    The exported settings are the session's best configuration when one was
    recommended, otherwise the baseline. Hardware metadata is included for
    context; applying the profile elsewhere is validated against the target
    game's catalog before anything is written.
    """
    info = load_session(db_path, session_id)
    if info is None:
        raise FileNotFoundError(
            f"no session {'with id ' + str(session_id) if session_id else ''}in {db_path}"
        )
    settings = info.best_settings or info.baseline_settings
    profile = {
        "format": "pc-optimize-profile",
        "version": 1,
        "game_id": info.game_id,
        "goal": info.goal,
        "created": info.ts,
        "source_session": info.session_id,
        "hardware": info.hardware,
        "settings": settings,
        "changed": [
            {"setting": k, "from": info.baseline_settings.get(k), "to": v}
            for k, v in settings.items()
            if info.baseline_settings.get(k) != v
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return profile
