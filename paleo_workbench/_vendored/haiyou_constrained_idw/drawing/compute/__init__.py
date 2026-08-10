"""Compute backends and performance controls for heavy map generation."""

from drawing.compute.performance import (
    ComputeSettings,
    get_compute_settings,
    set_cpu_percent,
    set_gpu_percent,
    set_hardware_accel,
)

__all__ = [
    "ComputeSettings",
    "get_compute_settings",
    "set_cpu_percent",
    "set_gpu_percent",
    "set_hardware_accel",
]
