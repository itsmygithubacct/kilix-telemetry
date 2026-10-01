"""Bounded process identities for automatically started sampler lifetimes."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from .ring import TelemetryError, TelemetryPaths, _ensure_private_directory, _secure_open

MAX_CONSUMERS = 1024
MAX_BYTES = 256 * 1024


def process_identity(pid: int) -> str | None:
    """Distinguish dead processes, zombies, rebooted hosts and reused PIDs."""
    if pid <= 0:
        return None
    try:
        directory = Path(f"/proc/{pid}")
        if directory.stat().st_uid != os.getuid():
            return None
        namespace = (directory / "ns/pid").stat()
        fields = (directory / "stat").read_text().rsplit(") ", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{namespace.st_dev}:{namespace.st_ino}:{fields[19]}"
    except (OSError, IndexError):
        return None


class ConsumerRegistry:
    def __init__(self, paths: TelemetryPaths) -> None:
        self.paths = paths
        self.file = paths.directory / "consumers-v1.json"

    def _live(self, raw: bytes) -> dict[str, str]:
        if len(raw) > MAX_BYTES:
            return {}
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {}
        if not isinstance(value, dict) or len(value) > MAX_CONSUMERS:
            return {}
        live = {}
        for pid, identity in value.items():
            try:
                numeric = int(pid)
            except (ValueError, TypeError):
                continue
            if isinstance(identity, str) and process_identity(numeric) == identity:
                live[pid] = identity
        return live

    def register(self, pid: int) -> None:
        identity = process_identity(pid)
        if identity is None:
            raise ValueError("telemetry owner is not a live process")
        _ensure_private_directory(self.paths.directory)
        fd = _secure_open(self.file, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            live = self._live(os.read(fd, MAX_BYTES + 1))
            if str(pid) not in live and len(live) >= MAX_CONSUMERS:
                raise TelemetryError("too many telemetry consumers")
            live[str(pid)] = identity
            encoded = json.dumps(live, sort_keys=True, separators=(",", ":")).encode()
            os.lseek(fd, 0, os.SEEK_SET)
            pending = memoryview(encoded)
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise OSError("short telemetry consumer registry write")
                pending = pending[written:]
            os.ftruncate(fd, len(encoded))
        finally:
            os.close(fd)

    def active(self) -> bool:
        try:
            fd = _secure_open(self.file, os.O_RDONLY)
        except FileNotFoundError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            return bool(self._live(os.read(fd, MAX_BYTES + 1)))
        finally:
            os.close(fd)
