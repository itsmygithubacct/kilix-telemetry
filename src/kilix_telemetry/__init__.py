"""Shared, low-overhead Linux telemetry for Kilix components."""

from .client import TelemetryClient, ensure_running
from .collect import LinuxCollector
from .model import (
    PaneMetrics,
    ProcessMetrics,
    Snapshot,
    SystemMetrics,
    ThermalSensor,
)
from .registry import PaneRegistry
from .ring import RingReader, RingWriter, TelemetryPaths, resolve_paths

__version__ = "0.1.0"
TELEMETRY_API_VERSION = (1, 0)

__all__ = [
    "TELEMETRY_API_VERSION",
    "LinuxCollector",
    "PaneMetrics",
    "PaneRegistry",
    "ProcessMetrics",
    "RingReader",
    "RingWriter",
    "Snapshot",
    "SystemMetrics",
    "TelemetryClient",
    "TelemetryPaths",
    "ThermalSensor",
    "__version__",
    "ensure_running",
    "resolve_paths",
]
