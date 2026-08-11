"""Stable client API with shared-ring reads and a direct-reader fallback."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from .collect import LinuxCollector
from .model import PaneMetrics, Snapshot
from .registry import PaneRegistry
from .ring import (
    RingReader,
    RingUnavailable,
    TelemetryError,
    TelemetryPaths,
    daemon_running,
    resolve_paths,
)

_TRUTHY = {"1", "true", "yes", "on"}


def _disabled() -> bool:
    return os.environ.get("KILIX_TELEMETRY_DISABLE", "").strip().lower() in _TRUTHY


def _daemon_command() -> list[str]:
    configured = os.environ.get("KILIX_TELEMETRY_COMMAND", "").strip()
    if configured:
        return shlex.split(configured)
    return [sys.executable, "-m", "kilix_telemetry", "serve", "--quiet"]


def _spawn_environment(paths: TelemetryPaths) -> dict[str, str]:
    environment = dict(os.environ)
    package_root = str(Path(__file__).resolve().parents[1])
    current = environment.get("PYTHONPATH", "")
    entries = [entry for entry in current.split(os.pathsep) if entry]
    if package_root not in entries:
        environment["PYTHONPATH"] = os.pathsep.join([package_root, *entries])
    environment["KILIX_TELEMETRY_RUNTIME"] = str(paths.directory)
    return environment


def _ring_snapshot(paths: TelemetryPaths, max_age: float) -> Snapshot | None:
    try:
        with RingReader(paths) as reader:
            return reader.latest(max_age=max_age)
    except (OSError, RingUnavailable):
        return None


def _writer_active(paths: TelemetryPaths) -> bool:
    try:
        return daemon_running(paths)
    except (OSError, TelemetryError):
        return False


def ensure_running(
    paths: TelemetryPaths | None = None,
    *,
    timeout: float = 2.5,
) -> bool:
    """Ensure a fresh writer exists without making consumers depend on it."""
    if _disabled():
        return False
    paths = paths or resolve_paths()
    if _writer_active(paths):
        return True
    command = _daemon_command()
    if not command:
        return False
    debug = os.environ.get("KILIX_TELEMETRY_DEBUG", "").lower() in _TRUTHY
    destination = None if debug else subprocess.DEVNULL
    started_ns = time.monotonic_ns()
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=destination,
            stderr=destination,
            close_fds=True,
            start_new_session=True,
            env=_spawn_environment(paths),
        )
    except OSError:
        return False
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        sample = _ring_snapshot(paths, 3.0)
        if (
            _writer_active(paths)
            and sample is not None
            and sample.monotonic_ns >= started_ns
        ):
            return True
        time.sleep(0.05)
    return _writer_active(paths)


class TelemetryClient:
    def __init__(
        self,
        paths: TelemetryPaths | None = None,
        *,
        max_age: float = 5.0,
        cache_seconds: float = 0.2,
        fallback_root: str | Path = "/",
    ) -> None:
        self.paths = paths or resolve_paths()
        self.max_age = max(0.1, float(max_age))
        self.cache_seconds = max(0.0, float(cache_seconds))
        self._fallback = LinuxCollector(fallback_root)
        self._cached: Snapshot | None = None
        self._cached_until = 0.0
        self._lock = threading.Lock()

    def snapshot(
        self,
        *,
        start: bool = True,
        fallback: bool = True,
        force: bool = False,
    ) -> Snapshot | None:
        now = time.monotonic()
        if not force and self._cached is not None and now < self._cached_until:
            return self._cached
        with self._lock:
            now = time.monotonic()
            if not force and self._cached is not None and now < self._cached_until:
                return self._cached
            snapshot = _ring_snapshot(self.paths, self.max_age)
            if start and not _writer_active(self.paths):
                if ensure_running(self.paths):
                    refreshed = _ring_snapshot(self.paths, self.max_age)
                    if refreshed is not None:
                        snapshot = refreshed
            if snapshot is None and fallback:
                snapshot = self._fallback.sample()
            self._cached = snapshot
            self._cached_until = now + self.cache_seconds
            return snapshot

    def pane(
        self,
        root_pid: int,
        *,
        start: bool = True,
        fallback: bool = True,
        force: bool = False,
    ) -> PaneMetrics:
        self.register_panes((root_pid,))
        snapshot = self.snapshot(start=start, fallback=False, force=force)
        if snapshot is None and fallback:
            snapshot = self._fallback.sample(pss_roots=(int(root_pid),))
        if snapshot is None:
            return PaneMetrics(max(0, int(root_pid)), 0, 0.0, 0, 0, False)
        return snapshot.pane(root_pid)

    def register_panes(self, roots: tuple[int, ...] | list[int]) -> bool:
        if _disabled():
            return False
        try:
            PaneRegistry(self.paths).update(os.getpid(), tuple(roots))
        except (OSError, ValueError):
            return False
        return True

    def history(
        self,
        limit: int | None = None,
        *,
        max_age: float | None = None,
    ) -> tuple[Snapshot, ...]:
        try:
            with RingReader(self.paths) as reader:
                return reader.history(limit, max_age=max_age)
        except (OSError, RingUnavailable):
            return ()


_DEFAULT_CLIENT: TelemetryClient | None = None
_DEFAULT_LOCK = threading.Lock()


def default_client() -> TelemetryClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_CLIENT is None:
                _DEFAULT_CLIENT = TelemetryClient()
    return _DEFAULT_CLIENT
