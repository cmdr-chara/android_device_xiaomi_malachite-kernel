#!/usr/bin/env python3
"""Compare reported source-build module names with the four consumed load lists.

Read-only: no binary is loaded, copied, rewritten or deployed. Name coverage is
necessary but not sufficient for a source/prebuilt migration. Every report keeps
release_status=GAP even when all names are reported by a build inventory.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys

LOAD_LISTS = ('modules.load.system', 'modules.load.vendor',
              'modules.load.vendor_ramdisk', 'modules.load.recovery')
MAX_INPUT_BYTES = 16 * 1024 * 1024


def read_text(path: Path) -> str:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'Expected a regular, non-symlink input: {path}')
    with path.open('rb') as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f'Input exceeds {MAX_INPUT_BYTES} bytes: {path}')
    return data.decode('utf-8')


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def module_name(name: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*\.ko', name))


def parse_generated(text: str) -> dict[str, list[str]]:
    paths = {}
    modules = defaultdict(list)
    for number, line in enumerate(text.splitlines(), 1):
        fields = line.split('\t')
        if len(fields) != 2 or not re.fullmatch(r'[0-9]+', fields[1]):
            raise ValueError(f'Invalid path/tab/byte-size record on line {number}')
        value, size = fields[0], int(fields[1])
        path = PurePosixPath(value)
        if (not path.parts or path.is_absolute() or '..' in path.parts
                or '.git' in path.parts or '\\' in value
                or value != path.as_posix() or any(ord(c) < 32 for c in value)):
            raise ValueError(f'Unsafe inventory path on line {number}')
        if value in paths:
            raise ValueError(f'Duplicate inventory path on line {number}')
        paths[value] = size
        if path.suffix == '.ko':
            if not module_name(path.name) or size == 0:
                raise ValueError(f'Invalid module name/zero-size module on line {number}')
            modules[path.name].append(value)
    if not modules:
        raise ValueError('No source module records; refusing a vacuous coverage result')
    return {name: sorted(values) for name, values in sorted(modules.items())}


def parse_load(text: str) -> list[str]:
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        name = line.split('#', 1)[0].strip()
        if not name:
            continue
        if not module_name(name):
            raise ValueError(f'Expected a module basename on load-list line {number}')
        result.append(name)
    if not result:
        raise ValueError('An empty load list cannot establish the consumed baseline')
    return result


def compare(generated: str, loads: dict[str, str], build_commit: str,
            prebuilt_commit: str) -> dict:
    for revision in (build_commit, prebuilt_commit):
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Both input revisions must be immutable 40-character commit IDs')
    if set(loads) != set(LOAD_LISTS):
        raise ValueError('All four consumed load lists are required')
    modules = parse_generated(generated)
    groups, missing, required = {}, set(), set()
    for name in LOAD_LISTS:
        entries = parse_load(loads[name])
        needed = set(entries)
        absent = sorted(needed - modules.keys())
        missing.update(absent)
        required.update(needed)
        groups[name] = {
            'entries': len(entries), 'unique_names': len(needed), 'missing': absent,
            'duplicate_load_entries': {key: count for key, count in sorted(Counter(entries).items()) if count > 1},
            'sha256': digest(loads[name]),
        }
    return {
        'schema_version': 1, 'scope': 'reported-basename-coverage-only',
        'status': 'FAIL' if missing else 'PASS', 'release_status': 'GAP',
        'build_commit': build_commit, 'prebuilt_commit': prebuilt_commit,
        'generated_inventory_sha256': digest(generated),
        'source_module_names': len(modules), 'required_module_names': len(required),
        'missing_module_names': sorted(missing), 'load_lists': groups,
        'required_names_with_multiple_reported_paths': {
            name: len(modules[name]) for name in sorted(required & modules.keys())
            if len(modules[name]) > 1
        },
        'gaps': [
            'Inventory authenticity/completeness and build outcome must be checked separately.',
            'Intermediate/staging copies are not a collected distribution.',
            'Equal basenames do not establish byte identity, ABI/CRC compatibility, signing or load order.',
            'Missing names may reflect disabled, renamed, built-in or unavailable components; do not delete load entries automatically.',
            'No Android packaging, firmware compatibility, boot or device test is proven.',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated-files', required=True, type=Path)
    parser.add_argument('--load-root', required=True, type=Path)
    parser.add_argument('--build-commit', required=True)
    parser.add_argument('--prebuilt-commit', required=True)
    parser.add_argument('--output', type=Path, help='Create a new report; never overwrite inputs or prior evidence')
    args = parser.parse_args()
    try:
        if args.load_root.is_symlink():
            raise ValueError('The load-list root must not be a symlink')
        result = compare(read_text(args.generated_files),
                         {name: read_text(args.load_root / name) for name in LOAD_LISTS},
                         args.build_commit, args.prebuilt_commit)
        text = json.dumps(result, indent=2, sort_keys=True) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(text)
        else:
            print(text, end='')
        return 1 if result['missing_module_names'] else 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
