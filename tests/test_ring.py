from __future__ import annotations

import os
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from helpers import linux_tree

from kilix_telemetry.collect import LinuxCollector
from kilix_telemetry.ring import (
    DaemonLock,
    RingReader,
    RingWriter,
    TelemetryError,
    daemon_running,
    resolve_paths,
)


class RingTests(unittest.TestCase):
    def test_bounded_round_trip_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "linux"
            runtime = Path(temporary) / "runtime"
            root.mkdir()
            linux_tree(root)
            base = LinuxCollector(root).sample()
            paths = resolve_paths(runtime)
            with RingWriter(paths, slot_count=3, slot_size=64 * 1024) as writer:
                for sequence in range(1, 6):
                    writer.publish(
                        replace(
                            base,
                            sequence=sequence,
                            monotonic_ns=base.monotonic_ns + sequence,
                            wall_time_ns=base.wall_time_ns + sequence,
                        )
                    )
                with RingReader(paths) as reader:
                    latest = reader.latest(max_age=None)
                    self.assertIsNotNone(latest)
                    self.assertEqual(latest.sequence, 5)
                    self.assertEqual(
                        [sample.sequence for sample in reader.history()],
                        [3, 4, 5],
                    )

    def test_geometry_change_swaps_the_ring_file_under_live_readers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "linux"
            runtime = Path(temporary) / "runtime"
            root.mkdir()
            linux_tree(root)
            base = LinuxCollector(root).sample()
            paths = resolve_paths(runtime)
            with RingWriter(paths, slot_count=4, slot_size=128 * 1024) as writer:
                writer.publish(base)
            reader = RingReader(paths)
            try:
                old_size = reader.size
                with RingWriter(paths, slot_count=2, slot_size=64 * 1024):
                    # The reader's inode is untouched: its complete mapping
                    # stays readable and still holds the published record.
                    self.assertEqual(
                        len(reader.mapping[old_size - 4096 : old_size]), 4096
                    )
                    latest = reader.latest(max_age=None)
                    self.assertIsNotNone(latest)
                    self.assertEqual(latest.sequence, base.sequence)
                    with RingReader(paths) as fresh:
                        self.assertEqual(fresh.slot_count, 2)
                        self.assertEqual(fresh.slot_size, 64 * 1024)
            finally:
                reader.close()

    def test_unchanged_geometry_restart_keeps_the_mapped_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "linux"
            runtime = Path(temporary) / "runtime"
            root.mkdir()
            linux_tree(root)
            base = LinuxCollector(root).sample()
            paths = resolve_paths(runtime)
            with RingWriter(paths, slot_count=3, slot_size=64 * 1024) as writer:
                writer.publish(base)
            inode = os.stat(paths.ring).st_ino
            reader = RingReader(paths)
            try:
                with RingWriter(paths, slot_count=3, slot_size=64 * 1024) as writer:
                    self.assertEqual(os.stat(paths.ring).st_ino, inode)
                    self.assertIsNone(reader.latest(max_age=None))
                    writer.publish(
                        replace(
                            base,
                            sequence=base.sequence + 1,
                            monotonic_ns=base.monotonic_ns + 1,
                            wall_time_ns=base.wall_time_ns + 1,
                        )
                    )
                    refreshed = reader.latest(max_age=None)
                    self.assertIsNotNone(refreshed)
                    self.assertEqual(refreshed.sequence, base.sequence + 1)
            finally:
                reader.close()

    def test_symlinked_runtime_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "real"
            real.mkdir()
            linked = base / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises(TelemetryError):
                RingWriter(resolve_paths(linked))

    def test_writer_liveness_comes_from_the_singleton_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = resolve_paths(Path(temporary) / "runtime")
            self.assertFalse(daemon_running(paths))
            with DaemonLock(paths):
                self.assertTrue(daemon_running(paths))
            self.assertFalse(daemon_running(paths))

    def test_large_process_table_is_compacted_without_losing_pane_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "linux"
            runtime = Path(temporary) / "runtime"
            root.mkdir()
            linux_tree(root)
            base = LinuxCollector(root).sample(pss_roots=(100,))
            template = base.processes[0]
            generator = random.Random(0)
            alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            processes = tuple(
                replace(
                    template,
                    pid=1_000 + index,
                    ppid=1,
                    command="".join(generator.choices(alphabet, k=2048)),
                )
                for index in range(160)
            )
            oversized = replace(
                base,
                processes=processes,
                processes_total=len(processes),
            )
            paths = resolve_paths(runtime)
            with RingWriter(paths, slot_count=2, slot_size=64 * 1024) as writer:
                writer.publish(oversized)
                with RingReader(paths) as reader:
                    decoded = reader.latest(max_age=None)
            self.assertIsNotNone(decoded)
            self.assertTrue(decoded.processes_truncated)
            self.assertEqual(decoded.processes_total, len(processes))
            self.assertEqual(decoded.pane(100), base.pane(100))


if __name__ == "__main__":
    unittest.main()
