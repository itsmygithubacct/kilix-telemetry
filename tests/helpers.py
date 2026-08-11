from __future__ import annotations

import os
from pathlib import Path


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def process_stat(
    pid: int,
    name: str,
    *,
    ppid: int,
    ticks: int,
    child_ticks: int,
    start: int,
    rss_pages: int,
) -> str:
    fields = ["0"] * 50
    fields[0] = "S"
    fields[1] = str(ppid)
    fields[11] = str(ticks)
    fields[12] = "0"
    fields[13] = str(child_ticks)
    fields[17] = "1"
    fields[19] = str(start)
    fields[20] = str(rss_pages * 4096 * 4)
    fields[21] = str(rss_pages)
    return f"{pid} ({name}) " + " ".join(fields) + "\n"


def process(
    root: Path,
    pid: int,
    name: str,
    *,
    ppid: int,
    ticks: int,
    child_ticks: int = 0,
    start: int,
    rss_kib: int,
    pss_kib: int | None = None,
) -> None:
    pages = max(1, rss_kib * 1024 // 4096)
    write(
        root,
        f"proc/{pid}/stat",
        process_stat(
            pid,
            name,
            ppid=ppid,
            ticks=ticks,
            child_ticks=child_ticks,
            start=start,
            rss_pages=pages,
        ),
    )
    write(
        root,
        f"proc/{pid}/status",
        (
            f"Name:\t{name}\nState:\tS (sleeping)\nPPid:\t{ppid}\n"
            f"Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\nThreads:\t1\n"
            f"VmRSS:\t{rss_kib} kB\nVmSize:\t{rss_kib * 3} kB\n"
            f"RssAnon:\t{rss_kib // 2} kB\n"
            f"RssFile:\t{rss_kib // 3} kB\nRssShmem:\t0 kB\n"
        ),
    )
    path = root / f"proc/{pid}/cmdline"
    path.write_bytes(f"{name}\0--demo\0".encode())
    if pss_kib is not None:
        write(root, f"proc/{pid}/smaps_rollup", f"Pss: {pss_kib} kB\n")


def linux_tree(root: Path) -> None:
    write(root, "proc/sys/kernel/random/boot_id", "boot-demo\n")
    write(
        root,
        "proc/stat",
        (
            "cpu  100 0 50 850 0 0 0 0 0 0\n"
            "cpu0 50 0 25 425 0 0 0 0 0 0\n"
            "cpu1 50 0 25 425 0 0 0 0 0 0\n"
        ),
    )
    write(root, "proc/loadavg", "1.25 0.75 0.50 1/100 42\n")
    write(
        root,
        "proc/cpuinfo",
        "processor : 0\ncpu MHz : 2400.0\n\nprocessor : 1\ncpu MHz : 2500.0\n",
    )
    write(root, "proc/uptime", "100.0 50.0\n")
    write(
        root,
        "proc/meminfo",
        (
            "MemTotal: 8192 kB\nMemAvailable: 4096 kB\nMemFree: 1024 kB\n"
            "Buffers: 256 kB\nCached: 2048 kB\nSReclaimable: 128 kB\n"
            "Shmem: 64 kB\nActive: 2048 kB\nInactive: 1024 kB\n"
            "AnonPages: 3072 kB\nSlab: 256 kB\nPageTables: 32 kB\n"
            "KernelStack: 16 kB\nDirty: 8 kB\nWriteback: 4 kB\n"
            "SwapTotal: 2048 kB\nSwapFree: 1024 kB\n"
            "HugePages_Total: 8\nHugePages_Free: 3\nHugepagesize: 2048 kB\n"
        ),
    )
    write(
        root, "proc/pressure/cpu", "some avg10=1.00 avg60=0.50 avg300=0.10 total=12\n"
    )
    write(
        root,
        "proc/pressure/memory",
        (
            "some avg10=2.00 avg60=1.00 avg300=0.20 total=20\n"
            "full avg10=0.10 avg60=0.05 avg300=0.01 total=2\n"
        ),
    )
    write(root, "proc/pressure/io", "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
    write(
        root,
        "proc/vmstat",
        "pgfault 100\npgmajfault 3\npswpin 4\npswpout 5\noom_kill 0\n",
    )
    write(root, "sys/class/thermal/thermal_zone0/type", "x86_pkg_temp\n")
    write(root, "sys/class/thermal/thermal_zone0/temp", "72000\n")
    write(root, "sys/class/thermal/thermal_zone0/trip_point_0_type", "critical\n")
    write(root, "sys/class/thermal/thermal_zone0/trip_point_0_temp", "100000\n")
    write(root, "sys/class/hwmon/hwmon2/name", "nvme\n")
    write(root, "sys/class/hwmon/hwmon2/temp1_label", "Composite\n")
    write(root, "sys/class/hwmon/hwmon2/temp1_input", "51000\n")
    write(root, "sys/class/hwmon/hwmon2/fan1_label", "Controller\n")
    write(root, "sys/class/hwmon/hwmon2/fan1_input", "3210\n")
    process(root, 100, "shell", ppid=1, ticks=100, start=10, rss_kib=2048, pss_kib=1500)
    process(
        root, 101, "worker", ppid=100, ticks=50, start=11, rss_kib=1024, pss_kib=700
    )
    process(root, 200, "other", ppid=1, ticks=10, start=12, rss_kib=512, pss_kib=400)
