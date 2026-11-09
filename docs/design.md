# Data model, ring and lifecycle

What a schema-1 snapshot holds, how pane aggregates are computed, the ring
format, and how the sampler starts and stops with its consumers.

## Data model

Each schema-1 snapshot contains:

- global and per-logical-CPU utilization, current CPU frequency, and
  1/5/15-minute system load;
- logical CPU count, uptime, RAM, swap, Linux CPU/memory/I/O PSI, and the VM
  counters used by Kilix Memory;
- thermal-zone and hwmon temperatures with stable keys and available warning
  and critical hints, plus hwmon fan tachometers;
- one process table with PID, parent PID, start ticks, CPU ticks, CPU use in
  logical cores, RSS, optional `smaps_rollup` PSS, identity, state, threads,
  bounded argv, and the memory fields used by the process dashboard. The
  `processes_total` and `processes_truncated` fields make any ring compaction
  explicit to process-list consumers.

`Snapshot.pane(root_pid)` follows the shared parent table and aggregates that
root plus its descendants. Its CPU result is in **cores**, not system load:
`1.0` means the pane's processes consumed one complete logical CPU during the
last interval. Linux's waited-child counters retain CPU used by short commands
which start and exit between process-table scans; a cumulative tree counter
accounts for that work without counting it again when a live child is reaped.
The retained start tick protects comparisons from PID reuse.
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
and reject stale data. Status and lazy startup inspect the live singleton lock,
not merely the age of the last record, so a dead daemon cannot leave a false
running result. If a process table would exceed a ring slot, argv is bounded
further and lower-priority process detail is trimmed while global and pane
aggregates remain intact; an irreducible record is skipped without terminating
the long-running sampler.

Automatic startup registers each consuming process under the private runtime
with its boot ID, PID namespace, PID and process start tick. The sampler exits
after five seconds without a matching live consumer. Closing one window keeps
it running for other consumers; a crashed or failed launcher does not leave an
unowned sampler. The bounded registry drops dead identities on new registrations.
A client lease lasts for the process, so closing one of several client objects
cannot revoke another object's use. Forked clients register the child's identity
on its first automatic snapshot request.

`serve` remains persistent by default for explicit service management. Pass
`--idle-timeout SECONDS` to use consumer lifetime management. Configured
`KILIX_TELEMETRY_COMMAND` overrides retain their selected lifecycle policy.
`start --owner-pid PID` registers a launcher before starting the automatic
sampler; ordinary Python clients register themselves. A timed out command that
never acquired the writer lock is terminated and reaped as an owned child.
