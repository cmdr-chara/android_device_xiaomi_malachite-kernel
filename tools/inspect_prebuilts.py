#!/usr/bin/env python3
"""Read-only malachite prebuilt shape, hash and module metadata inspection.

Never loads modules, builds images, invokes a device tool or changes artifacts.
PASS covers only these structural checks, not KMI, signing, boot or firmware
compatibility. DTBO is inventoried if present, never selected for deployment.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

GROUPS = {
    'modules.load.system': 'system_dlkm',
    'modules.load.vendor': 'vendor_dlkm',
    'modules.load.vendor_ramdisk': 'vendor_ramdisk',
    'modules.load.recovery': 'vendor_ramdisk',
}
MODULE_NAME = re.compile(r'[A-Za-z0-9_.+-]+\.ko\Z')
MAX_MODULE_BYTES = 128 * 1024 * 1024


def span(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError('ELF section extends outside file')
    return data[offset:offset + size]


def modinfo(data: bytes) -> dict[str, list[str]]:
    if len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError('Expected ELF64 little-endian module')
    if struct.unpack_from('<HH', data, 16) != (1, 183):
        raise ValueError('Expected relocatable AArch64 module')
    offset = struct.unpack_from('<Q', data, 40)[0]
    entsize, count, names_index = struct.unpack_from('<HHH', data, 58)
    if not offset or entsize != 64:
        raise ValueError('Missing or unsupported ELF section table')
    first = struct.unpack('<IIQQQQIIQQ', span(data, offset, 64))
    count = count or first[5]
    names_index = first[6] if names_index == 0xffff else names_index
    if not count or names_index >= count:
        raise ValueError('Invalid ELF section name table index')
    span(data, offset, count * entsize)

    def section(index: int):
        return struct.unpack('<IIQQQQIIQQ', span(data, offset + index * entsize, entsize))

    names_section = section(names_index)
    names = span(data, names_section[4], names_section[5])
    found = []
    for index in range(count):
        entry = section(index)
        name_offset = entry[0]
        if name_offset >= len(names):
            raise ValueError('Invalid ELF section name offset')
        end = names.find(b'\0', name_offset)
        if end < 0:
            raise ValueError('Unterminated ELF section name')
        if names[name_offset:end] == b'.modinfo':
            if entry[1] != 1:
                raise ValueError('Expected PROGBITS .modinfo')
            found.append(span(data, entry[4], entry[5]))
    if len(found) != 1:
        raise ValueError('Expected exactly one .modinfo section')
    result: dict[str, list[str]] = {}
    for item in found[0].split(b'\0'):
        if b'=' in item:
            key, value = item.decode('utf-8', errors='strict').split('=', 1)
            result.setdefault(key, []).append(value)
    if len(result.get('vermagic', [])) != 1 or not result['vermagic'][0].strip():
        raise ValueError('Expected exactly one nonempty vermagic')
    return result


def regular_file(root: Path, path: Path) -> Path:
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Missing, symlinked or out-of-root artifact: {path.name}')
    return path


def file_record(root: Path, path: Path) -> dict:
    regular_file(root, path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return {'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
            'sha256': digest.hexdigest()}


def load_names(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        line = line.partition('#')[0].strip()
        if not line:
            continue
        if not MODULE_NAME.fullmatch(line) or line in ('.ko', '..ko'):
            raise ValueError(f'Invalid module load-list entry: {line!r}')
        names.append(line)
    if not names:
        raise ValueError('Empty module load list')
    return names


def inspect(root: Path) -> dict:
    root = root.resolve()
    report = {'schema_version': 1, 'status': 'PASS', 'release_status': 'GAP',
              'scope': 'artifact hashes, container headers, module metadata and load-list membership only',
              'artifacts': [], 'load_lists': {}, 'warnings': [], 'errors': [],
              'gaps': ['Image configuration/release extraction', 'KMI/CRC and exported-symbol compatibility',
                       'module signature verification', 'DTB/DTBO and installed-firmware compatibility',
                       'actual module loading, Android packaging, boot and device tests']}

    def record(path: Path):
        item = file_record(root, path)
        report['artifacts'].append(item)
        return item

    try:
        image = regular_file(root, root / 'Image.lz4')
        with image.open('rb') as stream:
            magic = stream.read(4)
        if magic not in (bytes.fromhex('02214c18'), bytes.fromhex('04224d18')):
            raise ValueError('Image.lz4 is not a recognized LZ4 container')
        record(image)
    except (OSError, ValueError) as error:
        report['errors'].append(str(error))

    dtbs = sorted((root / 'dtb').glob('*.dtb'))
    if not dtbs:
        report['errors'].append('No DTB artifacts found')
    for path in dtbs:
        try:
            regular_file(root, path)
            with path.open('rb') as stream:
                header = stream.read(8)
            if len(header) != 8 or struct.unpack('>I', header[:4])[0] != 0xd00dfeed:
                raise ValueError(f'Invalid DTB header: {path.name}')
            total = struct.unpack('>I', header[4:])[0]
            if total < 40 or total > path.stat().st_size:
                raise ValueError(f'Invalid DTB size: {path.name}')
            record(path)
        except (OSError, ValueError) as error:
            report['errors'].append(str(error))
    if (root / 'dtbo.img').exists() or (root / 'dtbo.img').is_symlink():
        try:
            item = record(root / 'dtbo.img')
            item['deployment'] = 'EXCLUDED: presence is not authorization to package or flash'
        except (OSError, ValueError) as error:
            report['errors'].append(str(error))

    modules = {}
    vermagic = Counter()
    for group in sorted(set(GROUPS.values())):
        paths = sorted((root / group).glob('*.ko'))
        if not paths:
            report['errors'].append(f'No modules in {group}')
        modules[group] = {path.name for path in paths}
        for path in paths:
            try:
                regular_file(root, path)
                if path.stat().st_size > MAX_MODULE_BYTES:
                    raise ValueError(f'Module exceeds inspection size limit: {path.name}')
                info = modinfo(path.read_bytes())
                item = record(path)
                item['modinfo'] = {key: info[key] for key in ('name', 'vermagic', 'depends', 'srcversion') if key in info}
                vermagic[info['vermagic'][0]] += 1
            except (OSError, ValueError, UnicodeError, struct.error) as error:
                report['errors'].append(f'{group}/{path.name}: {error}')
    for name, group in GROUPS.items():
        try:
            path = regular_file(root, root / name)
            names = load_names(path.read_text(encoding='utf-8'))
            missing = sorted(set(names) - modules[group])
            duplicates = {key: count for key, count in Counter(names).items() if count > 1}
            report['load_lists'][name] = {'group': group, 'entries': len(names),
                                          'missing': missing, 'duplicates': duplicates}
            record(path)
            if missing:
                report['errors'].append(f'{name}: missing modules {missing}')
            if duplicates:
                report['warnings'].append(f'{name}: duplicate entries retained for review {duplicates}')
        except (OSError, ValueError, UnicodeError) as error:
            report['errors'].append(f'{name}: {error}')
    report['vermagic_counts'] = dict(sorted(vermagic.items()))
    if len(vermagic) > 1:
        report['warnings'].append('Multiple vermagic strings: compare configuration and symbol CRCs; do not assume interchangeability')
    if report['errors']:
        report['status'] = 'FAIL'
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = inspect(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
