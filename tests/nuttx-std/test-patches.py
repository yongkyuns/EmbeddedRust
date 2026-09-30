"""Fail-closed checks for the NuttX source patch series."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "external/nuttx"
PATCH = ROOT / "platform/nuttx/patches/0001-flat-build-global-pthread-keys.patch"
TOOL = ROOT / "tools/apply-nuttx-patches.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PatchSeriesTests(unittest.TestCase):
    def setUp(self):
        # Mirror target/firmware/...: the source archive is nested inside the
        # nxrs Git checkout, but must not inherit that checkout's Git root.
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "nuttx"
        self.source.mkdir()
        names = [line.split("\t", 2)[2] for line in subprocess.check_output(
            ["git", "apply", "--numstat", str(PATCH)], text=True,
        ).splitlines()]
        self.original = {}
        for name in names:
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(UPSTREAM / name, destination)
            self.original[name] = digest(destination)
        self.record = Path(self.temp.name) / "patches.json"

    def apply(self):
        return subprocess.run(
            ["python3", str(TOOL), "--source", str(self.source),
             "--revision", "test-revision", "--record", str(self.record)],
            text=True, capture_output=True,
        )

    def test_applies_only_to_copy_and_records_provenance(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = json.loads(self.record.read_text())
        self.assertEqual(ledger["nuttx_revision"], "test-revision")
        self.assertEqual(ledger["patches"][0]["sha256"], digest(PATCH))
        for name, hashes in ledger["patches"][0]["files"].items():
            self.assertEqual(hashes["before"], self.original[name])
            self.assertEqual(hashes["after"], digest(self.source / name))
            self.assertEqual(digest(UPSTREAM / name), self.original[name])
        self.assertIn("config TLS_GLOBAL_KEYS", (self.source / "libs/libc/tls/Kconfig").read_text())
        self.assertIn("config TLS_DTOR_ITERATIONS", (self.source / "libs/libc/tls/Kconfig").read_text())
        self.assertIn("tls->tl_elem[candidate] = 0;", (self.source / "libs/libc/tls/tls_destruct.c").read_text())
        self.assertIn("g_keyused[candidate] = true", (self.source / "libs/libc/pthread/pthread_keycreate.c").read_text())
        self.assertIn("g_keydtors[candidate] = destructor", (self.source / "libs/libc/pthread/pthread_keycreate.c").read_text())

    def test_rejects_reapplication_without_mutation(self):
        self.assertEqual(self.apply().returncode, 0)
        before = {name: digest(self.source / name) for name in self.original}
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already applied", result.stderr)
        self.assertEqual(before, {name: digest(self.source / name) for name in self.original})

    def test_rejects_incompatible_source_without_mutation(self):
        path = self.source / "libs/libc/tls/Kconfig"
        path.write_text(path.read_text().replace("TLS interfaces.\n\nconfig TLS_TASK_NELEM", "CHANGED interfaces.\n\nconfig TLS_TASK_NELEM"))
        before = {name: digest(self.source / name) for name in self.original}
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incompatible", result.stderr)
        self.assertEqual(before, {name: digest(self.source / name) for name in self.original})
        self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main()
