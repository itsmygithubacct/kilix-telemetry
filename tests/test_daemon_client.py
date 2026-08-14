from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import linux_tree

from kilix_telemetry.client import TelemetryClient, ensure_running
from kilix_telemetry.daemon import run_daemon
from kilix_telemetry.registry import PaneRegistry
from kilix_telemetry.ring import TelemetryError, resolve_paths


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

    def test_fresh_record_from_exited_writer_does_not_suppress_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            self.assertEqual(run_daemon(paths=paths, root=root, once=True), 0)

            with mock.patch("kilix_telemetry.client.subprocess.Popen") as spawn:
                self.assertFalse(ensure_running(paths, timeout=0))
            spawn.assert_called_once()

    def test_pane_polls_accumulate_registered_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            client = TelemetryClient(paths, fallback_root=root)
            client.pane(100, start=False)
            client.pane(200, start=False, force=True)
            self.assertEqual(PaneRegistry(paths).roots(), (100, 200))

    def test_unchanged_pane_set_throttles_registry_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            client = TelemetryClient(paths, fallback_root=root)
            real_update = PaneRegistry.update
            with mock.patch.object(
                PaneRegistry, "update", autospec=True, side_effect=real_update
            ) as update:
                client.pane(100, start=False)
                client.pane(100, start=False, force=True)
                client.pane(100, start=False, force=True)
            self.assertEqual(update.call_count, 1)
            self.assertEqual(PaneRegistry(paths).roots(), (100,))

    def test_stale_pane_roots_age_out_of_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            client = TelemetryClient(paths, fallback_root=root)
            clock = [100.0]
            with mock.patch(
                "kilix_telemetry.client.time.monotonic", side_effect=lambda: clock[0]
            ):
                client.pane(100, start=False)
                clock[0] += 20.0
                client.pane(200, start=False, force=True)
            self.assertEqual(PaneRegistry(paths).roots(), (200,))

    def test_daemon_handles_an_unpublishable_once_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            root.mkdir()
            linux_tree(root)
            paths = resolve_paths(base / "runtime")
            with mock.patch("kilix_telemetry.daemon.RingWriter") as writer_class:
                writer = writer_class.return_value.__enter__.return_value
                writer.publish.side_effect = TelemetryError("too large")
                result = run_daemon(paths=paths, root=root, once=True)
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
