from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import linux_tree, process, write

from kilix_telemetry.collect import LinuxCollector


class CollectorTests(unittest.TestCase):
    def test_global_thermal_process_and_pane_deltas_share_one_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            linux_tree(root)
            clock = [1_000_000_000]
            wall = [10_000_000_000]
            collector = LinuxCollector(
                root,
                monotonic_ns=lambda: clock[0],
                wall_time_ns=lambda: wall[0],
                pss_interval=0,
            )
            collector._ticks_per_second = 100
            first = collector.sample(pss_roots=(100,))
            self.assertIsNone(first.system.cpu_percent)
            self.assertEqual(first.system.logical_cpus, 2)
            self.assertEqual(first.system.memory_total, 8192 * 1024)
            self.assertEqual(first.system.pressure["memory"]["some_avg10"], 2.0)
            self.assertEqual(first.system.vm["pgmajfault"], 3)
            self.assertEqual(first.system.per_cpu_percent, (None, None))
            self.assertEqual(first.system.cpu_frequency_mhz, (2400.0, 2500.0))
            self.assertEqual(first.system.memory_huge_total, 8)
            self.assertEqual(first.system.memory_huge_free, 3)
            self.assertEqual(first.system.memory_huge_page_size, 2048 * 1024)
            self.assertEqual(first.hottest_celsius, 72.0)
            self.assertEqual(first.fans[0].rpm, 3210)
            self.assertEqual(first.fans[0].label, "Controller")
            self.assertEqual(first.pane(100).cpu_cores, 0.0)
            self.assertEqual(first.pane(100).proportional_bytes, 2200 * 1024)

            clock[0] += 2_000_000_000
            wall[0] += 2_000_000_000
            write(
                root,
                "proc/stat",
                (
                    "cpu  250 0 100 1650 0 0 0 0 0 0\n"
                    "cpu0 125 0 50 825 0 0 0 0 0 0\n"
                    "cpu1 125 0 50 825 0 0 0 0 0 0\n"
                ),
            )
            process(
                root,
                100,
                "shell",
                ppid=1,
                ticks=200,
                start=10,
                rss_kib=2048,
                pss_kib=1600,
            )
            process(
                root,
                101,
                "worker",
                ppid=100,
                ticks=100,
                start=11,
                rss_kib=1024,
                pss_kib=750,
            )
            second = collector.sample(pss_roots=(100,))
            self.assertAlmostEqual(second.pane(100).cpu_cores, 0.75)
            self.assertAlmostEqual(second.system.cpu_percent or 0.0, 20.0)
            self.assertEqual(second.system.per_cpu_percent, (20.0, 20.0))
            self.assertEqual(second.interval_ns, 2_000_000_000)
            self.assertEqual(second.pane(200).process_count, 1)

    def test_pid_reuse_does_not_inherit_cpu_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            linux_tree(root)
            clock = [1_000_000_000]
            collector = LinuxCollector(root, monotonic_ns=lambda: clock[0])
            collector._ticks_per_second = 100
            collector.sample()
            clock[0] += 1_000_000_000
            process(
                root, 101, "replacement", ppid=100, ticks=10000, start=999, rss_kib=100
            )
            sample = collector.sample()
            replacement = next(item for item in sample.processes if item.pid == 101)
            self.assertEqual(replacement.cpu_cores, 0.0)

    def test_cached_process_table_keeps_the_full_cpu_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            linux_tree(root)
            clock = [1_000_000_000]
            collector = LinuxCollector(
                root,
                monotonic_ns=lambda: clock[0],
                process_interval=2.0,
            )
            collector._ticks_per_second = 100
            collector.sample()

            clock[0] += 1_000_000_000
            process(root, 101, "worker", ppid=100, ticks=150, start=11, rss_kib=1024)
            cached = collector.sample()
            self.assertEqual(cached.pane(100).cpu_cores, 0.0)

            clock[0] += 1_000_000_000
            process(root, 101, "worker", ppid=100, ticks=250, start=11, rss_kib=1024)
            refreshed = collector.sample()
            # 200 ticks over the two seconds since the preceding process scan.
            self.assertAlmostEqual(refreshed.pane(100).cpu_cores, 1.0)


if __name__ == "__main__":
    unittest.main()
