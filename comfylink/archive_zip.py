"""Bounded structural checks for native, single-disk stored ZIP archives.

ZIP64 may be emitted before a 32-bit field overflows: Python deliberately uses
a 2 GiB threshold. Actual sentinel fields, not a guessed size threshold, decide
which values are present in each ZIP64 extra record.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import struct
import zipfile


@dataclass(frozen=True)
class Directory:
    count: int
    offset: int
    size: int


def _read(source, size):
    value = source.read(size)
    if len(value) != size:
        raise ValueError('The native archive is truncated.')
    return value


def bounded_directory(source, size, *, max_entries=10001, max_directory=8*1024*1024):
    if size < 22:
        raise ValueError('The native archive is truncated.')
    source.seek(0)
    if _read(source, 4) != b'PK\x03\x04':
        raise ValueError('The native archive has no first member.')
    source.seek(max(0, size-65557))
    tail = source.read(65557)
    position = tail.rfind(b'PK\x05\x06')
    if position < 0 or position+22 > len(tail):
        raise ValueError('The native archive has no directory.')
    end = max(0, size-65557)+position
    _, disk, cd_disk, disk_count, count, cd_size, offset, comment = struct.unpack('<4s4H2LH', tail[position:position+22])
    if disk or cd_disk or comment or end+22 != size:
        raise ValueError('Archive disks, comments and trailing data are unsupported.')
    original = disk_count, count, cd_size, offset
    required = disk_count == 0xffff or count == 0xffff or cd_size == 0xffffffff or offset == 0xffffffff
    source.seek(max(0, end-20))
    locator = source.read(20) if end >= 20 else b''
    has_locator = locator[:4] == b'PK\x06\x07'
    directory_end = end
    if required and not has_locator:
        raise ValueError('The native ZIP64 directory is missing.')
    if has_locator:
        _, zip_disk, zip_offset, total_disks = struct.unpack('<4sLQL', locator)
        if zip_disk or total_disks != 1 or zip_offset < 0 or zip_offset+56 != end-20:
            raise ValueError('The native ZIP64 locator is invalid.')
        source.seek(zip_offset)
        signature, length, _made, needed, disk, cd_disk, disk_count, count, cd_size, offset = struct.unpack('<4sQ2H2L4Q', _read(source, 56))
        if signature != b'PK\x06\x06' or length != 44 or needed != 45 or disk or cd_disk:
            raise ValueError('The native ZIP64 directory is invalid.')
        for old, actual, sentinel in zip(original, (disk_count, count, cd_size, offset), (0xffff, 0xffff, 0xffffffff, 0xffffffff)):
            if old != sentinel and old != actual:
                raise ValueError('The native ZIP64 and ordinary directories disagree.')
        directory_end = zip_offset
    if (disk_count != count or not 1 <= count <= max_entries or not 0 < cd_size <= max_directory
            or offset < 0 or offset+cd_size != directory_end):
        raise ValueError('The native archive directory exceeds supported bounds.')
    return Directory(int(count), int(offset), int(cd_size))


def _extra_values(extra, fields):
    """Resolve only the exact standard ZIP64 fields requested by sentinels."""
    if not fields:
        if extra:
            raise ValueError('Unexpected native archive extension metadata.')
        return ()
    required = sum(width for _value, width in fields)
    if len(extra) != required+4:
        raise ValueError('The native ZIP64 extension is truncated or oversized.')
    kind, length = struct.unpack('<HH', extra[:4])
    if kind != 1 or length != required:
        raise ValueError('Only the standard ZIP64 extension is supported.')
    values, position = [], 4
    for _value, width in fields:
        values.append(struct.unpack('<Q' if width == 8 else '<L', extra[position:position+width])[0])
        position += width
    return tuple(values)


def _resolve(extra, size, compressed, offset=None, disk=None):
    raw = [size, compressed]
    if offset is not None:
        raw.append(offset)
    if disk is not None:
        raw.append(disk)
    fields = [(value, 4 if index == 3 else 8) for index, value in enumerate(raw) if value == (0xffff if index == 3 else 0xffffffff)]
    values = iter(_extra_values(extra, fields))
    return tuple(next(values) if value == (0xffff if index == 3 else 0xffffffff) else value for index, value in enumerate(raw))


def central_records(source, directory):
    source.seek(directory.offset)
    records = []
    end = directory.offset+directory.size
    for _ in range(directory.count):
        if source.tell()+46 > end:
            raise ValueError('The native central directory is truncated.')
        values = struct.unpack('<4s6H3L5H2L', _read(source, 46))
        signature, made, needed, flags, compression, _time, _date, crc, compressed, size, name_size, extra_size, comment_size, disk, _internal, external, offset = values
        if (signature != b'PK\x01\x02' or flags not in (0, 0x800) or compression != zipfile.ZIP_STORED
                or not 0 < name_size <= 1024 or comment_size or extra_size > 32
                or source.tell()+name_size+extra_size > end or needed not in (10, 20, 45)):
            raise ValueError('The native central directory contains unsupported metadata.')
        name = _read(source, name_size)
        extra = _read(source, extra_size)
        resolved_size, resolved_compressed, resolved_offset, resolved_disk = _resolve(extra, size, compressed, offset, disk)
        if (extra and needed < 45) or resolved_disk != 0:
            raise ValueError('The native ZIP64 member version or disk is invalid.')
        if resolved_size != resolved_compressed or not 0 <= resolved_offset < directory.offset:
            raise ValueError('The native stored member sizes or location are invalid.')
        records.append({'raw_name': name, 'flags': flags, 'crc': crc, 'size': resolved_size,
                        'compressed': resolved_compressed, 'offset': resolved_offset, 'extra': extra,
                        'external': external, 'made': made, 'needed': needed,'raw_disk':disk})
    if source.tell() != end:
        raise ValueError('The native directory length is inconsistent.')
    return records


def validate_infos(source, infos, directory):
    records = central_records(source, directory)
    if len(infos) != len(records):
        raise ValueError('The native archive member count is inconsistent.')
    for info, record in zip(infos, records):
        encoding = 'utf-8' if record['flags'] & 0x800 else 'cp437'
        try:
            name = record['raw_name'].decode(encoding)
        except UnicodeDecodeError:
            raise ValueError('The native archive member name is invalid.') from None
        if (info.filename != name or info.orig_filename != name or info.header_offset != record['offset']
                or info.file_size != record['size'] or info.compress_size != record['compressed']
                or info.CRC != record['crc'] or info.flag_bits != record['flags'] or info.extra != record['extra']
                or info.external_attr != record['external'] or info.volume != record['raw_disk'] or info.comment
                or info.compress_type != zipfile.ZIP_STORED):
            raise ValueError('The decoded native archive differs from its directory.')
    return records


def member_start(source, entry):
    source.seek(entry['offset'])
    values = struct.unpack('<4s5H3L2H', _read(source, 30))
    signature, needed, flags, compression, _time, _date, crc, compressed, size, name_size, extra_size = values
    expected_name = entry.get('raw_name') or entry['name'].encode('ascii')
    if (signature != b'PK\x03\x04' or flags not in (0, 0x800) or flags != entry.get('flags', flags)
            or compression != zipfile.ZIP_STORED or crc != entry['crc'] or needed not in (10, 20, 45)
            or name_size != len(expected_name) or extra_size > 20):
        raise ValueError('The native member header differs from its directory.')
    if _read(source, name_size) != expected_name:
        raise ValueError('The native member name changed.')
    extra = _read(source, extra_size)
    size, compressed = _resolve(extra, size, compressed)
    if (extra and needed < 45) or size != entry['size'] or compressed != entry['size']:
        raise ValueError('The native ZIP64 member size differs from its directory.')
    start = source.tell()
    if start+size > entry['end']:
        raise ValueError('The native archive contains overlapping members.')
    return start


@contextmanager
def bounded_stored_archive(path, *, max_entries=10001, max_directory=8*1024*1024):
    with open(path, 'rb') as source:
        directory = bounded_directory(source, os.fstat(source.fileno()).st_size, max_entries=max_entries, max_directory=max_directory)
        # Validate raw central records before zipfile allocates its index.
        central_records(source, directory)
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            records = validate_infos(source, infos, directory)
            ordered = sorted(records, key=lambda value: value['offset'])
            if not ordered or ordered[0]['offset'] != 0 or len({record['offset'] for record in ordered}) != len(ordered):
                raise ValueError('The native member locations are invalid.')
            for index, record in enumerate(ordered):
                entry = {**record, 'end': ordered[index+1]['offset'] if index+1 < len(ordered) else directory.offset}
                member_start(source, entry)
            yield archive
