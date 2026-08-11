"""Versioned telemetry records shared by the daemon and every consumer."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class ThermalSensor:
    key: str
    chip: str
    label: str
    source: str
    celsius: float
    warning_celsius: float | None = None
    critical_celsius: float | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ThermalSensor:
        def optional(name: str) -> float | None:
            raw = value.get(name)
            return None if raw is None else _finite_float(raw)

        return cls(
            key=str(value.get("key", ""))[:256],
            chip=str(value.get("chip", ""))[:80],
            label=str(value.get("label", ""))[:80],
            source=str(value.get("source", ""))[:80],
            celsius=_finite_float(value.get("celsius")),
            warning_celsius=optional("warning_celsius"),
            critical_celsius=optional("critical_celsius"),
        )


@dataclass(frozen=True, slots=True)
class FanSensor:
    key: str
    chip: str
    label: str
    source: str
    rpm: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FanSensor:
        return cls(
            key=str(value.get("key", ""))[:256],
            chip=str(value.get("chip", ""))[:80],
            label=str(value.get("label", ""))[:80],
            source=str(value.get("source", ""))[:80],
            rpm=min(200_000, _nonnegative_int(value.get("rpm"))),
        )


@dataclass(frozen=True, slots=True)
class ProcessMetrics:
    pid: int
    ppid: int
    start_ticks: int
    cpu_ticks: int
    cpu_cores: float
    rss_bytes: int
    pss_bytes: int | None
    virtual_bytes: int
    uid: int
    name: str
    state: str
    threads: int
    command: str
    anon_bytes: int = 0
    file_bytes: int = 0
    shared_bytes: int = 0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProcessMetrics:
        pss = value.get("pss_bytes")
        return cls(
            pid=_nonnegative_int(value.get("pid")),
            ppid=_nonnegative_int(value.get("ppid")),
            start_ticks=_nonnegative_int(value.get("start_ticks")),
            cpu_ticks=_nonnegative_int(value.get("cpu_ticks")),
            cpu_cores=max(0.0, _finite_float(value.get("cpu_cores"))),
            rss_bytes=_nonnegative_int(value.get("rss_bytes")),
            pss_bytes=None if pss is None else _nonnegative_int(pss),
            virtual_bytes=_nonnegative_int(value.get("virtual_bytes")),
            uid=_nonnegative_int(value.get("uid")),
            name=str(value.get("name", ""))[:80],
            state=str(value.get("state", "?"))[:8],
            threads=max(1, _nonnegative_int(value.get("threads"))),
            command=str(value.get("command", ""))[:4096],
            anon_bytes=_nonnegative_int(value.get("anon_bytes")),
            file_bytes=_nonnegative_int(value.get("file_bytes")),
            shared_bytes=_nonnegative_int(value.get("shared_bytes")),
        )


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    cpu_percent: float | None
    load_1: float
    load_5: float
    load_15: float
    logical_cpus: int
    uptime_seconds: float
    memory_total: int
    memory_available: int
    memory_free: int
    memory_buffers: int
    memory_cached: int
    memory_reclaimable: int
    memory_shared: int
    memory_active: int
    memory_inactive: int
    memory_anon: int
    memory_slab: int
    memory_page_tables: int
    memory_kernel_stack: int
    memory_dirty: int
    memory_writeback: int
    swap_total: int
    swap_free: int
    pressure: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    vm: Mapping[str, int] = field(default_factory=dict)
    per_cpu_percent: tuple[float | None, ...] = ()
    cpu_frequency_mhz: tuple[float | None, ...] = ()
    memory_huge_total: int = 0
    memory_huge_free: int = 0
    memory_huge_page_size: int = 0

    @property
    def memory_used(self) -> int:
        return max(0, self.memory_total - min(self.memory_total, self.memory_available))

    @property
    def memory_percent(self) -> float:
        if self.memory_total <= 0:
            return 0.0
        return 100.0 * self.memory_used / self.memory_total

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SystemMetrics:
        cpu = value.get("cpu_percent")
        pressure: dict[str, dict[str, float]] = {}
        raw_pressure = value.get("pressure", {})
        if isinstance(raw_pressure, Mapping):
            for resource, lines in raw_pressure.items():
                if isinstance(lines, Mapping):
                    pressure[str(resource)] = {
                        str(key): _finite_float(number) for key, number in lines.items()
                    }
        vm: dict[str, int] = {}
        raw_vm = value.get("vm", {})
        if isinstance(raw_vm, Mapping):
            vm = {str(key): _nonnegative_int(number) for key, number in raw_vm.items()}

        def optional_floats(name: str) -> tuple[float | None, ...]:
            raw = value.get(name, ())
            if not isinstance(raw, (list, tuple)):
                return ()
            result: list[float | None] = []
            for item in raw[:4096]:
                if item is None:
                    result.append(None)
                    continue
                parsed = _finite_float(item, -1.0)
                result.append(parsed if parsed >= 0.0 else None)
            return tuple(result)

        return cls(
            cpu_percent=None
            if cpu is None
            else max(0.0, min(100.0, _finite_float(cpu))),
            load_1=max(0.0, _finite_float(value.get("load_1"))),
            load_5=max(0.0, _finite_float(value.get("load_5"))),
            load_15=max(0.0, _finite_float(value.get("load_15"))),
            logical_cpus=max(1, _nonnegative_int(value.get("logical_cpus"))),
            uptime_seconds=max(0.0, _finite_float(value.get("uptime_seconds"))),
            memory_total=_nonnegative_int(value.get("memory_total")),
            memory_available=_nonnegative_int(value.get("memory_available")),
            memory_free=_nonnegative_int(value.get("memory_free")),
            memory_buffers=_nonnegative_int(value.get("memory_buffers")),
            memory_cached=_nonnegative_int(value.get("memory_cached")),
            memory_reclaimable=_nonnegative_int(value.get("memory_reclaimable")),
            memory_shared=_nonnegative_int(value.get("memory_shared")),
            memory_active=_nonnegative_int(value.get("memory_active")),
            memory_inactive=_nonnegative_int(value.get("memory_inactive")),
            memory_anon=_nonnegative_int(value.get("memory_anon")),
            memory_slab=_nonnegative_int(value.get("memory_slab")),
            memory_page_tables=_nonnegative_int(value.get("memory_page_tables")),
            memory_kernel_stack=_nonnegative_int(value.get("memory_kernel_stack")),
            memory_dirty=_nonnegative_int(value.get("memory_dirty")),
            memory_writeback=_nonnegative_int(value.get("memory_writeback")),
            swap_total=_nonnegative_int(value.get("swap_total")),
            swap_free=_nonnegative_int(value.get("swap_free")),
            pressure=pressure,
            vm=vm,
            per_cpu_percent=optional_floats("per_cpu_percent"),
            cpu_frequency_mhz=optional_floats("cpu_frequency_mhz"),
            memory_huge_total=_nonnegative_int(value.get("memory_huge_total")),
            memory_huge_free=_nonnegative_int(value.get("memory_huge_free")),
            memory_huge_page_size=_nonnegative_int(value.get("memory_huge_page_size")),
        )


@dataclass(frozen=True, slots=True)
class PaneMetrics:
    root_pid: int
    process_count: int
    cpu_cores: float
    rss_bytes: int
    proportional_bytes: int
    complete_pss: bool


@dataclass(frozen=True, slots=True)
class Snapshot:
    sequence: int
    wall_time_ns: int
    monotonic_ns: int
    interval_ns: int
    boot_id: str
    system: SystemMetrics
    thermal: tuple[ThermalSensor, ...]
    processes: tuple[ProcessMetrics, ...]
    fans: tuple[FanSensor, ...] = ()
    schema: int = SCHEMA_VERSION

    @property
    def hottest_celsius(self) -> float | None:
        return max((sensor.celsius for sensor in self.thermal), default=None)

    def pane(self, root_pid: int) -> PaneMetrics:
        """Aggregate one pane's root process and all current descendants.

        CPU is expressed in logical cores: 1.0 means the tree consumed one
        complete logical CPU during the preceding sample interval. PID start
        ticks are retained in each record so consumers can reject recycled
        identities when comparing snapshots.
        """
        root_pid = _nonnegative_int(root_pid)
        by_pid = {process.pid: process for process in self.processes}
        if root_pid <= 0 or root_pid not in by_pid:
            return PaneMetrics(root_pid, 0, 0.0, 0, 0, False)
        children: dict[int, list[int]] = {}
        for process in self.processes:
            children.setdefault(process.ppid, []).append(process.pid)
        selected: list[ProcessMetrics] = []
        pending = [root_pid]
        seen: set[int] = set()
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            process = by_pid.get(pid)
            if process is None:
                continue
            selected.append(process)
            pending.extend(children.get(pid, ()))
        pss_values = [process.pss_bytes for process in selected]
        complete_pss = bool(selected) and all(value is not None for value in pss_values)
        proportional = sum(
            process.rss_bytes if process.pss_bytes is None else process.pss_bytes
            for process in selected
        )
        return PaneMetrics(
            root_pid=root_pid,
            process_count=len(selected),
            cpu_cores=sum(process.cpu_cores for process in selected),
            rss_bytes=sum(process.rss_bytes for process in selected),
            proportional_bytes=proportional,
            complete_pss=complete_pss,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Snapshot:
        schema = _nonnegative_int(value.get("schema"))
        if schema != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported telemetry schema {schema}; expected {SCHEMA_VERSION}"
            )
        raw_system = value.get("system")
        if not isinstance(raw_system, Mapping):
            raise TypeError("telemetry snapshot has no system record")
        raw_thermal = value.get("thermal", ())
        raw_processes = value.get("processes", ())
        raw_fans = value.get("fans", ())
        if (
            not isinstance(raw_thermal, (list, tuple))
            or not isinstance(raw_processes, (list, tuple))
            or not isinstance(raw_fans, (list, tuple))
        ):
            raise TypeError("telemetry snapshot arrays are malformed")
        return cls(
            sequence=_nonnegative_int(value.get("sequence")),
            wall_time_ns=_nonnegative_int(value.get("wall_time_ns")),
            monotonic_ns=_nonnegative_int(value.get("monotonic_ns")),
            interval_ns=_nonnegative_int(value.get("interval_ns")),
            boot_id=str(value.get("boot_id", ""))[:128],
            system=SystemMetrics.from_dict(raw_system),
            thermal=tuple(
                ThermalSensor.from_dict(item)
                for item in raw_thermal
                if isinstance(item, Mapping)
            ),
            processes=tuple(
                ProcessMetrics.from_dict(item)
                for item in raw_processes
                if isinstance(item, Mapping)
            ),
            fans=tuple(
                FanSensor.from_dict(item)
                for item in raw_fans
                if isinstance(item, Mapping)
            ),
            schema=schema,
        )
