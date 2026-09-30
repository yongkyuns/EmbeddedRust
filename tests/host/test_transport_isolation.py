"""Transport dependency and received-datagram regression controls."""
import copy
import importlib.util
from pathlib import Path
import unittest
import test_architecture

SOURCE = Path(__file__).resolve().parents[2] / 'tools/check-transport-isolation.py'
SPEC = importlib.util.spec_from_file_location('transport_isolation', SOURCE)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class PacketOracleTests(unittest.TestCase):
    def test_missing_extra_reordered_corrupted_and_wrong_source_are_rejected(self):
        good = [{'hex': '007f80ff', 'peer': ['127.0.0.1', 12345]},
                {'hex': b'transport-only'.hex(), 'peer': ['127.0.0.1', 12345]}]
        CHECK.check_packets(good)
        bad = [good[:1], good + good[:1], list(reversed(good))]
        for field, value in [('hex', '007f80'), ('hex', '007f8000'), ('peer', ['127.0.0.1', 9999])]:
            changed = copy.deepcopy(good)
            changed[0][field] = value
            bad.append(changed)
        for peer in [['192.0.2.1', 12345], ['127.0.0.1', 0]]:
            changed = copy.deepcopy(good)
            for packet in changed:
                packet['peer'] = peer
            bad.append(changed)
        for packets in bad:
            with self.subTest(packets=packets), self.assertRaises(AssertionError):
                CHECK.check_packets(packets)


class TransportArchitectureTests(test_architecture.ArchitectureTests):
    def transport_packages(self):
        self.storage_packages()
        for role in ('api', 'native', 'nuttx', 'mock'):
            self.domain_package('transport-' + role, 'hal/transport/' + role)
        self.add('transport-api', 'common')
        for role in ('native', 'nuttx', 'mock'):
            self.add('transport-' + role, 'transport-api')

    def test_transport_providers_remain_independent(self):
        self.transport_packages()
        self.assertEqual(self.violations(), [])
        for a, b in [('transport-api', 'transport-native'), ('transport-native', 'camera-native'),
                     ('transport-native', 'storage-native'), ('transport-mock', 'mock'),
                     ('service', 'transport-native'), ('transport-native', 'native')]:
            for options in ({}, {'optional': True}, {'kind': 'build'}, {'target': 'cfg(windows)'}):
                with self.subTest(edge=(a, b), options=options):
                    self.add(a, b, **options)
                    self.assertTrue(self.violations())
                    self.packages[a]['dependencies'].pop()

    def test_rustcam_app_cannot_select_transport_provider_directly(self):
        self.transport_packages()
        self.packages['app']['name'] = 'rustcam-applications'
        self.add('app', 'transport-native', rename='configured-transport', optional=True)
        self.assertTrue(self.violations())

    def test_transport_nuttx_provider_is_not_a_default_member(self):
        self.transport_packages()
        self.metadata['workspace_default_members'].append('transport-nuttx')
        self.assertTrue(self.violations())


if __name__ == '__main__':
    unittest.main()
