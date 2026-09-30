"""Run real host executables and reject false-success transcripts.

Build first: cargo build --locked -p nxrs-std-demo -p nxrs-ao-stress
Run: python3 -m unittest discover -s tests/host -p test_std_apps.py -v
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECIPES = {"vec", "fixed", "maps", "queues", "bytes", "ownership", "channels", "synchronization", "deadlines"}
SCENARIOS = {"steady", "burst", "slow-consumer", "cpu-load"}


def validate_std(text: str, cases: set[str] = RECIPES) -> None:
    lines = text.replace("\r", "").splitlines()
    assert not any("STD_DEMO FAIL" in line or "panicked" in line for line in lines), text
    actual = [m[1] for line in lines if (m := re.fullmatch(r"STD_DEMO case=(\S+) status=pass", line))]
    assert len(actual) == len(cases) and set(actual) == cases, text
    assert lines.count(f"STD_DEMO PASS cases={len(cases)}") == 1, text


def validate_stress(text: str, scenarios: set[str] = SCENARIOS, rounds: int = 1) -> list[dict]:
    lines = text.replace("\r", "").splitlines()
    assert not any("AO_STRESS FAIL" in line or "panicked" in line for line in lines), text
    rows = [json.loads(line.removeprefix("AO_RESULT ")) for line in lines if line.startswith("AO_RESULT ")]
    assert len(rows) == len(scenarios) * rounds, text
    assert {(r["scenario"], r["round"]) for r in rows} == {(s, n) for s in scenarios for n in range(1, rounds + 1)}, text
    for row in rows:
        assert row["attempted"] == row["accepted"] + row["ingress_full"], row
        assert row["accepted"] == row["handled"], row
        assert row["handled"] == row["forwarded"] + row["egress_full"], row
        assert row["forwarded"] == row["received"] > 0, row
        assert row["integrity_errors"] == 0 and row["joined"] is True, row
        assert 0 <= row["deadline_misses"] <= row["received"], row
        assert 0 < row["p50_upper_us"] <= row["p95_upper_us"] <= row["p99_upper_us"], row
        assert row["elapsed_us"] > 0 and row["shutdown_us"] >= 0, row
    assert lines.count(f"AO_STRESS PASS scenarios={len(scenarios)} rounds={rounds}") == 1, text
    return rows


class StdApps(unittest.TestCase):
    def run_app(self, name: str, *args: str, success: bool = True) -> str:
        executable = ROOT / "target" / "debug" / name
        self.assertTrue(executable.is_file(), f"build the app first: {executable}")
        result = subprocess.run([str(executable), *args], capture_output=True, text=True, timeout=30)
        text = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, text)
        else:
            self.assertNotEqual(result.returncode, 0, text)
            self.assertNotIn("STD_DEMO PASS", text)
            self.assertNotIn("AO_STRESS PASS", text)
        return text

    def test_all_std_recipes(self):
        validate_std(self.run_app("std-demo"))

    def test_individual_recipe(self):
        validate_std(self.run_app("std-demo", "--case", "channels"), {"channels"})

    def test_stress_scenarios(self):
        validate_stress(self.run_app("ao-stress", "--duration-ms", "60"))

    def test_small_queues_and_restarts(self):
        validate_stress(self.run_app("ao-stress", "--scenario", "slow-consumer", "--duration-ms", "30", "--capacity", "1", "--rounds", "3"), {"slow-consumer"}, 3)

    def test_invalid_options(self):
        for name, args in [
            ("std-demo", ("--case", "missing")),
            ("std-demo", ("--case", "vec", "extra")),
            ("ao-stress", ("--capacity", "0")),
            ("ao-stress", ("--producers", "9")),
            ("ao-stress", ("--duration-ms", "0")),
            ("ao-stress", ("--work", "100001")),
            ("ao-stress", ("--scenario", "missing")),
            ("ao-stress", ("--workers",)),
            ("ao-stress", ("--mystery", "1")),
        ]:
            with self.subTest(name=name, args=args):
                self.run_app(name, *args, success=False)

    def test_false_success_transcripts_rejected(self):
        with self.assertRaises(AssertionError):
            validate_std("STD_DEMO PASS cases=9\n")
        with self.assertRaises(AssertionError):
            validate_stress("AO_STRESS PASS scenarios=4 rounds=1\n")


if __name__ == "__main__":
    unittest.main()
