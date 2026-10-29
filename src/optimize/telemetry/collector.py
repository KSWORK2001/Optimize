"""Benchmark collector interface.

README: 'Keep telemetry collection and config modification behind interfaces
so they can be replaced.' A collector turns the current game configuration
into a CaptureResult of raw frame times. Two implementations exist:

- SimulatedCollector: deterministic model, used for development, CI, and the
  end-to-end demo. Works on any OS.
- PresentMonCollector: wraps the Intel PresentMon CLI on Windows for real
  games. Requires validation on a target Windows machine (Phase 0 exit
  criterion).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from optimize.models import CaptureResult, HardwareProfile


class BenchmarkCollector(ABC):
    """Captures frame-time telemetry for one benchmark run."""

    @abstractmethod
    def run(
        self,
        settings: Mapping[str, str],
        hardware: HardwareProfile,
        seconds: float = 20.0,
        seed: int = 0,
    ) -> CaptureResult:
        """Run one capture. `seed` exists so runs are repeatable where possible."""
        raise NotImplementedError
