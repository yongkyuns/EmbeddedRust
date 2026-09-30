#!/usr/bin/env python3
"""Independent parsers and invariants for NuttX heap/stack qualification."""
from __future__ import annotations

from dataclasses import dataclass
import json
import unittest


@dataclass(frozen=True)
class HeapRow:
    total: int
    used: int
    free: int
    maxused: int
    maxfree: int
    nused: int
    nfree: int


def parse_meminfo(text: str) -> dict[str, HeapRow]:
    rows: dict[str, HeapRow] = {}
    for raw in text.replace("\r", "").splitlines():
        parts = raw.split()
        if len(parts) < 8 or not all(part.isdigit() for part in parts[:7]):
            continue
        name = " ".join(parts[7:])
        if not name:
            continue
        if name in rows:
            raise AssertionError(f"duplicate meminfo heap {name!r}")
        values = [int(part) for part in parts[:7]]
        rows[name] = HeapRow(*values)
    if not rows:
        raise AssertionError(f"no ordinary heap rows in /proc/meminfo:\n{text}")
    return rows


def validate_heap_cycles(
    app: str,
    baseline: dict[str, HeapRow],
    warm: dict[str, HeapRow],
    checked: list[dict[str, HeapRow]],
) -> list[dict]:
    if not checked:
        raise AssertionError("no checked heap lifecycle samples")
    if set(baseline) != set(warm):
        raise AssertionError(
            f"heap inventory changed during first use: {set(baseline)} != {set(warm)}"
        )

    results = []
    for name in sorted(warm):
        before = baseline[name]
        reference = warm[name]
        if before.total != reference.total:
            raise AssertionError(f"{name}: total heap changed during warmup")
        min_maxfree = reference.maxfree
        max_used = reference.used
        for index, snapshot in enumerate(checked, 1):
            if set(snapshot) != set(warm):
                raise AssertionError(f"cycle {index}: heap inventory changed")
            current = snapshot[name]
            if current.total != reference.total:
                raise AssertionError(f"{name} cycle {index}: total heap changed")
            if current.used != reference.used or current.free != reference.free:
                raise AssertionError(
                    f"{name} cycle {index}: live heap drift "
                    f"used {reference.used}->{current.used}, "
                    f"free {reference.free}->{current.free}"
                )
            if current.maxfree < reference.maxfree:
                raise AssertionError(
                    f"{name} cycle {index}: largest free block regressed "
                    f"{reference.maxfree}->{current.maxfree}"
                )
            min_maxfree = min(min_maxfree, current.maxfree)
            max_used = max(max_used, current.used)
        results.append(
            {
                "app": app,
                "heap": name,
                "cycles": len(checked),
                "baseline_used": before.used,
                "warm_used": reference.used,
                "first_use_used_delta": reference.used - before.used,
                "baseline_maxfree": before.maxfree,
                "warm_maxfree": reference.maxfree,
                "first_use_maxfree_delta": reference.maxfree - before.maxfree,
                "max_checked_used": max_used,
                "min_checked_maxfree": min_maxfree,
                "stable_after_warmup": True,
            }
        )
    return results


def _json_lines(text: str, prefix: str) -> list[dict]:
    rows = []
    for line in text.replace("\r", "").splitlines():
        if line.startswith(prefix):
            rows.append(json.loads(line.removeprefix(prefix)))
    return rows


def validate_stack_output(
    text: str,
    *,
    scenarios: tuple[str, ...] = ("steady", "burst", "slow-consumer", "cpu-load"),
    rounds: int = 1,
    producers: int = 2,
    workers: int = 2,
) -> list[dict]:
    details = _json_lines(text, "NUTTX_STACK_RESULT ")
    summaries = _json_lines(text, "NUTTX_STACK_SUMMARY ")
    expected_names = {"ao-collector"}
    expected_names.update(f"ao-source-{index}" for index in range(producers))
    expected_names.update(f"ao-worker-{index}" for index in range(workers))
    expected_keys = {
        (scenario, round_number)
        for scenario in scenarios
        for round_number in range(1, rounds + 1)
    }

    grouped: dict[tuple[str, int], dict[str, dict]] = {}
    for row in details:
        required = {
            "scenario", "round", "name", "pid", "stack_size",
            "stack_used", "headroom", "fill_permille",
        }
        if set(row) != required:
            raise AssertionError(f"unexpected stack detail schema: {row}")
        key = (row["scenario"], row["round"])
        if key not in expected_keys:
            raise AssertionError(f"unexpected stack scenario/round: {key}")
        by_name = grouped.setdefault(key, {})
        if row["name"] in by_name:
            raise AssertionError(f"duplicate stack row: {key} {row['name']}")
        size, used = row["stack_size"], row["stack_used"]
        if not isinstance(size, int) or not isinstance(used, int) or size <= 0 or used <= 0:
            raise AssertionError(f"invalid stack sizes: {row}")
        if used > size or row["headroom"] != size - used:
            raise AssertionError(f"stack usage exceeds or disagrees with size: {row}")
        if row["fill_permille"] != used * 1000 // size:
            raise AssertionError(f"incorrect stack fill ratio: {row}")
        by_name[row["name"]] = row

    if set(grouped) != expected_keys:
        raise AssertionError(f"missing stack groups: expected={expected_keys} actual={set(grouped)}")

    summary_by_key: dict[tuple[str, int], dict] = {}
    for row in summaries:
        required = {
            "scenario", "round", "owners", "max_used",
            "min_headroom", "max_fill_permille",
        }
        if set(row) != required:
            raise AssertionError(f"unexpected stack summary schema: {row}")
        key = (row["scenario"], row["round"])
        if key in summary_by_key:
            raise AssertionError(f"duplicate stack summary: {key}")
        summary_by_key[key] = row

    if set(summary_by_key) != expected_keys:
        raise AssertionError(
            f"stack summary inventory mismatch: expected={expected_keys} actual={set(summary_by_key)}"
        )

    validated = []
    for key in sorted(expected_keys):
        by_name = grouped[key]
        if set(by_name) != expected_names:
            raise AssertionError(
                f"{key}: owner inventory mismatch "
                f"expected={expected_names} actual={set(by_name)}"
            )
        rows = list(by_name.values())
        summary = summary_by_key[key]
        if summary["owners"] != len(expected_names):
            raise AssertionError(f"{key}: wrong owner count")
        if summary["max_used"] != max(row["stack_used"] for row in rows):
            raise AssertionError(f"{key}: max_used summary mismatch")
        if summary["min_headroom"] != min(row["headroom"] for row in rows):
            raise AssertionError(f"{key}: min_headroom summary mismatch")
        if summary["max_fill_permille"] != max(row["fill_permille"] for row in rows):
            raise AssertionError(f"{key}: max_fill_permille summary mismatch")
        validated.extend(rows)
    return validated


