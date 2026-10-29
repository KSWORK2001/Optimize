"""PresentMon-based frame-time capture for real games on Windows.

Wraps the Intel PresentMon command line tool
(https://github.com/GameTechDev/PresentMon). Phase 0 requires validating the
exact CLI flags against the installed version before relying on them; the
argv template is therefore configurable. Nothing here is imported or executed
on non-Windows development machines — constructing the collector without a
PresentMon binary raises a clear error instead of failing obscurely.

The collector does not touch the game process (no injection, no hooks); it
only observes ETW events, matching the README safety rules.
"""

from __future__ import annotations

import csv
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from optimize.models import CaptureResult, HardwareProfile
from optimize.telemetry.collector import BenchmarkCollector

# PresentMon CSV column holding the interval between presents, in milliseconds.
FRAME_TIME_COLUMN = "msBetweenPresents"


class TelemetryUnavailableError(RuntimeError):
    pass


class PresentMonCollector(BenchmarkCollector):
    """Captures frame times of a running game process via PresentMon.

    Workflow: the user (or the game adapter) starts the game's built-in
    benchmark, then `run` launches a timed capture against `process_name`.
    `settings` and `hardware` are accepted for interface compatibility; the
    orchestrator is responsible for having applied the settings beforehand.
    """

    def __init__(
        self,
        exe_path: str | Path,
        process_name: str,
        argv_template: list[str] | None = None,
    ) -> None:
        self.exe_path = Path(exe_path)
        self.process_name = process_name
        # Defaults follow the modern PresentMon CLI; verify per installed version.
        self.argv_template = argv_template or [
            "--output_csv", "{csv}",
            "--process_name", "{process}",
            "--timed", "{seconds}",
            "--no_console_stats",
            "--stop_existing_session",
        ]

    def build_argv(self, csv_path: Path, seconds: float) -> list[str]:
        """Expand the argv template for one capture (unit-testable on any OS)."""
        return [
            str(self.exe_path),
            *[
                arg.replace("{csv}", str(csv_path))
                .replace("{process}", self.process_name)
                .replace("{seconds}", str(int(seconds)))
                for arg in self.argv_template
            ],
        ]

    def run(
        self,
        settings: Mapping[str, str],
        hardware: HardwareProfile,
        seconds: float = 20.0,
        seed: int = 0,
    ) -> CaptureResult:
        del settings, hardware, seed  # not used: passive capture of a live process
        if not self.exe_path.exists():
            raise TelemetryUnavailableError(
                f"PresentMon not found at {self.exe_path}. Install it and pass "
                "the correct path; see https://github.com/GameTechDev/PresentMon"
            )

        with tempfile.TemporaryDirectory(prefix="pc-optimize-") as tmp:
            csv_path = Path(tmp) / "capture.csv"
            proc = subprocess.run(
                self.build_argv(csv_path, seconds),
                capture_output=True,
                text=True,
                timeout=seconds * 3 + 30,
                check=False,
            )
            if proc.returncode != 0:
                raise TelemetryUnavailableError(
                    f"PresentMon exited with {proc.returncode}: {proc.stderr.strip()[:500]}"
                )
            frame_times = _parse_frame_times(csv_path)

        return CaptureResult(frame_times_ms=tuple(frame_times))


def _parse_frame_times(csv_path: Path) -> list[float]:
    if not csv_path.exists():
        raise TelemetryUnavailableError(
            f"PresentMon produced no output at {csv_path}; "
            "check that the game process name is correct and the benchmark was running"
        )
    frames: list[float] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or FRAME_TIME_COLUMN not in reader.fieldnames:
            raise TelemetryUnavailableError(
                f"PresentMon CSV is missing the {FRAME_TIME_COLUMN!r} column; "
                "the installed version may use different flags or output layout"
            )
        for row in reader:
            raw = row.get(FRAME_TIME_COLUMN)
            if raw in (None, "", "N/A"):
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value > 0:
                frames.append(value)
    if not frames:
        raise TelemetryUnavailableError(
            "PresentMon CSV contained no usable frame times; was the game running?"
        )
    return frames
