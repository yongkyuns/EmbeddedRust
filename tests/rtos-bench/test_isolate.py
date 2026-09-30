#!/usr/bin/env python3
"""Fault-isolation harness tests; fake console transcripts are NOT QEMU evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from isolate import commands_for, fresh_matrix_plans, history_prefix_plans, plans, run_boot, run_matrix

FAKE_CONSOLE = r'''#!/usr/bin/env python3
import json, sys, time
MODE = __MODE__
print('NuttShell (NSH)\nnsh> ', end='', flush=True)
for index, line in enumerate(sys.stdin):
    parts = line.split()
    if len(parts) != 4: sys.exit(2)
    _, backend, case, count = parts
    if MODE == 'timeout':
        time.sleep(30)
    if MODE == 'fault':
        print("\nqemu: fatal: Lockup: can't escalate 3 to HardFault", flush=True)
        sys.exit(1)
    row = dict(schema=1, backend=backend, case=case, iterations=int(count), capacity=8,
               valid=True, elapsed_ns=100000000, clock_resolution_ns=1000000,
               policy=2, priority=100, instrumentation='interval-only')
    if case == 'ping-pong':
        row.update(instrumentation='round-trip-sampled', receiver_parked_verified=False,
                   worker_stack_requested=32768, worker_policy=2, worker_priority=100,
                   p50_upper_ns=1, p99_upper_ns=1048576, max_ns=1000000)
    if MODE == 'wrong-count': row['iterations'] += 1
    if MODE == 'truncated':
        print('\nRTBENCH {"schema":1', flush=True)
        sys.exit(0)
    if MODE != 'missing-result':
        print('\nRTBENCH ' + json.dumps(row), flush=True)
    print('nsh> ', end='', flush=True)
'''


class IsolationTests(unittest.TestCase):
    def test_fresh_count_never_selects_history(self):
        for backend in ('rust-std', 'rust-ao'):
            for count in (2000, 200000):
                self.assertEqual(commands_for(backend, count), [(backend, 'ping-pong', count)])

    def test_prelude_is_identical_for_both_backends(self):
        raw = commands_for('rust-std', 200000, True)
        ao = commands_for('rust-ao', 200000, True)
        self.assertEqual(len(raw), 10)
        self.assertEqual(raw[:-1], ao[:-1])
        self.assertEqual(raw[-2], ('rust-std', 'queue-hot', 200000))
        self.assertTrue(all(c[2] == 200000 for c in raw))

    def test_complete_counterbalanced_matrix(self):
        cases = plans(2)
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({c['name'] for c in cases}), 12)
        self.assertEqual(cases[0]['backend'], 'rust-std')
        self.assertEqual(cases[6]['backend'], 'rust-ao')
        for repeat in (0, 1):
            for backend in ('rust-std', 'rust-ao'):
                selected = [p for p in cases if p['repeat'] == repeat and p['backend'] == backend]
                self.assertEqual([(p['iterations'], p['prior_sequence']) for p in selected],
                                 [(2000, False), (200000, False), (200000, True)])

    def test_fresh_matrix_is_one_command_per_boot_and_counterbalanced(self):
        cases = fresh_matrix_plans(2)
        self.assertEqual(len(cases), 28)
        self.assertEqual(len({c['name'] for c in cases}), 28)
        self.assertEqual(cases[0]['backend'], 'c-posix')
        self.assertEqual(cases[-1]['backend'], 'c-posix')
        self.assertTrue(all(c['iterations'] == 200000 for c in cases))
        first = [(c['backend'], c['case']) for c in cases[:14]]
        second = [(c['backend'], c['case']) for c in cases[14:]]
        self.assertEqual(second, list(reversed(first)))

    def test_history_prefix_scan_adds_one_command_at_a_time(self):
        cases = history_prefix_plans('rust-std')
        self.assertEqual(len(cases), 10)
        for prefix, case in enumerate(cases):
            commands = case['explicit_commands']
            self.assertEqual(case['history_prefix'], prefix)
            self.assertEqual(len(commands), prefix + 1)
            self.assertEqual(commands[-1], ('rust-std', 'ping-pong', 200000))
            if prefix:
                self.assertEqual(commands[:-1], cases[-1]['explicit_commands'][:prefix])

    def test_invalid_plan_rejected(self):
        for count in (0, 200, 200001):
            with self.assertRaises(ValueError): commands_for('rust-std', count)
        with self.assertRaises(ValueError): commands_for('unsupported', 2000)
        for repeats in (0, 11, True):
            with self.assertRaises(ValueError): plans(repeats)

    def test_failure_does_not_skip_later_boots(self):
        visited = []
        def runner(image, directory, plan):
            visited.append(plan['name'])
            return dict(plan, qualified=len(visited) != 1, target_started=True,
                        target_completed=len(visited) != 1, error='injected' if len(visited) == 1 else None)
        with tempfile.TemporaryDirectory() as tmp, patch('isolate.run_boot', side_effect=runner):
            result = run_matrix(Path('unused'), Path(tmp), 2)
            self.assertFalse(result['qualified'])
            self.assertEqual((result['planned'], result['completed']), (12, 12))
            self.assertEqual(len(visited), 12)
            self.assertTrue(result['results'][-1]['qualified'])

    def boot(self, mode='success', prior=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / 'fake-qemu'
            fake.write_text(FAKE_CONSOLE.replace('__MODE__', repr(mode)))
            fake.chmod(0o700)
            image = root / 'fixture.elf'
            image.write_bytes(b'fake test image, not a firmware binary')
            plan = dict(name='test', backend='rust-ao', iterations=200000,
                        prior_sequence=prior, repeat=0)
            result = run_boot(image, root / 'result', plan, qemu=str(fake),
                              pacing=0, timeout=2 if mode == 'timeout' else 10)
            stored = json.loads((root / 'result/result.json').read_text())
            self.assertEqual(stored, result)
            self.assertFalse(result['physical_timing_qualified'])
            self.assertTrue((root / 'result/console.log').is_file())
            return result

    def test_complete_boot_requires_each_result(self):
        result = self.boot(prior=True)
        self.assertTrue(result['qualified'])
        self.assertTrue(result['target_completed'])
        self.assertEqual(len(result['results']), 10)
        self.assertEqual(result['results'][-1]['iterations'], 200000)

    def test_guest_fault_retains_failure(self):
        result = self.boot('fault')
        self.assertFalse(result['qualified'])
        self.assertTrue(result['target_started'])
        self.assertFalse(result['target_completed'])
        self.assertIn('fault/lockup', result['error'])

    def test_prelude_fault_does_not_implicate_unrun_target(self):
        result = self.boot('fault', prior=True)
        self.assertFalse(result['target_started'])
        self.assertEqual(result['active_command'], ['c-posix', 'semaphore-hot', 200000])

    def test_false_success_and_truncation_rejected(self):
        for mode in ('missing-result', 'wrong-count', 'truncated'):
            with self.subTest(mode=mode):
                result = self.boot(mode)
                self.assertFalse(result['qualified'])
                self.assertFalse(result['target_completed'])
                self.assertIsNotNone(result['error'])

    def test_timeout_is_not_success(self):
        result = self.boot('timeout')
        self.assertFalse(result['qualified'])
        self.assertIn('TimeoutError', result['error'])


if __name__ == '__main__':
    unittest.main()
