from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from kilix_telemetry.registry import PaneRegistry
from kilix_telemetry.ring import resolve_paths


class RegistryTests(unittest.TestCase):
    def test_multiple_owners_share_a_bounded_private_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = resolve_paths(Path(temporary) / "runtime")
            registry = PaneRegistry(paths)
            registry.update(100, [20, 10, 20, -1])
            registry.update(200, (30,))
            self.assertEqual(registry.roots(), (10, 20, 30))
            self.assertEqual(stat.S_IMODE(paths.panes.stat().st_mode), 0o600)
            self.assertEqual(paths.panes.stat().st_uid, os.getuid())


if __name__ == "__main__":
    unittest.main()
