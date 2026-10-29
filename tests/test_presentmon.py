"""Portable tests for the PresentMon wrapper.

The wrapper itself only runs on Windows with PresentMon installed, but its
CSV parser, argv template, and failure modes are pure logic and must be
correct before Phase 0 validation on a real machine.
"""

import pytest

from optimize.models import HardwareProfile
from optimize.telemetry.presentmon import (
    FRAME_TIME_COLUMN,
    PresentMonCollector,
    TelemetryUnavailableError,
    _parse_frame_times,
)

_CSV = (
    f"Application,{FRAME_TIME_COLUMN},PresentMode\n"
    "game.exe,8.30,Composed: Flip\n"
    "game.exe,8.40,Composed: Flip\n"
    "game.exe,N/A,Hardware Composed: Independent Flip\n"
    "game.exe,,Composed: Flip\n"
    "game.exe,oops,Composed: Flip\n"
    "game.exe,8.20,Composed: Flip\n"
)


def test_parse_skips_unusable_rows(tmp_path):
    csv = tmp_path / "capture.csv"
    csv.write_text(_CSV)
    frames = _parse_frame_times(csv)
    assert frames == [8.30, 8.40, 8.20]


def test_parse_missing_column(tmp_path):
    csv = tmp_path / "capture.csv"
    csv.write_text("Application,SomeOtherColumn\ngame.exe,8.3\n")
    with pytest.raises(TelemetryUnavailableError, match="missing"):
        _parse_frame_times(csv)


def test_parse_no_usable_rows(tmp_path):
    csv = tmp_path / "capture.csv"
    csv.write_text(f"{FRAME_TIME_COLUMN}\nN/A\nN/A\n")
    with pytest.raises(TelemetryUnavailableError, match="no usable frame times"):
        _parse_frame_times(csv)


def test_parse_missing_file(tmp_path):
    with pytest.raises(TelemetryUnavailableError, match="no output"):
        _parse_frame_times(tmp_path / "does-not-exist.csv")


def test_collector_requires_presentmon_binary(tmp_path):
    collector = PresentMonCollector(tmp_path / "nonexistent.exe", "game.exe")
    with pytest.raises(TelemetryUnavailableError, match="PresentMon not found"):
        collector.run({}, _hardware())


def test_argv_template_substitution(tmp_path):
    collector = PresentMonCollector(
        tmp_path / "pm.exe", "game.exe",
        argv_template=["--output_csv", "{csv}", "--process_name", "{process}",
                       "--timed", "{seconds}"],
    )
    argv = collector.build_argv(tmp_path / "out.csv", 12.7)
    assert argv[0] == str(tmp_path / "pm.exe")
    assert argv[argv.index("--output_csv") + 1] == str(tmp_path / "out.csv")
    assert argv[argv.index("--process_name") + 1] == "game.exe"
    assert argv[argv.index("--timed") + 1] == "12"


def _hardware() -> HardwareProfile:
    return HardwareProfile(
        cpu_model="c", cpu_cores=8, gpu_model="g", vram_mb=8192, ram_gb=16,
        display_resolution="1920x1080", refresh_rate_hz=144, os="test",
    )
