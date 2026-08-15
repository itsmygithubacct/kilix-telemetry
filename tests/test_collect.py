from __future__ import annotations

import shutil
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

    def test_sensor_values_refresh_through_the_cached_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            linux_tree(root)
            clock = [1_000_000_000]
            collector = LinuxCollector(root, monotonic_ns=lambda: clock[0])
            first = collector.sample()
            self.assertEqual(first.hottest_celsius, 72.0)
            self.assertEqual(first.fans[0].rpm, 3210)

            write(root, "sys/class/thermal/thermal_zone0/temp", "80000\n")
            write(root, "sys/class/hwmon/hwmon2/fan1_input", "2500\n")
            clock[0] += 2_000_000_000
            second = collector.sample()
            self.assertEqual(second.hottest_celsius, 80.0)
            self.assertEqual(second.fans[0].rpm, 2500)

            # A newly appearing sensor waits for the slow topology rescan.
            write(root, "sys/class/hwmon/hwmon2/temp2_input", "44000\n")
            clock[0] += 2_000_000_000
            third = collector.sample()
            self.assertNotIn(
                "hwmon:hwmon2:nvme:temp2",
                [sensor.key for sensor in third.thermal],
            )
            clock[0] += 60_000_000_000
            fourth = collector.sample()
            self.assertIn(
                "hwmon:hwmon2:nvme:temp2",
                [sensor.key for sensor in fourth.thermal],
            )

    def test_removed_sensor_disappears_and_forces_a_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            linux_tree(root)
            clock = [1_000_000_000]
            collector = LinuxCollector(root, monotonic_ns=lambda: clock[0])
            collector.sample()

            (root / "sys/class/hwmon/hwmon2/temp1_input").unlink()
            clock[0] += 2_000_000_000
            gone = collector.sample()
            self.assertNotIn(
                "hwmon:hwmon2:nvme:temp1",
                [sensor.key for sensor in gone.thermal],
            )

            # The vanished input forces an early topology refresh, so a
            # sensor added now appears well before the slow rescan cadence.
            write(root, "sys/class/hwmon/hwmon2/temp3_input", "40000\n")
            clock[0] += 2_000_000_000
            refreshed = collector.sample()
            self.assertIn(
                "hwmon:hwmon2:nvme:temp3",
                [sensor.key for sensor in refreshed.thermal],
            )

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

    def test_pane_cpu_includes_children_that_exit_between_scans(self) -> None:
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
            collector.sample(pss_roots=(100,))

            clock[0] += 2_000_000_000
            process(
                root,
                100,
                "shell",
                ppid=1,
                ticks=100,
                child_ticks=80,
                start=10,
                rss_kib=2048,
                pss_kib=1500,
            )
            sample = collector.sample(pss_roots=(100,))

            # The 80 ticks belong to a child which was never present in either
            # process-table scan, but the shell's waited-child counter retains it.
            self.assertAlmostEqual(sample.pane(100).cpu_cores, 0.4)

    def test_reaped_child_cpu_is_not_counted_twice(self) -> None:
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
            collector.sample(pss_roots=(100,))

            clock[0] += 2_000_000_000
            process(
                root,
                101,
                "worker",
                ppid=100,
                ticks=100,
                start=11,
                rss_kib=1024,
            )
            live = collector.sample(pss_roots=(100,))
            self.assertAlmostEqual(live.pane(100).cpu_cores, 0.25)

            clock[0] += 2_000_000_000
            shutil.rmtree(root / "proc" / "101")
            process(
                root,
                100,
                "shell",
                ppid=1,
                ticks=100,
                child_ticks=120,
                start=10,
                rss_kib=2048,
                pss_kib=1500,
            )
            reaped = collector.sample(pss_roots=(100,))

            # The first 100 child ticks were already present in the live tree;
            # only the final 20 ticks are new when they move to shell cutime.
            self.assertAlmostEqual(reaped.pane(100).cpu_cores, 0.1)


if __name__ == "__main__":
    unittest.main()
