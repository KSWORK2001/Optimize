"""Synthetic game adapter: 'Aurora Plains' (fictional).

Aurora Plains is a simulated open-world game used to validate the entire
optimization loop — backup, baseline, candidate trials, comparison, rollback —
on any OS and in CI without touching a real installation. Its settings live
in an ordinary JSON file inside the tool's data directory, so the real
backup/atomic-write/audit code paths are exercised, not mocked away.

The cost numbers (gpu_ms/cpu_ms/vram_mb/quality) model a GPU-bound
open-world title on mid-range hardware; see telemetry/simulated.py for how
they turn into frame times.
"""

from __future__ import annotations

import json
from pathlib import Path

from optimize.adapters.base import ConfigFileAdapter
from optimize.models import SettingsCatalog, SettingSpec, SettingValue

AURORA_CATALOG = SettingsCatalog(
    game_id="aurora-plains",
    title="Aurora Plains (synthetic benchmark game)",
    specs=(
        SettingSpec(
            key="resolution_scale",
            label="Render resolution scale (%)",
            bottleneck="gpu",
            values=(
                SettingValue("50", quality=0.55, gpu_ms=2.6),
                SettingValue("65", quality=0.68, gpu_ms=3.9),
                SettingValue("80", quality=0.82, gpu_ms=5.3),
                SettingValue("100", quality=1.00, gpu_ms=7.2),
            ),
            default="100",
        ),
        SettingSpec(
            key="shadow_quality",
            label="Shadow quality",
            bottleneck="gpu",
            values=(
                SettingValue("low", quality=0.50, gpu_ms=0.8),
                SettingValue("medium", quality=0.75, gpu_ms=1.7),
                SettingValue("high", quality=0.90, gpu_ms=3.4),
                SettingValue("ultra", quality=1.00, gpu_ms=4.6),
            ),
            default="high",
        ),
        SettingSpec(
            key="anti_aliasing",
            label="Anti-aliasing",
            bottleneck="gpu",
            values=(
                SettingValue("off", quality=0.50, gpu_ms=0.0),
                SettingValue("fxaa", quality=0.70, gpu_ms=0.5),
                SettingValue("smaa", quality=0.85, gpu_ms=0.9),
                SettingValue("taa", quality=0.95, gpu_ms=1.5),
            ),
            default="taa",
        ),
        SettingSpec(
            key="texture_quality",
            label="Texture quality",
            bottleneck="memory",
            values=(
                SettingValue("medium", quality=0.60, gpu_ms=0.5, vram_mb=1300),
                SettingValue("high", quality=0.85, gpu_ms=0.7, vram_mb=2400),
                SettingValue("ultra", quality=1.00, gpu_ms=0.9, vram_mb=3700),
            ),
            default="high",
        ),
        SettingSpec(
            key="draw_distance",
            label="Draw distance",
            bottleneck="cpu",
            restart_required=True,
            values=(
                SettingValue("medium", quality=0.60, cpu_ms=3.2),
                SettingValue("far", quality=0.85, cpu_ms=4.6),
                SettingValue("ultra", quality=1.00, cpu_ms=6.1),
            ),
            default="far",
        ),
        SettingSpec(
            key="crowd_density",
            label="Crowd density",
            bottleneck="cpu",
            values=(
                SettingValue("low", quality=0.50, cpu_ms=1.8),
                SettingValue("medium", quality=0.80, cpu_ms=3.0),
                SettingValue("high", quality=1.00, cpu_ms=4.2),
            ),
            default="medium",
        ),
    ),
)


class SyntheticGameAdapter(ConfigFileAdapter):
    """File-backed adapter for the fictional Aurora Plains game."""

    game_id = AURORA_CATALOG.game_id
    title = AURORA_CATALOG.title

    def __init__(self, data_root: Path, install: bool = True) -> None:
        super().__init__(data_root, config_path=data_root / self.game_id / "settings.json")
        if install:
            self.ensure_installed()

    def catalog(self) -> SettingsCatalog:
        return AURORA_CATALOG

    def ensure_installed(self) -> None:
        """Create the default configuration on first run (our own data dir only)."""
        if self.config_path.exists():
            return
        defaults = {spec.key: spec.default for spec in AURORA_CATALOG.specs}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