class NuttXMemoryParsers(unittest.TestCase):
    MEM = """      total       used       free    maxused    maxfree  nused  nfree name
    2097152     100000    1997152     130000    1800000     20      3 Umem
     131072      10000     121072      12000     120000      5      2 Kmem
"""

    def test_meminfo_parser(self):
        rows = parse_meminfo(self.MEM)
        self.assertEqual(rows["Umem"].maxfree, 1_800_000)
        self.assertEqual(rows["Kmem"].used, 10_000)

    def test_heap_stability_accepts_equal_or_improved_largest_block(self):
        base = parse_meminfo(self.MEM)
        warm = dict(base)
        improved = dict(warm)
        improved["Umem"] = HeapRow(2097152, 100000, 1997152, 130000, 1800100, 20, 2)
        rows = validate_heap_cycles("ao-stress", base, warm, [warm, improved])
        self.assertEqual(rows[1]["cycles"], 2)

    def test_heap_live_drift_is_rejected(self):
        base = parse_meminfo(self.MEM)
        bad = dict(base)
        bad["Umem"] = HeapRow(2097152, 100064, 1997088, 130000, 1800000, 21, 3)
        with self.assertRaises(AssertionError):
            validate_heap_cycles("ao-stress", base, base, [bad])

    def test_largest_free_regression_is_rejected(self):
        base = parse_meminfo(self.MEM)
        bad = dict(base)
        bad["Umem"] = HeapRow(2097152, 100000, 1997152, 130000, 1700000, 20, 4)
        with self.assertRaises(AssertionError):
            validate_heap_cycles("ao-stress", base, base, [bad])

    @staticmethod
    def stack_text(mutate=None):
        lines = []
        names = ["ao-collector", "ao-source-0", "ao-source-1", "ao-worker-0", "ao-worker-1"]
        for scenario in ("steady", "burst", "slow-consumer", "cpu-load"):
            rows = []
            for index, name in enumerate(names):
                row = {
                    "scenario": scenario,
                    "round": 1,
                    "name": name,
                    "pid": 10 + index,
                    "stack_size": 32768,
                    "stack_used": 4096 + index * 64,
                }
                row["headroom"] = row["stack_size"] - row["stack_used"]
                row["fill_permille"] = row["stack_used"] * 1000 // row["stack_size"]
                if mutate:
                    mutate(row)
                rows.append(row)
                lines.append("NUTTX_STACK_RESULT " + json.dumps(row, separators=(",", ":")))
            summary = {
                "scenario": scenario,
                "round": 1,
                "owners": len(rows),
                "max_used": max(row["stack_used"] for row in rows),
                "min_headroom": min(row["headroom"] for row in rows),
                "max_fill_permille": max(row["fill_permille"] for row in rows),
            }
            lines.append("NUTTX_STACK_SUMMARY " + json.dumps(summary, separators=(",", ":")))
        return "\n".join(lines)

    def test_stack_inventory_and_accounting(self):
        self.assertEqual(len(validate_stack_output(self.stack_text())), 20)

    def test_stack_overflow_is_rejected(self):
        def mutate(row):
            if row["name"] == "ao-worker-0":
                row["stack_used"] = row["stack_size"] + 1
                row["headroom"] = -1
                row["fill_permille"] = 1000
        with self.assertRaises(AssertionError):
            validate_stack_output(self.stack_text(mutate))

    def test_missing_owner_is_rejected(self):
        text = self.stack_text()
        line = next(line for line in text.splitlines() if '"name":"ao-source-1"' in line)
        with self.assertRaises(AssertionError):
            validate_stack_output(text.replace(line + "\n", "", 1))

    def test_false_success_without_measurements_is_rejected(self):
        with self.assertRaises(AssertionError):
            validate_stack_output("AO_STRESS PASS scenarios=4 rounds=1")


if __name__ == "__main__":
    unittest.main()
