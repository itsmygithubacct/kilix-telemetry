from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from helpers import linux_tree

from kilix_telemetry.collect import LinuxCollector
from kilix_telemetry.ring import (
    RingReader,
    RingWriter,
    TelemetryError,
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


if __name__ == "__main__":
    unittest.main()
