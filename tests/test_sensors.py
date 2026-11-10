"""The kilix-sensors reader answers one sysfs reading and does not sample."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kilix_telemetry.sensors import answer


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(root: Path) -> None:
    write(root, "class/thermal/thermal_zone0/type", "x86_pkg_temp\n")
    write(root, "class/thermal/thermal_zone0/temp", "72000\n")
    write(root, "class/hwmon/hwmon0/name", "coretemp\n")
    write(root, "class/hwmon/hwmon0/temp1_label", "Package id 0\n")
    write(root, "class/hwmon/hwmon0/temp1_input", "72000\n")
    write(root, "class/hwmon/hwmon0/temp2_label", "Core 0\n")
    write(root, "class/hwmon/hwmon0/temp2_input", "61000\n")
    write(root, "class/hwmon/hwmon2/name", "nvme\n")
    write(root, "class/hwmon/hwmon2/temp1_label", "Composite\n")
    write(root, "class/hwmon/hwmon2/temp1_input", "51000\n")
    write(root, "class/hwmon/hwmon2/fan1_label", "Controller\n")
    write(root, "class/hwmon/hwmon2/fan1_input", "3210\n")
    write(root, "class/hwmon/hwmon4/name", "thinkpad\n")
    write(root, "class/hwmon/hwmon4/fan1_input", "4411\n")
    write(root, "class/hwmon/hwmon3/name", "acpitz\n")
    write(root, "class/hwmon/hwmon3/temp1_input", "40000\n")


class SensorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sysfs = Path(temporary.name)
        fixture(self.sysfs)

    def ask(self, text: str, unit: str = "celsius") -> tuple[int, str]:
        return answer(text, sysfs=self.sysfs, unit=unit)

    def test_hottest_cpu_named_and_fan_readings(self) -> None:
        status, text = self.ask("what is the temperature?")
        self.assertEqual(status, 0)
        self.assertEqual(
            text,
            "CPU / zone 0: 72.0°C\nCPU / Package 0: 72.0°C",
        )
        status, text = self.ask("what is the cpu temperature?")
        self.assertEqual(text, "CPU / zone 0: 72.0°C\nCPU / Package 0: 72.0°C")
        status, text = self.ask("nvme temperature")
        self.assertEqual(status, 0)
        self.assertEqual(text, "NVMe / Composite: 51.0°C")
        status, text = self.ask("show the acpi temperature")
        self.assertEqual(text, "ACPI / temp1: 40.0°C")
        status, text = self.ask("what's the package 0 temperature")
        self.assertEqual(text, "CPU / Package 0: 72.0°C")
        status, text = self.ask("what's the fan speed?")
        self.assertEqual(
            text,
            "NVMe / Controller: 3210 RPM\nThinkPad / fan1: 4411 RPM",
        )
        status, text = self.ask("what's the thinkpad fan speed")
        self.assertEqual(text, "ThinkPad / fan1: 4411 RPM")
        status, text = self.ask("what is the temperature in fahrenheit?", unit="celsius")
        self.assertEqual(
            text,
            "CPU / zone 0: 161.6°F\nCPU / Package 0: 161.6°F",
        )

    def test_small_millidegree_value_stays_a_fraction_of_a_degree(self) -> None:
        alone = self.sysfs / "small"
        write(alone, "class/thermal/thermal_zone0/type", "acpitz\n")
        write(alone, "class/thermal/thermal_zone0/temp", "500\n")
        status, text = answer("temperature", sysfs=alone, unit="celsius")
        self.assertEqual((status, text), (0, "ACPI / zone 0: 0.5°C"))

    def test_zero_celsius_is_a_reading_and_a_missing_sensor_is_an_error(self) -> None:
        write(self.sysfs, "class/hwmon/hwmon3/temp2_input", "0\n")
        status, text = self.ask("show the acpi temperature")
        self.assertEqual(status, 0)
        self.assertEqual(text, "ACPI / temp1: 40.0°C\nACPI / temp2: 0.0°C")
        write(self.sysfs, "class/hwmon/hwmon3/temp2_input", "-200000\n")
        status, text = self.ask("show the acpi temperature")
        self.assertEqual((status, text), (0, "ACPI / temp1: 40.0°C"))
        freezing = self.sysfs / "freeze"
        write(freezing, "class/hwmon/hwmon0/name", "acpitz\n")
        write(freezing, "class/hwmon/hwmon0/temp1_input", "-100000\n")
        status, text = answer("acpitz temperature", sysfs=freezing, unit="celsius")
        self.assertEqual((status, text), (0, "ACPI / temp1: -100.0°C"))
        write(freezing, "class/hwmon/hwmon0/temp1_input", "-100001\n")
        status, text = answer("acpitz temperature", sysfs=freezing, unit="celsius")
        self.assertEqual((status, text), (1, "no current temperature"))
        write(freezing, "class/hwmon/hwmon0/temp1_input", "250001\n")
        status, text = answer("acpitz temperature", sysfs=freezing, unit="celsius")
        self.assertEqual((status, text), (1, "no current temperature"))
        status, text = answer("nvme temperature", sysfs=freezing, unit="celsius")
        self.assertEqual(status, 3)
        empty = self.sysfs / "empty"
        empty.mkdir()
        status, text = answer("how hot is it?", sysfs=empty, unit="celsius")
        self.assertEqual((status, text), (1, "no temperature sensor"))
        status, text = answer("fan rpm", sysfs=empty, unit="celsius")
        self.assertEqual((status, text), (1, "no fan sensor"))

    def test_unknown_name_and_other_sentences_continue(self) -> None:
        for text in (
            "what's the wifi temperature",
            "what's my temperature",
            "what's the cpu load",
            "how much memory is free",
            "how do I see the temperature",
            "temperatures",
            "open the temperature dashboard",
            "how hot is it in Tokyo",
            "temperature in Paris",
            "what's the weather in Tokyo",
            "30 c to f",
            "why is it hot",
            "cpu temperature and close the pane",
            "set the fan to 2000",
            "show cpu",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.ask(text)[0], 3)

    def test_closed_phrases_match(self) -> None:
        for text in (
            "temperature",
            "the temperature",
            "show the temperature",
            "check the temperature",
            "what's the temperature",
            "how hot is it",
            "how hot is this computer",
            "cpu temperature",
            "the cpu temperature",
            "cpu temp",
            "show cpu temperature",
            "check the cpu temperature",
            "what's the cpu temperature",
            "what is my cpu temperature",
            "how hot is the cpu",
            "fan speed",
            "fan rpm",
            "show the fan speed",
            "what's the thinkpad fan speed",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(self.ask(text)[0], 3, text)
