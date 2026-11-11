"""The CI fallback may change known mirror URIs, never package trust settings."""
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "ci_ubuntu_mirror", Path(__file__).resolve().parents[1] / "tools/ci_ubuntu_mirror.py")
mirror = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mirror)

BASE = """# Ubuntu archive\nTypes: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\nSuites: noble noble-updates noble-backports\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"""
SECURITY = """# Security updates\nTypes: deb\nURIs: https://security.ubuntu.com/ubuntu/\nSuites: noble-security\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"""


class UbuntuMirrorTests(unittest.TestCase):
    def test_only_uri_lines_change_in_archive_and_security_stanzas(self):
        original = BASE + "\n" + SECURITY
        result = mirror.fallback_sources(original)
        expected = original.replace("mirror+file:/etc/apt/apt-mirrors.txt", mirror.MIRROR)
        expected = expected.replace("https://security.ubuntu.com/ubuntu/", mirror.MIRROR)
        self.assertEqual(result, expected)

    def test_direct_ubuntu_uri_and_crlf_comments_are_preserved(self):
        original = BASE.replace("mirror+file:/etc/apt/apt-mirrors.txt",
                                "http://azure.archive.ubuntu.com/ubuntu/").replace("\n", "\r\n")
        result = mirror.fallback_sources(original)
        self.assertEqual(result, original.replace("http://azure.archive.ubuntu.com/ubuntu/", mirror.MIRROR))

    def test_fallback_is_idempotent(self):
        result = mirror.fallback_sources(BASE)
        self.assertEqual(mirror.fallback_sources(result), result)

    def test_unexpected_sources_fail_without_partial_rewrite(self):
        invalid = {
            "foreign URI": BASE.replace("mirror+file:/etc/apt/apt-mirrors.txt", "https://example.com/ubuntu/"),
            "mixed URI": BASE.replace("mirror+file:/etc/apt/apt-mirrors.txt", "https://archive.ubuntu.com/ubuntu/ https://example.com/ubuntu/"),
            "wrong suite": BASE.replace("noble noble-updates noble-backports", "jammy"),
            "wrong keyring": BASE.replace(mirror.KEYRING, "/tmp/other-keyring.gpg"),
            "missing keyring": BASE.replace("Signed-By: " + mirror.KEYRING + "\n", ""),
            "duplicate field": BASE + "URIs: https://archive.ubuntu.com/ubuntu/\n",
            "continuation": BASE.replace("Suites: noble", "Suites:\n noble"),
            "trust bypass": BASE + "Trusted: yes\n",
            "insecure repository": BASE + "Allow-Insecure: yes\n",
            "expired metadata bypass": BASE + "Check-Valid-Until: no\n",
            "unexpected component": BASE.replace("main restricted universe multiverse", "main extra"),
        }
        for reason, bad in invalid.items():
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                mirror.fallback_sources(BASE + "\n" + bad)

    def test_empty_source_file_is_rejected(self):
        with self.assertRaises(ValueError):
            mirror.fallback_sources("# No Ubuntu source\n")


if __name__ == "__main__":
    unittest.main()
