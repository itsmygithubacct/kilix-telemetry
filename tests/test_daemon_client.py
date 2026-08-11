from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import linux_tree

from kilix_telemetry.client import TelemetryClient, ensure_running
from kilix_telemetry.daemon import run_daemon
from kilix_telemetry.ring import resolve_paths


class DaemonClientTests(unittest.TestCase):
    def test_foreground_once_publishes_for_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            self.assertEqual(
                run_daemon(
                    paths=paths,
                    root=root,
                    once=True,
                    slot_count=2,
                    slot_size=64 * 1024,
                ),
                0,
            )
            sample = TelemetryClient(paths).snapshot(
                start=False, fallback=False, force=True
            )
            self.assertIsNotNone(sample)
            self.assertEqual(sample.system.memory_total, 8192 * 1024)

    def test_disabled_start_uses_direct_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            with mock.patch.dict(
                "os.environ", {"KILIX_TELEMETRY_DISABLE": "1"}, clear=False
            ):
                self.assertFalse(ensure_running(paths, timeout=0))
                sample = TelemetryClient(paths, fallback_root=root).snapshot(force=True)
            self.assertIsNotNone(sample)
            self.assertEqual(len(sample.processes), 3)


if __name__ == "__main__":
    unittest.main()
