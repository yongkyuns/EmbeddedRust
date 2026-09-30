"""Validate real memory-test transcripts, or run parser negative controls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

EXPECTED = {
    "std-demo": {
        **{case: {"setup", "first-use", "steady", "reclaimed"}
           for case in ("vec-bounded", "hashmap", "string")},
        "vec-dynamic": {"growth", "reclaimed"},
        "vec-reserved": {"setup", "reserved-fill", "growth", "reclaimed"},
        "fixed-array": {"steady"},
    },
    "ao-stress": {
        "caller-runtime": {"first-use", "reuse"},
        "owned-buffer": {"setup", "first-use", "steady", "teardown", "reclaimed"},
        **{case + "-lifecycle": {"first-run", "warmed-cycles"}
           for case in ("steady", "burst", "slow-consumer", "cpu-load")},
    },
}
COUNTS = {"alloc", "zeroed", "realloc", "dealloc", "failed"}
SIZES = {"live_before", "live_after", "blocks_before", "blocks_after", "peak_process_requested_bytes"}
KEYS = COUNTS | SIZES | {"app", "case", "phase", "valid"}


def validate(text: str, app: str) -> list[dict]:
    if app not in EXPECTED:
        raise ValueError("unknown app")
    lines = text.replace("\r", "").splitlines()
    if "panicked" in text or "test result: FAILED" in text:
        raise ValueError("test failed")
    rows = []
    seen = set()
    for line in lines:
        if not line.startswith("MEMORY_RESULT "):
            continue
        row = json.loads(line.removeprefix("MEMORY_RESULT "))
        if set(row) != KEYS or row["app"] != app or row["valid"] is not True:
            raise ValueError("invalid report schema/app/validity")
        for key in COUNTS | SIZES:
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError("invalid unsigned counter")
        key = (row["case"], row["phase"])
        if key in seen:
            raise ValueError("duplicate phase")
        seen.add(key)
        if row["failed"] or row["peak_process_requested_bytes"] < max(row["live_before"], row["live_after"]):
            raise ValueError("failed allocation or impossible lifetime peak")
        zero_window = row["phase"] in {"steady", "reserved-fill"} or (
            app == "std-demo" and row["phase"] == "first-use")
        reclaimed = row["phase"] in {"reclaimed", "warmed-cycles", "reuse"} or zero_window
        if zero_window and any(row[k] for k in COUNTS):
            raise ValueError("allocator activity in zero-call phase")
        if reclaimed and (row["live_after"] != row["live_before"] or row["blocks_after"] != row["blocks_before"]):
            raise ValueError("retained allocation at reclamation boundary")
        if row["phase"] == "growth" and row["realloc"] == 0:
            raise ValueError("missing observed Vec growth")
        rows.append(row)
    expected = {(case, phase) for case, phases in EXPECTED[app].items() for phase in phases}
    if seen != expected:
        raise ValueError(f"incomplete/unexpected phases: missing={expected - seen}, extra={seen - expected}")
    if lines.count(f"MEMORY_PASS app={app} cases={len(EXPECTED[app])}") != 1:
        raise ValueError("missing or duplicate completion")
    if lines.count(f"MEMORY_CONTROL app={app} kind=allocation-and-retention rejected=true") != 1:
        raise ValueError("missing observer negative control")
    return rows


def synthetic(app: str) -> str:
    """Only a parser test fixture, not benchmark/measurement evidence."""
    lines = [f"MEMORY_CONTROL app={app} kind=allocation-and-retention rejected=true"]
    for case, phases in EXPECTED[app].items():
        for phase in sorted(phases):
            row = dict.fromkeys(COUNTS | SIZES, 0)
            row.update(app=app, case=case, phase=phase, valid=True)
            if phase == "growth":
                row["realloc"] = 1
            lines.append("MEMORY_RESULT " + json.dumps(row))
    lines.append(f"MEMORY_PASS app={app} cases={len(EXPECTED[app])}")
    return "\n".join(lines)


class MemoryReportTests(unittest.TestCase):
    def test_complete_schema(self):
        self.assertEqual(len(validate(synthetic("std-demo"), "std-demo")), 19)
        self.assertEqual(len(validate(synthetic("ao-stress"), "ao-stress")), 15)

    def test_success_marker_is_not_evidence(self):
        with self.assertRaises(ValueError):
            validate("MEMORY_PASS app=std-demo cases=6", "std-demo")

    def test_missing_duplicate_and_wrong_app(self):
        text = synthetic("std-demo")
        result = next(line for line in text.splitlines() if line.startswith("MEMORY_RESULT "))
        for changed in [text.replace(result, ""), text + "\n" + result,
                        text.replace('"app": "std-demo"', '"app": "ao-stress"')]:
            with self.subTest(changed=changed[:60]), self.assertRaises(ValueError):
                validate(changed, "std-demo")

    def test_activity_leak_invalid_and_bad_numeric_values(self):
        text = synthetic("std-demo")
        original = next(line for line in text.splitlines()
                        if '"phase": "steady"' in line)
        for key, value in [("alloc", 1), ("live_after", 1), ("blocks_after", 1),
                           ("valid", False), ("dealloc", -1), ("zeroed", True)]:
            row = json.loads(original.removeprefix("MEMORY_RESULT "))
            row[key] = value
            changed = text.replace(original, "MEMORY_RESULT " + json.dumps(row))
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(changed, "std-demo")

    def test_caller_runtime_reuse_cannot_hide_continuing_retention(self):
        text = synthetic("ao-stress")
        original = next(line for line in text.splitlines() if '"phase": "reuse"' in line)
        row = json.loads(original.removeprefix("MEMORY_RESULT "))
        row.update(live_after=48, blocks_after=1, peak_process_requested_bytes=48)
        with self.assertRaises(ValueError):
            validate(text.replace(original, "MEMORY_RESULT " + json.dumps(row)), "ao-stress")

    def test_missing_control_and_failure_after_success(self):
        text = synthetic("ao-stress")
        for changed in ["\n".join(text.splitlines()[1:]), text + "\nthread panicked"]:
            with self.assertRaises(ValueError):
                validate(changed, "ao-stress")


if __name__ == "__main__":
    if "--app" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--app", required=True, choices=EXPECTED)
        parser.add_argument("--log", required=True, type=Path)
        args = parser.parse_args()
        rows = validate(args.log.read_text(), args.app)
        print(f"MEMORY_TRANSCRIPT PASS app={args.app} records={len(rows)}")
    else:
        unittest.main()
