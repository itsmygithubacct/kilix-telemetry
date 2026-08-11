# kilix-telemetry

`kilix-telemetry` is the one live Linux metrics source for Kilix chrome,
dashboards, desktops, and future policy consumers. One per-user sampler reads
`/proc` and `/sys`; every client reads versioned snapshots from a private mmap
ring instead of independently walking the process table and hardware sensors.

The component is deliberately separate from `kilix-state`. `kilix-state` owns
durable, crash-safe application records. Telemetry is transient, newest-wins,
and invalid as soon as its monotonic timestamp becomes stale.

## Data model

Each schema-1 snapshot contains:

- global CPU utilization and 1/5/15-minute system load;
- logical CPU count, uptime, RAM, swap, Linux CPU/memory/I/O PSI, and the VM
  counters used by Kilix Memory;
- thermal-zone and hwmon temperatures with stable keys and available warning
  and critical hints;
- one process table with PID, parent PID, start ticks, CPU ticks, CPU use in
  logical cores, RSS, optional `smaps_rollup` PSS, identity, state, threads,
  bounded argv, and the memory fields used by the process dashboard.

`Snapshot.pane(root_pid)` follows the shared parent table and aggregates that
root plus its descendants. Its CPU result is in **cores**, not system load:
`1.0` means the pane's processes consumed one complete logical CPU during the
last interval. The retained start tick protects comparisons from PID reuse.
Pane proportional memory sums PSS where the current user can read it and falls
back to RSS for unavailable processes. Chrome instances publish their live root
PIDs to a bounded, locked registry, so the sampler opens `smaps_rollup` only for
registered pane descendants—not every process on the machine.

## Ring and lifecycle

The daemon creates `telemetry-v1.ring` under
`$KILIX_TELEMETRY_RUNTIME`, `$XDG_RUNTIME_DIR/kilix/telemetry`, or a private
per-UID `/tmp` fallback. The directory is mode 0700 and the mmap file and
singleton lock are mode 0600; symlinked or foreign-owned endpoints are refused.

The ring is bounded (32 × 512 KiB by default), zlib-compresses JSON records,
and carries CRC, sequence, schema, wall-clock, monotonic, and writer heartbeat
metadata. One writer holds an exclusive singleton lock. Readers take a short
shared file lock while copying a slot, validate both sequence fields and CRC,
and reject stale data. A dead daemon therefore produces a direct-reader
fallback, never a frozen green status indicator.

## Commands

```sh
uv sync --frozen
uv run kilix-telemetry serve       # foreground sampler
uv run kilix-telemetry status
uv run kilix-telemetry snapshot --no-processes
uv run kilix-telemetry pane "$KITTY_PID"
uv run kilix-telemetry history --limit 10 --no-processes
uv run python -m unittest discover -s tests -v
uv build
```

Ordinary clients call `TelemetryClient.snapshot()` or `.pane(pid)`. The client
starts the sampler lazily when needed and falls back to an in-process
`LinuxCollector` if startup, the runtime directory, or the ring is unavailable.
Set `KILIX_TELEMETRY_DISABLE=1` to exercise the fallback explicitly.

Runtime dependencies: Python 3.11+ and Linux procfs/sysfs. The project is
managed and locked with `uv`; it has no third-party runtime packages.
