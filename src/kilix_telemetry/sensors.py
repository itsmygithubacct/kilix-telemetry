"""Read-only temperature and fan readings for Kilix Ask.

This is the kilix-sensors module. It lives in kilix-telemetry so Ask can
read the same sysfs files the sampler watches, and it never starts that
sampler. Thermal-zone and hwmon temperature files are millidegree Celsius;
the value is always divided by 1000.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

NOT_SENSOR = 3
_CPU_NAMES = frozenset({"coretemp", "x86_pkg_temp"})
_RESERVED = frozenset({"the", "my", "this", "a"})
_ZONE = re.compile(r"thermal_zone\d+")
_HWMON = re.compile(r"hwmon\d+")
_TEMP_FILE = re.compile(r"temp\d+_input")
_FAN_FILE = re.compile(r"fan\d+_input")
_INTEGER = re.compile(r"-?\d+")
_NATURAL = re.compile(r"(\d+)")
_PREFIX = re.compile(r"^(?:please\s+)?", re.IGNORECASE)
_TRAIL = re.compile(r"[?!.]+$")
_UNIT = re.compile(r" in (celsius|fahrenheit)$", re.IGNORECASE)
_NAME = r"[a-z0-9][a-z0-9_+.-]*(?: [a-z0-9][a-z0-9_+.-]*){0,4}"
_LEAD = r"(?:(?:show |check |what(?:'s| is) )?(?:the )?)"
_CPU = re.compile(
    r"(?:show |check )?(?:the )?cpu temp(?:erature)?"
    r"|what(?:'s| is) (?:the |my )?cpu temp(?:erature)?"
    r"|how hot is the cpu",
    re.IGNORECASE,
)
_TEMPERATURE = re.compile(
    r"(?:show |check )?(?:the )?temperature"
    r"|what(?:'s| is) the temperature"
    r"|how hot is it"
    r"|how hot is this (?:computer|machine)",
    re.IGNORECASE,
)
_FAN = re.compile(
    r"(?:show |check )?(?:the )?fan (?:speed|rpm)"
    r"|what(?:'s| is) (?:the )?fan (?:speed|rpm)",
    re.IGNORECASE,
)
_NAMED_TEMP = re.compile(
    rf"{_LEAD}(?P<name>{_NAME}) temp(?:erature)?",
    re.IGNORECASE,
)
_NAMED_FAN = re.compile(
    rf"{_LEAD}(?P<name>{_NAME}) fan (?:speed|rpm)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Temperature:
    """One current temperature after the kernel millidegree conversion."""

    chip: str
    name: str
    label: str
    celsius: float


@dataclass(frozen=True)
class Fan:
    """One current tachometer reading."""

    chip: str
    name: str
    label: str
    rpm: int


@dataclass(frozen=True)
class _Request:
    kind: str
    name: str = ""
    unit: str = ""


class SensorError(Exception):
    """A recognized reading that sysfs could not answer."""


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in _NATURAL.split(value)
    )


def _pretty_chip(name: str) -> str:
    lowered = name.lower()
    aliases = {
        "coretemp": "CPU",
        "x86_pkg_temp": "CPU",
        "acpitz": "ACPI",
        "thinkpad": "ThinkPad",
        "nvme": "NVMe",
    }
    if lowered in aliases:
        return aliases[lowered]
    if lowered.startswith("pch_"):
        return "PCH"
    if lowered.startswith("iwlwifi"):
        return "Wi-Fi"
    return name.replace("_", " ").title() or "Sensor"


def _clean_label(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip()
    return re.sub(r"Package id (\d+)", r"Package \1", label, flags=re.IGNORECASE)


def _clean(text: str) -> tuple[str, str]:
    text = " ".join(text.strip().replace("’", "'").split())
    text = _TRAIL.sub("", text).strip()
    text = _PREFIX.sub("", text).strip()
    unit = ""
    match = _UNIT.search(text)
    if match:
        unit = match.group(1).lower()
        text = text[: match.start()].strip()
    return text, unit


def _named(match: re.Match[str] | None) -> str:
    if match is None:
        return ""
    name = " ".join(match.group("name").split()).casefold()
    if name in _RESERVED or name in {"cpu", "fan", "temp", "temperature"}:
        return ""
    return name


def classify(text: str) -> _Request | None:
    """Return the one sensor sentence, or None when Ask should continue."""
    text, unit = _clean(text)
    if not text:
        return None
    if _CPU.fullmatch(text):
        return _Request("cpu", unit=unit)
    if _TEMPERATURE.fullmatch(text):
        return _Request("temperature", unit=unit)
    if _FAN.fullmatch(text):
        return _Request("fan", unit=unit)
    named = _named(_NAMED_TEMP.fullmatch(text))
    if named:
        return _Request("named-temperature", named, unit)
    named = _named(_NAMED_FAN.fullmatch(text))
    if named:
        return _Request("named-fan", named, unit)
    return None


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _token(root: Path, path: Path) -> str | None:
    if not _contained(root, path):
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    text = text.strip()
    if not text or len(text) > 80 or not text.isprintable():
        return None
    return text


def _celsius(root: Path, path: Path) -> float | None:
    text = _token(root, path)
    if text is None or _INTEGER.fullmatch(text) is None:
        return None
    # The kernel unit for both files is millidegree Celsius.
    value = int(text) / 1000.0
    if not math.isfinite(value) or value <= 0.0 or value > 250.0:
        return None
    return value


def _rpm(root: Path, path: Path) -> int | None:
    text = _token(root, path)
    if text is None or _INTEGER.fullmatch(text) is None:
        return None
    value = int(text)
    if value < 0 or value > 200_000:
        return None
    return value


def _dirs(root: Path, parent: Path, pattern: re.Pattern[str]) -> list[Path]:
    if not parent.is_dir():
        return []
    try:
        children = list(parent.iterdir())
    except OSError:
        return []
    found = [
        child for child in children
        if pattern.fullmatch(child.name) and child.is_dir() and _contained(root, child)
    ]
    return sorted(found, key=lambda child: _natural_key(child.name))


def read_temperatures(sysfs: Path = Path("/sys")) -> tuple[Temperature, ...]:
    """Current zone and hwmon temperatures, in discovery order."""
    root = Path(sysfs)
    found: list[Temperature] = []
    for zone in _dirs(root, root / "class" / "thermal", _ZONE):
        celsius = _celsius(root, zone / "temp")
        if celsius is None:
            continue
        raw = _token(root, zone / "type") or zone.name
        index = zone.name.removeprefix("thermal_zone")
        found.append(Temperature(_pretty_chip(raw), raw, f"zone {index}", celsius))
    for hwmon in _dirs(root, root / "class" / "hwmon", _HWMON):
        raw = _token(root, hwmon / "name") or hwmon.name
        try:
            files = list(hwmon.iterdir())
        except OSError:
            continue
        inputs = sorted(
            (item for item in files if _TEMP_FILE.fullmatch(item.name)),
            key=lambda item: _natural_key(item.name),
        )
        for item in inputs:
            celsius = _celsius(root, item)
            if celsius is None:
                continue
            prefix = item.name.removesuffix("_input")
            label = _token(root, hwmon / f"{prefix}_label") or prefix
            found.append(Temperature(
                _pretty_chip(raw), raw, _clean_label(label), celsius,
            ))
    return tuple(found)


def read_fans(sysfs: Path = Path("/sys")) -> tuple[Fan, ...]:
    """Current hwmon tachometers, in discovery order."""
    root = Path(sysfs)
    found: list[Fan] = []
    for hwmon in _dirs(root, root / "class" / "hwmon", _HWMON):
        raw = _token(root, hwmon / "name") or hwmon.name
        try:
            files = list(hwmon.iterdir())
        except OSError:
            continue
        inputs = sorted(
            (item for item in files if _FAN_FILE.fullmatch(item.name)),
            key=lambda item: _natural_key(item.name),
        )
        for item in inputs:
            rpm = _rpm(root, item)
            if rpm is None:
                continue
            prefix = item.name.removesuffix("_input")
            label = _token(root, hwmon / f"{prefix}_label") or prefix
            found.append(Fan(_pretty_chip(raw), raw, _clean_label(label), rpm))
    return tuple(found)


def _same(name: str, chip: str, label: str, wanted: str) -> bool:
    folded = wanted.casefold()
    return folded in {name.casefold(), chip.casefold(), label.casefold()}


def _shown(celsius: float) -> float:
    return float(f"{celsius:.1f}")


def _hottest(readings: tuple[Temperature, ...] | list[Temperature]) -> tuple[Temperature, ...]:
    if not readings:
        return ()
    peak = max(_shown(item.celsius) for item in readings)
    return tuple(item for item in readings if _shown(item.celsius) == peak)


def _format_temperature(reading: Temperature, unit: str) -> str:
    shown = _shown(reading.celsius)
    if unit == "celsius":
        text = f"{shown:.1f}°C"
    else:
        text = f"{shown * 9.0 / 5.0 + 32.0:.1f}°F"
    return f"{reading.chip} / {reading.label}: {text}"


def answer(
    text: str,
    *,
    sysfs: Path = Path("/sys"),
    unit: str = "fahrenheit",
) -> tuple[int, str]:
    """Answer one whole sensor request.

    Status 3 means this is not a sensor sentence. Status 1 means it is, and
    no current file answered it. ``unit`` is the saved display unit. A unit
    named in the request wins, and this function does not write that setting.
    """
    request = classify(text)
    if request is None:
        return NOT_SENSOR, ""
    chosen = request.unit or unit
    if chosen not in {"celsius", "fahrenheit"}:
        chosen = "fahrenheit"
    temperatures = read_temperatures(sysfs)
    if request.kind == "temperature":
        selected = _hottest(temperatures)
        if not selected:
            return 1, "no temperature sensor"
        lines = [_format_temperature(item, chosen) for item in selected]
        return 0, "\n".join(lines)
    if request.kind == "cpu":
        cpu = tuple(
            item for item in temperatures if item.name.casefold() in _CPU_NAMES
        )
        selected = _hottest(cpu)
        if not selected:
            return 1, "no temperature sensor"
        return 0, "\n".join(_format_temperature(item, chosen) for item in selected)
    if request.kind == "named-temperature":
        selected = tuple(
            item for item in temperatures
            if _same(item.name, item.chip, item.label, request.name)
        )
        if not selected:
            return NOT_SENSOR, ""
        return 0, "\n".join(_format_temperature(item, chosen) for item in selected)
    fans = read_fans(sysfs)
    if request.kind == "named-fan":
        fans = tuple(
            item for item in fans
            if _same(item.name, item.chip, item.label, request.name)
        )
        if not fans:
            return NOT_SENSOR, ""
    if not fans:
        return 1, "no fan sensor"
    return 0, "\n".join(
        f"{item.chip} / {item.label}: {item.rpm} RPM" for item in fans
    )
