"""Repeated checks avoid rereading assets while changed files never reuse SHA."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("zura_file_cache_test", Path(__file__).resolve().parents[1] / "artist_studio/file_cache.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class FileCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "asset.bin"
        self.path.write_bytes(b"original")
        cache._DIGESTS.clear()

    def test_warm_digest_does_not_read_file_again(self):
        expected = hashlib.sha256(b"original").hexdigest()
        self.assertEqual(cache.digest_file(self.path), expected)
        with patch.object(Path, "open", side_effect=AssertionError("warm checks must not read")):
            self.assertEqual(cache.digest_file(self.path), expected)

    def test_same_size_replacement_with_restored_mtime_is_rehashed(self):
        before = self.path.stat()
        old_digest = cache.digest_file(self.path)
        replacement = self.path.with_suffix(".new")
        replacement.write_bytes(b"replaced")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, self.path)
        self.assertNotEqual(cache.digest_file(self.path), old_digest)
        self.assertEqual(cache.digest_file(self.path), hashlib.sha256(b"replaced").hexdigest())

    def test_deleted_file_never_returns_a_cached_digest(self):
        cache.digest_file(self.path)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            cache.digest_file(self.path)

    def test_in_place_write_with_restored_mtime_is_rehashed(self):
        before = self.path.stat()
        old_digest = cache.digest_file(self.path)
        self.path.write_bytes(b"replaced")
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertNotEqual(cache.digest_file(self.path), old_digest)

    def test_mutation_during_read_is_rejected_and_not_cached(self):
        real_sha = hashlib.sha256
        path = self.path

        class MutatingDigest:
            def __init__(self):
                self.value = real_sha()

            def update(self, block):
                self.value.update(block)
                path.write_bytes(b"changed during hashing")

            def hexdigest(self):
                return self.value.hexdigest()

        with patch.object(cache.hashlib, "sha256", MutatingDigest):
            with self.assertRaisesRegex(ValueError, "changed"):
                cache.digest_file(self.path)
        self.assertEqual(len(cache._DIGESTS), 0)

    def test_entries_are_bounded_and_warm_access_updates_lru(self):
        paths = [self.path.with_name(str(i)) for i in range(3)]
        for i, path in enumerate(paths):
            path.write_bytes(str(i).encode())
        with patch.object(cache, "MAX_ENTRIES", 2):
            cache.digest_file(paths[0])
            cache.digest_file(paths[1])
            cache.digest_file(paths[0])
            cache.digest_file(paths[2])
        self.assertEqual(len(cache._DIGESTS), 2)
        self.assertIn(cache.file_identity(paths[0]), cache._DIGESTS)
        self.assertNotIn(cache.file_identity(paths[1]), cache._DIGESTS)


if __name__ == "__main__":
    unittest.main()
