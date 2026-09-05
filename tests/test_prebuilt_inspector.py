import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('inspect_prebuilts', ROOT / 'tools/inspect_prebuilts.py')
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


def module(vermagic=b'6.1.test SMP preempt mod_unload aarch64'):
    names = b'\0.shstrtab\0.modinfo\0'
    info = b'name=test\0vermagic=' + vermagic + b'\0depends=\0'
    data = bytearray(64 + 3 * 64)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', data, 16, 1, 183, 1)
    struct.pack_into('<Q', data, 40, 64)
    struct.pack_into('<HHHH', data, 56, 0, 64, 3, 1)
    struct.pack_into('<IIQQQQIIQQ', data, 128, 1, 3, 0, 0, len(data), len(names), 0, 0, 1, 0)
    struct.pack_into('<IIQQQQIIQQ', data, 192, 11, 1, 0, 0, len(data) + len(names), len(info), 0, 0, 1, 0)
    return bytes(data) + names + info


class InspectorTests(unittest.TestCase):
    def test_reads_arm64_modinfo(self):
        self.assertEqual(inspector.modinfo(module())['name'], ['test'])

    def test_rejects_truncated_header(self):
        with self.assertRaises(ValueError): inspector.modinfo(module()[:40])

    def test_rejects_non_arm64(self):
        data = bytearray(module()); struct.pack_into('<H', data, 18, 62)
        with self.assertRaises(ValueError): inspector.modinfo(data)

    def test_rejects_non_relocatable(self):
        data = bytearray(module()); struct.pack_into('<H', data, 16, 2)
        with self.assertRaises(ValueError): inspector.modinfo(data)

    def test_rejects_section_outside_file(self):
        data = bytearray(module()); struct.pack_into('<Q', data, 192 + 24, 1 << 63)
        with self.assertRaises(ValueError): inspector.modinfo(data)

    def test_rejects_missing_vermagic(self):
        with self.assertRaises(ValueError): inspector.modinfo(module(b''))

    def test_rejects_invalid_section_index(self):
        data = bytearray(module()); struct.pack_into('<H', data, 62, 8)
        with self.assertRaises(ValueError): inspector.modinfo(data)

    def test_extended_section_counts(self):
        data = bytearray(module()); struct.pack_into('<H', data, 60, 0)
        struct.pack_into('<Q', data, 64 + 32, 3)
        self.assertEqual(inspector.modinfo(data)['name'], ['test'])

    def test_safe_load_list(self):
        self.assertEqual(inspector.load_names('# heading\ntest.ko\n\ntest.ko # retain duplicate\n'), ['test.ko', 'test.ko'])

    def test_rejects_empty_or_path_entries(self):
        for text in ('', '../test.ko', '/test.ko', 'a.ko b.ko', '.ko'):
            with self.subTest(text=text), self.assertRaises(ValueError): inspector.load_names(text)

    def dt_table(self):
        fdt = struct.pack('>II', 0xd00dfeed, 40) + bytes(32)
        return bytearray(struct.pack('>8I', 0xd7b7ab1e, 104, 32, 32, 1, 32, 2048, 0)
                         + struct.pack('>8I', 40, 64, 0, 0, 0, 0, 0, 0) + fdt)

    def test_android_dt_table_v0(self):
        result = inspector.device_tree_container(self.dt_table())
        self.assertEqual(result['format'], 'android-dt-table-v0')
        self.assertEqual(result['entries'][0]['offset'], 64)

    def test_dt_table_rejects_header_overlap(self):
        data = self.dt_table(); struct.pack_into('>I', data, 36, 32)
        with self.assertRaises(ValueError): inspector.device_tree_container(data)

    def test_dt_table_rejects_payload_outside_declared_total(self):
        data = self.dt_table(); struct.pack_into('>I', data, 4, 100)
        with self.assertRaises(ValueError): inspector.device_tree_container(data)

    def test_dt_table_rejects_entry_array_outside_container(self):
        data = self.dt_table(); struct.pack_into('>I', data, 16, 100)
        with self.assertRaises(ValueError): inspector.device_tree_container(data)

    def test_dt_table_does_not_guess_newer_or_compressed_versions(self):
        data = self.dt_table(); struct.pack_into('>I', data, 28, 1)
        with self.assertRaises(ValueError): inspector.device_tree_container(data)

    def test_dt_table_rejects_truncated_or_invalid_fdt(self):
        for data in (self.dt_table()[:70], self.dt_table()[:64] + bytes(40)):
            with self.assertRaises(ValueError): inspector.device_tree_container(data)

    def test_inspects_wrapped_dtb_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            path = root / 'dtb/mt6878.dtb'; data = self.dt_table(); path.write_bytes(data)
            result = inspector.inspect(root)
            self.assertEqual(result['status'], 'PASS', result['errors'])
            self.assertEqual(path.read_bytes(), data)

    def fixture(self, root):
        (root / 'Image.lz4').write_bytes(bytes.fromhex('02214c18') + b'fixture')
        (root / 'dtb').mkdir()
        (root / 'dtb/mt6878.dtb').write_bytes(struct.pack('>II', 0xd00dfeed, 40) + bytes(32))
        (root / 'dtbo.img').write_bytes(b'inventory-only')
        for group in set(inspector.GROUPS.values()):
            (root / group).mkdir(); (root / group / 'test.ko').write_bytes(module())
        for name in inspector.GROUPS: (root / name).write_text('test.ko\n')

    def test_complete_fixture_and_dtbo_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            result = inspector.inspect(root)
            self.assertEqual(result['status'], 'PASS', result['errors'])
            self.assertEqual(result['release_status'], 'GAP')
            self.assertTrue(next(x for x in result['artifacts'] if x['path'] == 'dtbo.img')['deployment'].startswith('EXCLUDED'))
            self.assertEqual(len(result['artifacts']), 10)

    def test_missing_module_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            (root / 'modules.load.vendor').write_text('missing.ko\n')
            self.assertEqual(inspector.inspect(root)['status'], 'FAIL')

    def test_duplicates_are_reported_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            path = root / 'modules.load.recovery'; path.write_text('test.ko\ntest.ko\n')
            result = inspector.inspect(root)
            self.assertEqual(result['status'], 'PASS', result['errors'])
            self.assertEqual(result['load_lists'][path.name]['duplicates'], {'test.ko': 2})
            self.assertEqual(path.read_text(), 'test.ko\ntest.ko\n')

    def test_rejects_symlinked_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            (root / 'Image.lz4').unlink(); (root / 'Image.lz4').symlink_to('/etc/passwd')
            self.assertEqual(inspector.inspect(root)['status'], 'FAIL')

    def test_empty_root_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(inspector.inspect(Path(directory))['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
