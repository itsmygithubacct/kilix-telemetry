from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import linux_tree

from kilix_telemetry.cli import main
from kilix_telemetry.ring import DaemonLock, resolve_paths


class CliTests(unittest.TestCase):
    def test_runtime_is_accepted_after_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "linux"
            runtime = base / "runtime"
            root.mkdir()
            linux_tree(root)
            self.assertEqual(
                main(
                    [
                        "serve",
                        "--runtime",
                        str(runtime),
                        "--root",
                        str(root),
                        "--once",
                        "--quiet",
                    ]
                ),
                0,
            )
            self.assertEqual(main(["status", "--runtime", str(runtime)]), 1)
            with DaemonLock(resolve_paths(runtime)):
                self.assertEqual(main(["status", "--runtime", str(runtime)]), 0)


if __name__ == "__main__":
    unittest.main()
