"""Hardware profiler (README: main module 1).

Collects only what optimization needs, through supported OS interfaces.
On Windows this queries CIM/WMI via PowerShell (no third-party packages).
Every metric is optional: if a query fails or returns nothing, the field is
left empty rather than guessed.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys

from optimize.models import HardwareProfile

# Known caveat: AdapterRAM is a 32-bit unsigned value and wraps above 4 GB.
# When it looks implausible for the GPU model we leave VRAM at 0 and the
# caller treats it as unknown.
IMPLAUSIBLE_ADAPTER_RAM_MB = 4095

_QUERY = (
    "$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1;"
    "$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1;"
    "$ram = Get-CimInstance Win32_PhysicalMemory;"
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
    "@{"
    " cpu_model = $cpu.Name;"
    " cpu_cores = $cpu.NumberOfLogicalProcessors;"
    " gpu_model = $gpu.Name;"
    " vram_mb = [math]::Round($gpu.AdapterRAM / 1MB);"
    " res = \"$($gpu.CurrentHorizontalResolution)x$($gpu.CurrentVerticalResolution)\";"
    " refresh = $gpu.CurrentRefreshRate;"
    " driver = $gpu.DriverVersion;"
    " ram_gb = [math]::Round(($ram | Measure-Object Capacity -Sum).Sum / 1GB);"
    "} | ConvertTo-Json -Compress"
)


class WindowsProfiler:
    """Read-only hardware detection via PowerShell / CIM (no admin required)."""

    source = "windows-cim"

    def profile(self) -> HardwareProfile:
        raw = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _QUERY],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if raw.returncode != 0:
            raise RuntimeError(f"hardware query failed: {raw.stderr.strip()[:300]}")
        data = json.loads(raw.stdout)

        vram_mb = int(data.get("vram_mb") or 0)
        if vram_mb >= IMPLAUSIBLE_ADAPTER_RAM_MB:
            vram_mb = 0  # wrapped value; report unknown rather than wrong

        return HardwareProfile(
            cpu_model=str(data.get("cpu_model") or "unknown CPU").strip(),
            cpu_cores=int(data.get("cpu_cores") or 0),
            gpu_model=str(data.get("gpu_model") or "unknown GPU").strip(),
            vram_mb=vram_mb,
            ram_gb=int(data.get("ram_gb") or 0),
            display_resolution=str(data.get("res") or "unknown"),
            refresh_rate_hz=int(data.get("refresh") or 0),
            os=f"Windows ({platform.release()})",
            driver_version=(str(data["driver"]) if data.get("driver") else None),
            source=self.source,
        )


class SimulatedProfiler:
    """Fixed mid-range profile so the pipeline runs on any development machine."""

    source = "simulated"

    def profile(self) -> HardwareProfile:
        return HardwareProfile(
            cpu_model="Simulated 6-core CPU (reference tier)",
            cpu_cores=12,
            gpu_model="Simulated mid-range GPU (reference tier)",
            vram_mb=6144,
            ram_gb=16,
            display_resolution="1920x1080",
            refresh_rate_hz=144,
            os=f"{platform.system()} (simulated target: Windows 11)",
            driver_version="simulated-566.36",
            source=self.source,
        )


def detect_hardware(prefer_simulated: bool = False) -> HardwareProfile:
    """Return the best available profile. Windows first, simulated fallback."""
    if not prefer_simulated and sys.platform == "win32":
        try:
            return WindowsProfiler().profile()
        except Exception as exc:  # degrade to the simulated profile, don't crash
            profile = SimulatedProfiler().profile()
            return HardwareProfile(
                **{**profile.__dict__, "source": f"simulated (windows query failed: {exc})"}
            )
    return SimulatedProfiler().profile()
