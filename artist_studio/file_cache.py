"""Bounded process-local fingerprints for repeatedly checked local assets.

Changed files are hashed again. A digest is only published when the opened
file and its path retain the same identity throughout the read.
"""
from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import threading

MAX_ENTRIES = 256
_DIGESTS = OrderedDict()
_LOCK = threading.RLock()


def _stat_identity(value):
    return (value.st_size, value.st_mtime_ns, value.st_ctime_ns,
            value.st_dev, value.st_ino)


def file_identity(path):
    resolved = Path(path).resolve(strict=True)
    # fstat exposes Windows change time rather than Path.stat's legacy birth
    # time, so in-place writes still invalidate if mtime was restored. Opening
    # for metadata does not read the asset payload.
    descriptor = os.open(str(resolved), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        stamp = _stat_identity(os.fstat(descriptor))
        path_stamp = _stat_identity(resolved.stat())
        if stamp[:2] + stamp[3:] != path_stamp[:2] + path_stamp[3:]:
            raise ValueError("The file changed while checking its identity.")
        return (str(resolved), *stamp)
    finally:
        os.close(descriptor)


def digest_file(path):
    identity = file_identity(path)
    resolved = Path(identity[0])
    with _LOCK:
        cached = _DIGESTS.get(identity)
        if cached is not None:
            # Recheck after looking up a value, including replacement of a
            # same-sized file while its original modification time is restored.
            if file_identity(path) != identity:
                raise ValueError("The file changed while checking its fingerprint.")
            _DIGESTS.move_to_end(identity)
            return cached
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        opened = _stat_identity(os.fstat(stream.fileno()))
        if opened != identity[1:]:
            raise ValueError("The file changed before fingerprinting.")
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
        after = _stat_identity(os.fstat(stream.fileno()))
    if after != opened or file_identity(path) != identity:
        raise ValueError("The file changed while fingerprinting.")
    result = digest.hexdigest()
    with _LOCK:
        _DIGESTS[identity] = result
        _DIGESTS.move_to_end(identity)
        while len(_DIGESTS) > MAX_ENTRIES:
            _DIGESTS.popitem(last=False)
    return result


# A descriptive alias used by Studio's asset checks.
file_digest = digest_file
