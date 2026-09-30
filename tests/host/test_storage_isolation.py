"""Reject corrupted persisted output without a compiler or device."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'tools/check-storage-isolation.py'
SPEC = importlib.util.spec_from_file_location('storage_isolation', SOURCE)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class RecordOracleTests(unittest.TestCase):
    def test_independent_record_oracle_rejects_missing_extra_and_corrupt_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for n, value in [(1, 7), (2, 9)]:
                header = b'RCAMREC1\x02\x00\x02\x00\x00\x00\x00\x00'
                header += n.to_bytes(8, 'little') + (n * 10).to_bytes(8, 'little') + (4).to_bytes(8, 'little')
                (root / f'{n:020}.rcam').write_bytes(header + bytes([value]) * 4)
            CHECK.check_records(root)
            path = root / f'{1:020}.rcam'
            good = path.read_bytes()
            for bad in [good[:-1], good + b'x', b'X' + good[1:], good[:24] + bytes(8) + good[32:], good[:-4] + bytes(4)]:
                path.write_bytes(bad)
                with self.assertRaises(AssertionError):
                    CHECK.check_records(root)
            path.write_bytes(good)
            extra = root / 'unfinished.part'; extra.write_bytes(b'')
            with self.assertRaises(AssertionError):
                CHECK.check_records(root)
            extra.unlink(); path.unlink()
            with self.assertRaises(AssertionError):
                CHECK.check_records(root)


if __name__ == '__main__':
    unittest.main()
