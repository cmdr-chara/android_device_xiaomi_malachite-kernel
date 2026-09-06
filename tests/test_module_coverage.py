"""Offline coverage-contract tests; synthetic text only, no modules or devices."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('coverage_check', ROOT / 'tools/compare_module_coverage.py')
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)
BUILD, PREBUILT = 'a' * 40, 'b' * 40


class ModuleCoverage(unittest.TestCase):
    def setUp(self):
        self.loads = dict.fromkeys(coverage.LOAD_LISTS, 'one.ko\n')
        self.generated = 'staging/one.ko\t12\n'

    def report(self):
        return coverage.compare(self.generated, self.loads, BUILD, PREBUILT)

    def test_complete_names_do_not_certify_release(self):
        result = self.report()
        self.assertEqual((result['status'], result['release_status']), ('PASS', 'GAP'))
        self.assertEqual(result['required_module_names'], 1)

    def test_missing_module_fails(self):
        self.loads['modules.load.vendor'] += 'missing.ko\n'
        self.assertEqual(self.report()['missing_module_names'], ['missing.ko'])
        self.assertEqual(self.report()['status'], 'FAIL')

    def test_duplicates_reported_not_removed(self):
        self.loads['modules.load.recovery'] += 'one.ko\n'
        result = self.report()['load_lists']['modules.load.recovery']
        self.assertEqual(result['entries'], 2)
        self.assertEqual(result['duplicate_load_entries'], {'one.ko': 2})

    def test_staging_and_unstripped_are_not_dist_proof(self):
        self.generated += 'unstripped/one.ko\t24\n'
        result = self.report()
        self.assertEqual(result['required_names_with_multiple_reported_paths'], {'one.ko': 2})
        self.assertEqual(result['release_status'], 'GAP')

    def test_nonmodule_records_do_not_fill_missing_names(self):
        self.generated += 'other/two.ko.tmp\t12\nother/Module.symvers\t0\n'
        self.loads['modules.load.vendor'] += 'two.ko\n'
        self.assertEqual(self.report()['missing_module_names'], ['two.ko'])

    def test_no_module_inventory_is_rejected(self):
        for value in ('', 'Image.lz4\t123\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                coverage.parse_generated(value)

    def test_malformed_records_rejected(self):
        for value in ('one.ko', 'one.ko\t-1', 'one.ko\t1\textra', 'one.ko\t0', 'one.ko\tabc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                coverage.parse_generated(value)

    def test_unsafe_inventory_paths_rejected(self):
        for path in ('../one.ko', '/one.ko', 'a/../one.ko', 'a//one.ko', '.git/one.ko', 'a\\one.ko'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                coverage.parse_generated(path + '\t12\n')

    def test_duplicate_inventory_paths_rejected(self):
        with self.assertRaises(ValueError):
            coverage.parse_generated(self.generated * 2)

    def test_load_paths_are_not_silently_normalized(self):
        for text in ('../one.ko', 'dir/one.ko', 'one.ko two.ko', ''):
            with self.subTest(text=text), self.assertRaises(ValueError):
                coverage.parse_load(text)

    def test_comments_and_hyphenated_names(self):
        self.assertEqual(coverage.parse_load('# comment\none-driver.ko # note\n'), ['one-driver.ko'])

    def test_all_four_lists_required(self):
        self.loads.pop('modules.load.recovery')
        with self.assertRaises(ValueError):
            self.report()

    def test_revision_identity_required(self):
        with self.assertRaises(ValueError):
            coverage.compare(self.generated, self.loads, 'lineage-23.2', PREBUILT)

    def test_inputs_unchanged_and_hashes_recorded(self):
        saved = copy.deepcopy(self.loads)
        result = self.report()
        self.assertEqual(self.loads, saved)
        self.assertEqual(result['generated_inventory_sha256'], coverage.digest(self.generated))

    def test_symlink_and_oversize_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.write_text('one.ko\n')
            link = root / 'link'; link.symlink_to(source)
            with self.assertRaises(ValueError):
                coverage.read_text(link)
            with source.open('wb') as stream:
                stream.truncate(coverage.MAX_INPUT_BYTES + 1)
            with self.assertRaises(ValueError):
                coverage.read_text(source)

    def test_cli_reports_missing_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inventory = root / 'inventory.txt'; inventory.write_text(self.generated)
            for name in coverage.LOAD_LISTS:
                (root / name).write_text('one.ko\nmissing.ko\n')
            output = root / 'report.json'
            command = [sys.executable, str(ROOT / 'tools/compare_module_coverage.py'),
                       '--generated-files', str(inventory), '--load-root', str(root),
                       '--build-commit', BUILD, '--prebuilt-commit', PREBUILT, '--output', str(output)]
            self.assertEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 1)
            original = output.read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 2)
            self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
