# kilix-telemetry

`kilix-telemetry` is the one live Linux metrics source for Kilix chrome,
dashboards, desktops, and future policy consumers. One per-user sampler reads
`/proc` and `/sys`; every client reads versioned snapshots from a private mmap
ring instead of independently walking the process table and hardware sensors.

The component is deliberately separate from `kilix-state`. `kilix-state` owns
durable, crash-safe application records. Telemetry is transient, newest-wins,
and invalid as soon as its monotonic timestamp becomes stale.
Ships in Plebian-OS 0.2.3 as a submodule of
[Kilix](https://github.com/itsmygithubacct/kilix#readme)
(`third_party/kilix-telemetry`). Kilix's pane title-bar CPU and memory chips,
the System Center CPU, Memory and Temperatures apps, and `kilix telemetry`
read from it; desktop providers reach it as `kilix_sdk.telemetry`.

## What it does

- Samples CPU (global, per logical CPU, frequency, load), memory, swap, PSI,
  temperatures, fans and the process table from `/proc` and `/sys`, once per
  user.
- Publishes zlib-compressed JSON snapshots to a bounded, CRC-checked mmap ring
  that any number of clients read without walking `/proc` themselves.
- Aggregates a pane's process tree (`Snapshot.pane(root_pid)`): CPU in cores,
  proportional memory from `smaps_rollup` where readable.
- Starts lazily for its consumers and exits five seconds after the last one
  goes; `serve` stays up for explicit service management.
- Falls back to an in-process collector when the ring cannot be used.

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
The schema-1 component is first consumed by the Kilix 0.1.9 release.

## Command reference

| Command | What it does |
|---|---|
| `kilix-telemetry serve [--interval S] [--idle-timeout S] [--once]` | Run the single sampler in the foreground |
| `kilix-telemetry start --owner-pid PID` | Start an automatic sampler owned by a live process |
| `kilix-telemetry status` | Report daemon and ring health |
| `kilix-telemetry snapshot [--no-processes] [--direct] [--no-start]` | Print the newest sample |
| `kilix-telemetry pane PID` | Print one process-tree aggregate |
| `kilix-telemetry history [--limit N] [--no-processes]` | Print recent ring samples |
| `kilix-telemetry --runtime DIR ...` | Use another private runtime directory |

| Environment | Effect |
|---|---|
| `KILIX_TELEMETRY_RUNTIME` | Runtime directory (default `$XDG_RUNTIME_DIR/kilix/telemetry`) |
| `KILIX_TELEMETRY_DISABLE=1` | Skip the ring and use the in-process collector |
| `KILIX_TELEMETRY_COMMAND` | Override the command that starts the sampler |
| `KILIX_TELEMETRY_INTERVAL`, `KILIX_TELEMETRY_PSS_INTERVAL` | Default sampling interval and `smaps_rollup` interval for `serve`, in seconds |

In Kilix the same commands are `kilix telemetry status`, `snapshot`,
`pane PID` and `history`.

## How it works

```
 /proc, /sys ──> sampler (one per user, singleton lock) ──> telemetry-v1.ring
                         │                                   32 slots × 512 KiB
                         │  registered consumers (boot id,    zlib JSON + CRC,
                         │  pid namespace, pid, start tick)   sequence, heartbeat
                         ▼                                          │
                 exits 5 s after the last live consumer             ▼
                                         TelemetryClient.snapshot() / .pane(pid)
                                         (falls back to LinuxCollector)
```

One writer holds an exclusive lock on the ring; readers copy a slot under a
short shared lock, check both sequence fields and the CRC, and refuse stale
data. A process table too large for a slot is trimmed rather than stopping the
sampler. Consumers register their identity, so a reused PID cannot keep a
sampler alive. Details: [docs/design.md](docs/design.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/design.md](docs/design.md) | Snapshot data model, pane aggregation, ring format, consumer lifecycle |

## Related repositories

- [kilix](https://github.com/itsmygithubacct/kilix#readme): pins this
  component for its chrome, System Center apps and `kilix telemetry`.
- [kilix-tui-utils](https://github.com/itsmygithubacct/kilix-tui-utils#readme):
  system monitors that read Kilix telemetry.
- [kilix-state](https://github.com/itsmygithubacct/kilix-state#readme):
  durable records, which this transient source deliberately is not.

## Part of Plebian-OS

kilix-telemetry is one of the repositories behind
[Plebian-OS](https://github.com/itsmygithubacct/plebian-os#readme), a Debian
install whose desktop is [Kilix](https://github.com/itsmygithubacct/kilix#readme)
running the [Kilix 95](https://github.com/itsmygithubacct/kilix-95#readme)
desktop through [Pleb](https://github.com/itsmygithubacct/pleb#readme).
It ships inside Kilix as the `third_party/kilix-telemetry` submodule and feeds
every CPU, memory and temperature reading the desktop shows. The map of every
repository and how it ships is on the
[components page](https://github.com/itsmygithubacct/plebian-os/blob/main/docs/components.md).

## License

MIT. See [LICENSE](LICENSE).
