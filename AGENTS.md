# AGENTS.md — project instructions and handoff state

Instructions for any coding agent (or human) picking up this repository.
**The README is the design spec** — read it before changing architecture.
This file tells you where the project stands and what to do next.

## What this project is

A hardware-aware PC game optimization tool: profile the machine, benchmark a
game, test a bounded set of supported settings changes, keep only measured
improvements, and roll everything back safely. Windows is the target platform;
the core is deliberately portable Python so it develops and tests anywhere.

- Package: `pc-optimize`, import name `optimize`, Python 3.10+, stdlib only.
- Layout: `src/optimize/` (models, hardware, telemetry, adapters, engine, db,
  reporting, cli), `tests/` (pytest), data at `~/.pc-optimize` (override with
  `--data-dir` or `PC_OPTIMIZE_HOME`).

## Current state (as of the last commit)

Milestone 1 prototype is complete and validated against the synthetic game
"Aurora Plains" with deterministic simulated telemetry: **84 tests pass,
ruff is clean**. Everything portable is done and tested:

- Full loop: hardware → backup → baseline → ranked candidate trials
  (keep/reject/inconclusive) → combined trial → recommendation → restore or
  `--apply`. See `src/optimize/engine/`.
- Metrics: documented 1% low, p99, spikes, consistency, within-group variance
  significance (`telemetry/metrics.py`).
- Adapters: catalog-validated settings only, atomic writes, SHA-256 backups,
  JSONL audit log, one-click restore, unknown-key drift detection
  (`adapters/`).
- SQLite profile DB with raw frame times; HTML reports with SVG frame-time
  charts; JSON profile export/import (`db.py`, `reporting.py`).
- CLI: `demo`, `optimize`, `benchmark`, `restore`, `report`, `export`,
  `apply-config`, `history`, `hardware`.

**Not yet validated on real hardware.** `hardware/profiler.py::WindowsProfiler`
(PowerShell/CIM) and `telemetry/presentmon.py::PresentMonCollector` are
implemented and unit-tested for parsing/failure modes only. That is the next
work item.

## Setup (Windows)

```powershell
git clone https://github.com/KSWORK2001/Optimize.git
cd Optimize
py -3 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest          # must pass: 84 tests
.venv\Scripts\ruff check src tests      # must pass
```

macOS/Linux setup is identical minus `py -3` (use `python3`). Both platforms
run the same suite; the synthetic game keeps everything testable everywhere.

## Where to pick up: Phase 0 (feasibility spike on this machine)

Work through these in order. Each step names the file to change and its
acceptance criterion. Do not skip to Phase 2 work first.

1. **Run the suite** (command above). If anything fails on Windows, fix the
   portability bug before proceeding — the whole design depends on the
   portable core staying green.

2. **Validate the hardware profiler.**
   `.venv\Scripts\python -m optimize hardware --real-hardware`
   Known risks in `src/optimize/hardware/profiler.py`: the PowerShell/CIM
   query's JSON shape, `CurrentRefreshRate` arriving as a string, and
   `AdapterRAM` (32-bit; wraps above 4 GB — currently reported as unknown,
   which is correct behavior). Acceptance: correct model names, cores,
   resolution/refresh, and VRAM for this machine; failures degrade to the
   simulated profile with a message, never a crash.
   Note: accurate VRAM above 4 GB needs DXGI or the registry
   `qwMemorySize` value — if you add it, keep it in this file and document
   the caveat.

3. **Validate PresentMon capture.**
   - Install Intel PresentMon (github.com/GameTechDev/PresentMon, MIT —
     verify license for the bundled version). ETW capture requires an
     elevated shell; this is the one documented operation that needs admin
     (README allows exactly this kind of exception).
   - Run `PresentMon.exe --help` and reconcile the flags against
     `argv_template` in `src/optimize/telemetry/presentmon.py`; then capture
     any GPU workload and confirm the CSV actually has the
     `msBetweenPresents` column the parser expects.
   - Wire a manual capture through `PresentMonCollector.run()` from a
     scratch script (no need to touch the CLI yet).
   Acceptance: a real capture parses into `CaptureResult` and produces
   sane `compute_metrics` output. Record the validated flags in this file.

4. **Calibrate benchmark variance.**
   `.venv\Scripts\python -m optimize benchmark --runs 5 --seconds 30` on a
   real workload; compare run-to-run CV against the defaults in
   `telemetry/metrics.py` (`min_gain_pct=3.0`, `noise_factor=2.0`). Adjust
   only with data. Acceptance: documented variance for this machine in the
   session notes/README.

5. **Pick the first real game (start of Phase 2).** Criteria (README Phase 0):
   text-based documented config (INI/JSON) in a predictable path, a built-in
   repeatable benchmark, and no anti-cheat conflict with config-file editing
   plus passive ETW frame capture (prefer single-player titles; CapFrameX
   compatibility is a good signal). Write the adapter by subclassing
   `ConfigFileAdapter` (`adapters/base.py`) — see `adapters/synthetic.py`
   for the shape: catalog of `SettingSpec`s (costs are ranking heuristics,
   not promises), detection, config path. Register it in `make_adapter`
   (`cli.py`). Acceptance: detect → backup → read/apply/restore round trip
   on the real game, then a baseline + one-setting trial with real
   PresentMon capture.

## Invariants — never violate these

From the README; they are the product's core promises:

- Every setting change goes through catalog validation
  (`SettingsCatalog.validate`). No unvalidated writes, no unknown keys.
- Back up before any write; restore is always one command
  (`pc-optimize restore --game <id>`); every change lands in `audit.jsonl`.
- Nothing applies without explicit user action (`--apply` / `apply-config`);
  the optimizer always leaves the original config in place otherwise.
- No injection, DLL loading, memory patching, or anti-cheat interaction.
  PresentMon observes ETW events passively — keep it that way.
- No overclocking/voltage/BIOS/registry tweaks. No telemetry leaves the
  machine; there is no network code, keep it that way.
- Optimizer trials always restore the baseline configuration afterward
  (enforced in `engine/search.py`; keep it enforced).

## Conventions

- Tests for every behavior change; `pytest` and `ruff check src tests` stay
  green in every commit. Windows-only paths get portable unit tests
  (parse templates, failure modes) — see `tests/test_presentmon.py`.
- Deterministic seeds everywhere in simulation (`SimulatedCollector`, search
  seed blocks). Real captures have no seeds — that's what the variance
  machinery is for.
- Don't create a universal config editor; one adapter per game, version-aware.
- Console output stays plain text, no dependencies beyond the stdlib unless
  the README's stack table is revised first.

## Log of validated Windows facts

(Fill this in as Phase 0 steps complete so the next session doesn't re-derive.)

- PresentMon flags validated: _pending_
- Profiler output verified on: _pending_
- Measured run-to-run variance: _pending_
- First real game chosen: _pending_
