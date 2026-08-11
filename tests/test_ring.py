from __future__ import annotations

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
