# PC Game Optimization Engine

A hardware-aware tool that profiles a Windows gaming PC, benchmarks a game, searches for better supported settings, and verifies the results. The goal is to reduce the gap between the consistency of a fixed console configuration and the variability of PC gaming.

> **Project principle:** Measure before changing anything. Apply only supported, reversible changes, then benchmark again. Never promise console-level performance or a fixed FPS gain.

## Table of contents

- [Why build this?](#why-build-this)
- [Problem statement](#problem-statement)
- [What the tool can and cannot do](#what-the-tool-can-and-cannot-do)
- [Goals and non-goals](#goals-and-non-goals)
- [Proposed user experience](#proposed-user-experience)
- [Architecture](#architecture)
- [Optimization loop](#optimization-loop)
- [Performance metrics and scoring](#performance-metrics-and-scoring)
- [MVP scope](#mvp-scope)
- [Suggested technology stack](#suggested-technology-stack)
- [Safety and compatibility](#safety-and-compatibility)
- [Development roadmap](#development-roadmap)
- [Testing and success criteria](#testing-and-success-criteria)
- [Risks and open questions](#risks-and-open-questions)
- [Getting started](#getting-started)
- [References](#references)

## Why build this?

Consoles often deliver a consistent experience despite having less raw compute power than some gaming PCs. Developers target a known hardware configuration and can tune the game around it. PC games must support a much wider range of CPUs, GPUs, memory configurations, drivers, display modes, and operating-system states.

The opportunity is not to magically rewrite a game's engine. It is to automate the work PC players often do manually:

1. Identify the machine and game configuration.
2. Measure actual performance.
3. Diagnose likely bottlenecks.
4. Test sensible, supported configuration changes.
5. Keep changes that improve the user's chosen experience.
6. Restore the previous configuration if results regress.

## Problem statement

PC optimization is fragmented across game settings, GPU utilities, monitoring software, driver controls, community guides, and manual trial and error. A single interface could combine profiling, safe configuration changes, repeatable benchmarking, and evidence-based recommendations.

The tool should optimize for the user's chosen target, such as:
- Competitive play: stable frame times and low latency.
- High-refresh-rate play: approach a chosen FPS target.
- Visual quality: preserve image quality while improving performance.
- Balanced play: trade off frame rate, visual quality, latency, power, and temperature.

## What the tool can and cannot do

### Potentially within scope

- Detect CPU, GPU, VRAM, RAM, storage, driver version, resolution, and refresh rate.
- Read and change documented or well-understood game configuration settings.
- Recommend resolution, quality, shadow, volumetric, and supported upscaling settings.
- Capture frame-time and performance telemetry.
- Identify likely CPU, GPU, or memory bottlenecks.
- Run repeatable benchmarks where a game offers a suitable benchmark or test route.
- Back up settings and roll back changes.
- Maintain game- and hardware-specific profiles.

### Limited or outside the tool's control

- Inefficient engine code, poor multithreading, excessive draw calls, or broken asset streaming may require changes from the game developer.
- Shader-compilation stutter may be mitigated in some cases, but not reliably eliminated by an external utility.
- A GPU cannot compensate for every CPU bottleneck, and settings changes cannot create hardware resources that do not exist.
- Console-specific rendering paths and engine changes cannot generally be reproduced through Windows settings alone.
- Anti-cheat software may prohibit certain overlays, hooks, process access, or modifications. Compatibility must be evaluated per game.
- A 120 Hz display mode does not guarantee 120 FPS in every scene. At 120 FPS, a new frame must be produced approximately every 8.33 milliseconds.

The application should report uncertainty and explain when it cannot safely or meaningfully improve performance.

## Goals and non-goals

### Goals

- **Evidence-based:** recommendations are validated by measurements.
- **Reversible:** every setting change can be undone.
- **Game-aware:** use specific adapters rather than assuming every game behaves alike.
- **Hardware-aware:** account for system constraints and supported GPU features.
- **Transparent:** show before-and-after results and explain changes.
- **Safe by default:** avoid game-process injection, memory patching, and unsupported anti-cheat interactions.
- **Incremental:** start with one game and one hardware ecosystem, then expand.

### Non-goals for the first release

- Automatically modifying game binaries or engine code.
- Bypassing anti-cheat or changing protected game memory.
- Guaranteeing console-equivalent performance.
- Optimizing every game and every hardware combination from day one.
- Applying risky CPU/GPU overclocks or undocumented registry tweaks.
- Using AI as an unchecked agent with unrestricted system access.

## Proposed user experience

1. The user opens the application and chooses an installed, supported game.
2. The tool detects hardware and the current game configuration.
3. The user selects a target profile: Competitive, High FPS, Balanced, or Visual Quality.
4. The tool explains the benchmark plan and backs up supported settings.
5. It runs a baseline capture, or imports a capture if automated benchmarking is not supported.
6. It tests a limited set of candidate configurations.
7. It compares average FPS, 1% lows, frame-time consistency, image-quality trade-offs, and any available latency, temperature, or power data.
8. It recommends a profile and shows exactly what will change.
9. The user approves the changes.
10. The tool validates the selected profile and offers rollback if performance worsens.

Automated benchmarks should use the same scene, route, duration, resolution, and background conditions wherever possible. Results from incomparable runs should be labeled accordingly.

## Architecture

```text
┌─────────────────────────────────────────────┐
│              Desktop Application            │
│ Game selection · Goals · Results · Rollback │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│            Optimization Orchestrator        │
│ Candidate selection · Constraints · Scoring │
└─────────────┬──────────────────┬────────────┘
              │                  │
┌─────────────▼──────────┐  ┌────▼─────────────┐
│ Game Adapter Layer     │  │ Telemetry Layer  │
│ Config read/write      │  │ FPS/frame times  │
│ Version checks         │  │ CPU/GPU/memory   │
│ Backups and rollback   │  │ Temp/power if    │
│ Supported settings     │  │ available        │
└─────────────┬──────────┘  └────┬─────────────┘
              │                  │
              └────────┬─────────┘
                       │
┌──────────────────────▼──────────────────────┐
│               Profile Database              │
│ Hardware · Game · Version · Settings · Runs │
└─────────────────────────────────────────────┘
```

### Main modules

#### 1. Hardware profiler

Collect only the information needed for optimization:
- CPU model and logical core count.
- GPU model, available VRAM, driver version, and supported features.
- Installed RAM and current memory pressure when available.
- Display resolution and refresh rate.
- Storage and operating-system details where relevant.
- Power and thermal information where supported.

Use supported operating-system and vendor interfaces. Do not assume every metric is available on every device.

#### 2. Telemetry and benchmark collector

Capture:
- Average FPS.
- 1% low FPS, with the calculation method documented.
- Frame-time distribution and spikes.
- CPU and GPU utilization where available.
- VRAM and system-memory use where available.
- Temperature, power, and latency when supported.

PresentMon-compatible tooling is a potential foundation for frame-time capture. Validate the current API, licensing, and supported Windows versions before integrating it.

#### 3. Game adapter layer

Each supported game should have a dedicated adapter that defines:
- How to identify the game and its version.
- Which settings can be read safely.
- Which settings can be changed.
- Valid values and dependencies.
- Whether a restart is required.
- How to back up and restore configuration.
- How to launch or guide the user through a benchmark, if supported.

Do not write a universal config editor that assumes settings have the same meaning across games. Keep adapters isolated and version-aware.

#### 4. Optimization engine

Generate a bounded set of candidate settings, evaluate them, and choose the best measured result for the selected goal.

Begin with rule-based recommendations and a simple search algorithm. AI may help rank candidate changes or explain results, but a deterministic layer must validate settings, enforce limits, and apply changes.

#### 5. Profile database

Store local records containing:
- Hardware and driver metadata.
- Game and game version.
- Resolution and target profile.
- Settings before and after.
- Benchmark conditions and results.
- Timestamp, confidence, and known caveats.

A future opt-in shared database could aggregate anonymized results. Do not upload system identifiers or telemetry without clear user consent.

## Optimization loop

```text
Detect hardware and game
          |
          v
Back up supported configuration
          |
          v
Run baseline benchmark
          |
          v
Estimate likely bottleneck
          |
          v
Generate safe candidate settings
          |
          v
Apply one candidate configuration
          |
          v
Run comparable benchmark
          |
          v
Compare performance and quality
          |
          v
Keep improvement or roll back
          |
          v
Stop at target, time limit, or no useful gains
```

### Suggested search strategy

For the MVP, use a bounded search over a carefully selected list of settings:
1. Identify the likely bottleneck.
2. Prioritize settings likely to affect that bottleneck.
3. Change one setting or a small, known-related group at a time.
4. Run repeatable tests.
5. Reject regressions and configurations outside safety constraints.
6. Save the best result.
7. Stop when the target is met, the test budget is exhausted, or gains become negligible.

A later version can use Bayesian optimization or another sample-efficient search method. Do not start by exhaustively testing every combination; the search space grows exponentially.

## Performance metrics and scoring

A simple conceptual score is:

```text
Score =
    w_fps       * normalized_average_fps
  + w_consist   * normalized_frame_consistency
  + w_quality   * estimated_or_user-rated_image_quality
  - w_latency   * normalized_input_latency
  - w_power     * normalized_power_cost
  - w_thermal   * thermal_penalty
```

The weights (`w_*`) depend on the selected goal. This is a design sketch, not a validated formula. Normalize metrics before combining them, define missing-data behavior, and avoid double-counting correlated metrics.

Prefer hard constraints for critical requirements. For example:
- Do not recommend a configuration that crashes or fails validation.
- Do not sacrifice image quality beyond the user's selected tolerance.
- Do not claim an FPS target has been achieved unless measurements support it.
- Treat results as inconclusive if benchmark variance is larger than the observed gain.

For frame pacing, retain raw frame-time samples rather than relying only on average FPS. A small average-FPS gain may not be worthwhile if stuttering becomes worse.

## MVP scope

### Recommended first release

- Windows desktop only.
- One supported game.
- NVIDIA GPU configurations initially.
- Read-only hardware detection.
- Baseline frame-time capture.
- A small, documented list of safe game settings.
- Manual benchmark workflow if automated benchmarking is unavailable.
- Before-and-after comparison.
- Configuration backup and rollback.
- Local profile storage.
- Clear warnings and user approval before applying changes.

### Leave for later

- Broad multi-game support.
- AMD and Intel GPU-specific tuning.
- Cloud profiles and cross-user learning.
- Automatic benchmark route detection.
- Advanced power/thermal optimization.
- AI-generated recommendations.
- One-click optimization for games with unsupported configuration formats.

## Suggested technology stack

Choose the stack based on the developer's familiarity and the integration requirements. One practical starting point:

| Component | Candidate |
|---|---|
| Desktop UI | C# with .NET and WinUI/WPF, or Tauri with a web UI |
| Windows system integration | C#/.NET or a small native Rust/C++ module |
| Optimization engine | Python for early experiments; port performance-critical pieces later if needed |
| Local database | SQLite |
| Telemetry | PresentMon-compatible capture plus supported OS/vendor APIs |
| Testing | Unit tests for adapters, integration tests for config rollback, repeatable benchmark runs |
| Packaging | Signed Windows installer once the app is stable |

Avoid committing to a large stack before validating the first game adapter and the benchmark pipeline. Keep telemetry collection and config modification behind interfaces so they can be replaced.

## Safety and compatibility

- Back up configuration files before editing.
- Write only to documented or verified settings paths.
- Validate values and file contents before applying changes.
- Use atomic writes where practical.
- Keep a clear audit log of every change.
- Provide a one-click restore to the original configuration.
- Never disable security tools or anti-cheat.
- Avoid injection, DLL loading into game processes, memory patching, and unsupported hooks.
- Do not change BIOS settings, voltages, or overclocking settings in the MVP.
- Require explicit user approval before applying changes.
- Handle game updates by invalidating profiles when compatibility is uncertain.
- Use least privilege; do not require administrator access unless a specific, documented operation truly needs it.
- Clearly disclose telemetry collection and keep it opt-in.

## Development roadmap

### Phase 0 — Feasibility spike

- [ ] Choose one game with accessible configuration settings and a repeatable benchmark.
- [ ] Confirm telemetry capture works on the target Windows versions.
- [ ] Verify which settings can be changed safely and restored.
- [ ] Record a baseline on at least two hardware configurations if available.
- [ ] Document legal, license, and anti-cheat constraints.

**Exit criterion:** A script or prototype can capture a repeatable baseline and restore the original configuration.

### Phase 1 — Instrumentation prototype

- [ ] Implement hardware detection.
- [ ] Integrate frame-time capture.
- [ ] Save benchmark metadata and raw results.
- [ ] Display average FPS, 1% lows, and frame-time charts.
- [ ] Add run-to-run variance checks.

**Exit criterion:** The same configuration can be benchmarked repeatedly and the tool can report uncertainty.

### Phase 2 — One-game optimizer

- [ ] Implement the first game adapter.
- [ ] Add safe settings validation and backup/rollback.
- [ ] Create a small set of candidate profiles.
- [ ] Run tests and compare results.
- [ ] Reject crashes, invalid settings, and performance regressions.

**Exit criterion:** The tool can find and verify an improvement on at least one test configuration without losing the ability to restore the original state.

### Phase 3 — Desktop UX

- [ ] Add game selection and target profiles.
- [ ] Show a preview of planned changes.
- [ ] Add explicit Apply, Re-test, and Restore controls.
- [ ] Display before-and-after results and confidence.
- [ ] Add useful failure messages and logs.

### Phase 4 — More games and hardware

- [ ] Add adapters one game at a time.
- [ ] Test across GPU, CPU, driver, and game-version combinations.
- [ ] Add AMD and Intel GPU support where the telemetry and tuning interfaces allow it.
- [ ] Add profile import/export.
- [ ] Consider opt-in, anonymized community profiles.

### Phase 5 — Smarter optimization

- [ ] Learn from previous successful test runs.
- [ ] Use a sample-efficient search strategy.
- [ ] Estimate which settings are likely to matter for a detected bottleneck.
- [ ] Compare recommendations against static presets and existing vendor tools.
- [ ] Add AI-generated explanations, with all changes still validated by deterministic code.

## Testing and success criteria

A credible MVP should demonstrate:
- **Safety:** every test can restore the initial configuration.
- **Repeatability:** benchmarks use comparable conditions and report variance.
- **Correctness:** invalid or unsupported settings are never applied.
- **Transparency:** every change and measured result is visible to the user.
- **Performance:** at least one supported configuration improves a user-selected metric beyond normal benchmark variation without unacceptable regressions in other metrics.
- **Compatibility:** failures caused by game updates or missing telemetry are handled gracefully.
- **Trust:** no anti-cheat bypass, hidden changes, or non-consensual telemetry uploads.

Do not claim success from a single benchmark run. Use repeated runs, consistent conditions, and conservative thresholds. Compare the optimizer against both the game's default settings and any relevant vendor optimization utility.

## Risks and open questions

1. **Benchmark noise:** background tasks, shader compilation, thermal changes, and different scenes can make results incomparable.
2. **Game-specific behavior:** settings files and supported options vary, and game updates may invalidate adapters.
3. **Anti-cheat:** some competitive titles may be unsuitable for automated interaction.
4. **Image-quality measurement:** FPS is easy to measure; visual quality is harder to score automatically. Begin with known settings trade-offs and user-selected quality limits.
5. **Scope:** supporting every game from the start will slow development and weaken validation.
6. **Telemetry access:** available metrics differ by GPU vendor, Windows version, and API.
7. **Value proposition:** existing tools already offer profiles and performance capture. The product must prove value through its closed-loop test, validation, and rollback workflow.

## Getting started

1. Pick one game and confirm that its settings can be safely read, changed, and restored.
2. Build a minimal hardware and telemetry collector before creating the full UI.
3. Record several baseline benchmark runs and quantify natural variation.
4. Add one reversible setting change and test whether the benchmark detects its effect.
5. Implement rollback and failure handling before adding more settings.
6. Expand only when the first adapter produces reliable, repeatable results.

### First milestone

**Milestone 1: a working benchmark-and-rollback prototype.**

It should identify the machine, capture a baseline, change one safe setting, capture a second run, compare the results, and restore the original setting. This validates the hardest assumptions before investing in a broad optimization engine.

## Implementation status (Milestone 1 prototype)

A working benchmark-and-rollback prototype lives in `src/optimize/` (Python 3.10+, standard library only; SQLite via `sqlite3`). It implements the full loop against a **synthetic game** ("Aurora Plains") with deterministic simulated telemetry, so the pipeline — profiling, backup, baseline, bounded candidate trials, verdicts, rollback — runs and is tested on any OS and in CI. Windows-specific integrations are implemented behind the same interfaces and require validation on a real machine (Phase 0 exit criterion).

| README module | Status |
|---|---|
| Hardware profiler | `WindowsProfiler` (PowerShell/CIM, read-only, no admin) + `SimulatedProfiler` fallback; VRAM >4 GB wraparound detected and reported as unknown |
| Telemetry / metrics | `compute_metrics` (avg FPS, documented 1% low, p99, spikes, consistency), `compare_runs` (within-group variance; gains inside the noise band are inconclusive), raw frame times retained |
| Benchmark collectors | `SimulatedCollector` (deterministic, bottleneck-aware model) and `PresentMonCollector` (CSV wrapper — **validate CLI flags on a target Windows machine before use**) |
| Game adapter layer | `GameAdapter`/`ConfigFileAdapter` base classes + synthetic adapter; catalog-validated values only, atomic writes, per-game backups with SHA-256 manifests, JSONL audit log, one-click restore |
| Optimization engine | Bottleneck estimate → ranked single-setting candidates → bounded trials (keep/reject/inconclusive) → one combined trial of winners → per-goal weighted scoring with quality-floor hard constraint; stops at budget, target, or no gains |
| Profile database | Local SQLite (`~/.pc-optimize/profiles.db`): sessions, per-trial verdicts, and raw frame-time samples per run |
| Reports & profiles | `report` renders a self-contained HTML report (metric cards, trial verdicts, SVG frame-time charts) from any stored session; `export`/`apply-config` move a configuration as validated JSON — catalog-checked, backed up before applying |
| Game-update safety | Config keys absent from the adapter catalog are detected as drift, warned about, and never touched |

Quick start:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/python -m optimize demo          # full loop, restores original by default
.venv/bin/python -m optimize demo --apply  # keep the winning configuration
.venv/bin/python -m optimize restore --game aurora-plains   # one-click rollback
.venv/bin/python -m optimize benchmark --runs 3             # baseline + variance
.venv/bin/python -m optimize report                         # HTML report, latest session
.venv/bin/python -m optimize export                         # portable JSON profile
.venv/bin/python -m optimize apply-config --file <profile.json>
.venv/bin/python -m optimize history
.venv/bin/python -m pytest                 # 84 tests
.venv/bin/ruff check src tests             # lint (configured in pyproject.toml)
```

Safety properties enforced in code: every candidate is validated against the game's catalog before writing; writes are atomic (`tmp` + rename); every session starts from a verified backup; trials always restore the baseline; nothing is applied without an explicit `--apply`; every change is appended to `audit.jsonl`.

Not yet done (next steps, in order): pick and verify a real game + PresentMon on Windows (Phase 0), wire `PresentMonCollector` into the CLI for that adapter, repeat baseline-variance calibration on real hardware, then the desktop UI (Phase 3).

Everything above runs identically on macOS, Linux, and Windows: all Windows-only behavior (CIM hardware queries, PresentMon capture) sits behind interfaces with portable unit tests covering their parsing and failure modes.

## References

Verify the current documentation, versions, licensing, and supported APIs before implementation.

- [Microsoft Learn: Windows APIs](https://learn.microsoft.com/en-us/windows/)
- [PresentMon GitHub repository](https://github.com/GameTechDev/PresentMon)
- [NVIDIA Developer](https://developer.nvidia.com/)
- [NVIDIA App](https://www.nvidia.com/en-us/software/nvidia-app/)
- [CapFrameX](https://www.capframex.com/)

---

## Disclaimer

This project is an optimization assistant, not a guarantee of higher FPS. Improvements depend on the game, hardware, driver, settings exposed by the game, and benchmark conditions. All changes should be reversible and tested on the user's actual system.
