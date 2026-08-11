from __future__ import annotations

import unittest

from kilix_telemetry.model import (
    PaneMetrics,
    ProcessMetrics,
    Snapshot,
    SystemMetrics,
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
