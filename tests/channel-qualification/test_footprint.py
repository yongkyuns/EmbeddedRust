import copy
import tempfile
import unittest
from pathlib import Path
import footprint as f


class ComparisonTests(unittest.TestCase):
    def records(self):
        identity = {key: 'fixed' for key in f.IDENTITY}
        identity['instrumented'] = False
        result = []
        for i, name in enumerate(f.VARIANTS):
            result.append({'schema': 1, 'variant': name, 'identity': copy.deepcopy(identity),
                           'metrics': dict(text_bytes=100 + i, data_bytes=10, bss_bytes=20,
                                           flash_like_bytes=110 + i, static_ram_bytes=30,
                                           elf_file_bytes=1000 + i),
                           'artifacts': {'elf': 'not-read-in-structural-tests', 'sha256': 'test'}})
        return result

    def test_matched_deltas(self):
        report = f.compare(self.records(), False)
        self.assertEqual(report['comparisons'][0]['delta_bytes']['flash_like_bytes'], 1)
        self.assertIn('cq-crossbeam', f.markdown(report))

    def test_every_identity_field_is_checked(self):
        for key in f.IDENTITY:
            with self.subTest(field=key):
                records = self.records()
                records[-1]['identity'][key] = True if key == 'instrumented' else 'changed'
                with self.assertRaises(ValueError):
                    f.compare(records, False)

    def test_missing_variant(self):
        with self.assertRaises(ValueError):
            f.compare(self.records()[:-1], False)

    def test_duplicate_variant(self):
        records = self.records()
        with self.assertRaises(ValueError):
            f.compare(records + [records[0]], False)

    def test_boolean_and_negative_metrics_rejected(self):
        for value in [True, -1, '100']:
            records = self.records()
            records[0]['metrics']['text_bytes'] = value
            with self.assertRaises(ValueError):
                f.compare(records, False)

    def test_derived_metrics_checked(self):
        records = self.records()
        records[0]['metrics']['static_ram_bytes'] += 1
        with self.assertRaises(ValueError):
            f.compare(records, False)

    def test_real_artifact_hash_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'image'
            artifact.write_bytes(b'linked artifact stand-in')
            records = self.records()
            for record in records:
                record['artifacts'] = {'elf': str(artifact), 'sha256': f.sha256(artifact)}
            f.compare(records)
            artifact.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                f.compare(records)

    def test_empty_configuration_identity_rejected(self):
        records = self.records()
        records[0]['identity']['kernel_config_sha256'] = ''
        with self.assertRaises(ValueError):
            f.compare(records, False)

    def test_zero_baseline_percent_is_not_infinity(self):
        records = self.records()
        records[0]['metrics'] = {key: 0 for key in f.FIELDS}
        report = f.compare(records, False)
        self.assertIsNone(report['comparisons'][0]['delta_percent']['flash_like_bytes'])

    def test_deployment_hash_and_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'image'
            artifact.write_bytes(b'firmware')
            records = self.records()
            for record in records:
                record['artifacts'] = {'elf': str(artifact), 'sha256': f.sha256(artifact),
                                       'deployment_image': str(artifact),
                                       'deployment_sha256': f.sha256(artifact), 'deployment_bytes': 8}
            f.compare(records)
            records[0]['artifacts']['deployment_bytes'] = 9
            with self.assertRaises(ValueError):
                f.compare(records)


if __name__ == '__main__':
    unittest.main()
