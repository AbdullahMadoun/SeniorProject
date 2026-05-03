from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import dataclass, asdict


@dataclass
class CapabilityReport:
    os_name: str
    cpu_name: str
    cores: int
    logical_processors: int
    ram_gb: float
    free_ram_gb: float
    gpu_name: str
    gpu_vram_gb: float
    wsl_available: bool
    recommendation: str
    rationale: list[str]


def _powershell_json(command: str) -> dict:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}


def inspect_windows_device() -> CapabilityReport:
    computer = _powershell_json(
        "Get-CimInstance Win32_ComputerSystem | "
        "Select-Object TotalPhysicalMemory | ConvertTo-Json -Compress"
    )
    cpu = _powershell_json(
        "Get-CimInstance Win32_Processor | "
        "Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress"
    )
    gpu = _powershell_json(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json -Compress"
    )
    os_info = _powershell_json(
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption,FreePhysicalMemory | ConvertTo-Json -Compress"
    )
    wsl_available = shutil.which("wsl") is not None

    ram_gb = int(computer.get("TotalPhysicalMemory", 0)) / (1024 ** 3)
    free_ram_gb = int(os_info.get("FreePhysicalMemory", 0)) * 1024 / (1024 ** 3)
    gpu_vram_gb = int(gpu.get("AdapterRAM", 0) or 0) / (1024 ** 3)

    rationale: list[str] = []
    if ram_gb < 16:
        rationale.append("System RAM is below the preferred 16 GB baseline for comfortable Gazebo-class simulation.")
    if gpu_vram_gb < 2:
        rationale.append("GPU VRAM is limited, so integrated-graphics rendering is a constraint for 3D simulation.")
    if free_ram_gb < 2:
        rationale.append("Current free RAM is low, which increases the risk of instability for heavy simulators.")

    if rationale:
        recommendation = "Use lightweight visualization as the baseline; keep full 3D simulation optional."
    else:
        recommendation = "Machine can support a serious PX4/Gazebo trial."

    return CapabilityReport(
        os_name=os_info.get("Caption", platform.platform()),
        cpu_name=cpu.get("Name", "Unknown CPU"),
        cores=int(cpu.get("NumberOfCores", 0)),
        logical_processors=int(cpu.get("NumberOfLogicalProcessors", 0)),
        ram_gb=round(ram_gb, 2),
        free_ram_gb=round(free_ram_gb, 2),
        gpu_name=gpu.get("Name", "Unknown GPU"),
        gpu_vram_gb=round(gpu_vram_gb, 2),
        wsl_available=wsl_available,
        recommendation=recommendation,
        rationale=rationale,
    )


def generate_report() -> CapabilityReport:
    if platform.system() == "Windows":
        return inspect_windows_device()
    raise RuntimeError("Capability report currently supports Windows only in this repo.")


def to_markdown(report: CapabilityReport) -> str:
    lines = [
        "# Phase 0 Capability Report",
        "",
        f"- OS: `{report.os_name}`",
        f"- CPU: `{report.cpu_name}`",
        f"- Cores / Threads: `{report.cores} / {report.logical_processors}`",
        f"- RAM: `{report.ram_gb:.2f} GB` total, `{report.free_ram_gb:.2f} GB` free",
        f"- GPU: `{report.gpu_name}`",
        f"- GPU VRAM: `{report.gpu_vram_gb:.2f} GB`",
        f"- WSL available: `{report.wsl_available}`",
        "",
        "## Recommendation",
        "",
        report.recommendation,
        "",
        "## Rationale",
        "",
    ]
    if report.rationale:
        lines.extend(f"- {item}" for item in report.rationale)
    else:
        lines.append("- No major blockers detected for a 3D simulation trial.")
    return "\n".join(lines) + "\n"


def to_dict(report: CapabilityReport) -> dict:
    return asdict(report)
