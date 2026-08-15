from __future__ import annotations

import dataclasses
import unittest

from kilix_telemetry.model import (
    FanSensor,
    PaneMetrics,
    ProcessMetrics,
    Snapshot,
    SystemMetrics,
    ThermalSensor,
)


def process(pid: int, ppid: int, cpu: float, rss: int, pss: int | None):
    return ProcessMetrics(
        pid,
        ppid,
        pid * 10,
        0,
        cpu,
        rss,
        pss,
        rss * 2,
        1000,
        f"p{pid}",
        "S",
        1,
        f"p{pid}",
    )


def system() -> SystemMetrics:
    return SystemMetrics(
        cpu_percent=None,
        load_1=0,
        load_5=0,
        load_15=0,
        logical_cpus=4,
        uptime_seconds=0,
        memory_total=1000,
        memory_available=500,
        memory_free=100,
        memory_buffers=0,
        memory_cached=0,
        memory_reclaimable=0,
        memory_shared=0,
        memory_active=0,
        memory_inactive=0,
        memory_anon=0,
        memory_slab=0,
        memory_page_tables=0,
        memory_kernel_stack=0,
        memory_dirty=0,
        memory_writeback=0,
        swap_total=0,
        swap_free=0,
    )


class ModelTests(unittest.TestCase):
    def test_pane_aggregates_only_descendants_and_uses_pss_fallback(self) -> None:
        sample = Snapshot(
            1,
            2,
            3,
            4,
            "boot",
            system(),
            (),
            (
                process(10, 1, 0.5, 100, 80),
                process(11, 10, 0.75, 200, 150),
                process(12, 11, 0.25, 300, None),
                process(20, 1, 8.0, 900, 700),
            ),
        )
        pane = sample.pane(10)
        self.assertEqual(pane.process_count, 3)
        self.assertAlmostEqual(pane.cpu_cores, 1.5)
        self.assertEqual(pane.rss_bytes, 600)
        self.assertEqual(pane.proportional_bytes, 530)
        self.assertFalse(pane.complete_pss)
        self.assertEqual(sample.pane(999).process_count, 0)

    def test_to_dict_matches_dataclass_reflection(self) -> None:
        rich_system = dataclasses.replace(
            system(),
            pressure={"cpu": {"some_avg10": 1.5}, "memory": {"full_avg10": 0.5}},
            vm={"pgfault": 10, "oom_kill": 0},
            per_cpu_percent=(10.0, None),
            cpu_frequency_mhz=(2400.0, None),
            memory_huge_total=8,
        )
        sample = Snapshot(
            1,
            2,
            3,
            4,
            "boot",
            rich_system,
            (
                ThermalSensor(
                    "zone:0:x86_pkg_temp",
                    "CPU",
                    "zone 0",
                    "thermal-zone",
                    55.5,
                    90.0,
                    100.0,
                ),
                ThermalSensor(
                    "hwmon:hwmon2:nvme:temp1", "NVMe", "Composite", "hwmon2", 41.0
                ),
            ),
            (
                process(10, 1, 0.5, 100, 80),
                process(11, 10, 0.25, 50, None),
            ),
            fans=(
                FanSensor("fan:hwmon2:nvme:fan1", "NVMe", "Controller", "hwmon2", 1200),
            ),
            panes=(PaneMetrics(10, 2, 0.75, 150, 130, False),),
            processes_total=5,
            processes_truncated=True,
        )
        self.assertEqual(sample.to_dict(), dataclasses.asdict(sample))

    def test_round_trip_rejects_an_unknown_schema(self) -> None:
        sample = Snapshot(1, 2, 3, 4, "boot", system(), (), ())
        decoded = Snapshot.from_dict(sample.to_dict())
        self.assertEqual(decoded, sample)
        value = sample.to_dict()
        value["schema"] = 99
        with self.assertRaises(ValueError):
            Snapshot.from_dict(value)

    def test_precomputed_pane_metrics_survive_a_compacted_process_table(self) -> None:
        expected = PaneMetrics(10, 7, 2.5, 800, 600, True)
        sample = Snapshot(
            1,
            2,
            3,
            4,
            "boot",
            system(),
            (),
            (),
            panes=(expected,),
            processes_total=100,
            processes_truncated=True,
        )
        decoded = Snapshot.from_dict(sample.to_dict())
        self.assertEqual(decoded.pane(10), expected)
        self.assertEqual(decoded.processes_total, 100)
        self.assertTrue(decoded.processes_truncated)


if __name__ == "__main__":
    unittest.main()
