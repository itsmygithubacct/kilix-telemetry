"""Bounded process identities for automatically started sampler lifetimes."""

from __future__ import annotations

import fcntl
import json
import os
import sys
from pathlib import Path

from .ring import TelemetryError, TelemetryPaths, _ensure_private_directory, _secure_open

MAX_CONSUMERS = 1024
MAX_BYTES = 256 * 1024


_libc = None


def _freebsd_libc():
    """The running image's libc; dlopen(NULL) needs no ldconfig(8) lookup."""
    global _libc
    if _libc is None:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                ctypes.c_void_p, ctypes.c_size_t]
        libc.sysctl.restype = ctypes.c_int
        _libc = libc
    return _libc


def _freebsd_identity(pid: int) -> str | None:
    """kern.proc.pid.PID and kern.boottime: owner, state, start and boot.

    FreeBSD has no pid namespaces (jails share one pid space), so the boot
    time and the process start time name one incarnation of PID.
    """
    import ctypes
    import struct

    libc = _freebsd_libc()

    def read(mib: list[int], size: int) -> bytes | None:
        array = (ctypes.c_int * len(mib))(*mib)
        buffer = ctypes.create_string_buffer(size)
        length = ctypes.c_size_t(size)
        if libc.sysctl(array, len(mib), buffer, ctypes.byref(length), None, 0) != 0:
            return None
        return buffer.raw[: length.value]

    # struct kinfo_proc on LP64 FreeBSD (amd64, arm64): 1088 bytes, ki_pid at
    # 72, ki_ruid at 172, ki_start (timeval) at 336, ki_stat at 388. Trust
    # nothing unless ki_structsize and ki_pid match.
    raw = read([1, 14, 1, pid], 1088)  # CTL_KERN, KERN_PROC, KERN_PROC_PID
    if not raw or len(raw) < 1088:
        return None
    if struct.unpack_from("i", raw, 0)[0] != 1088 or struct.unpack_from("i", raw, 72)[0] != pid:
        return None
    if struct.unpack_from("I", raw, 172)[0] != os.getuid() or raw[388] == 5:  # SZOMB
        return None
    start_seconds, start_micros = struct.unpack_from("qq", raw, 336)
    boot = read([1, 21], 16)  # CTL_KERN, KERN_BOOTTIME
    if not boot or len(boot) < 16:
        return None
    boot_seconds, boot_micros = struct.unpack_from("qq", boot, 0)
    return f"{boot_seconds}.{boot_micros}:{start_seconds}.{start_micros}"


def process_identity(pid: int) -> str | None:
    """Distinguish dead processes, zombies, rebooted hosts and reused PIDs."""
    if pid <= 0:
        return None
    if sys.platform.startswith("freebsd"):
        return _freebsd_identity(pid)
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
