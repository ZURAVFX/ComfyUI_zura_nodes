"""CPU-only checks: python -m unittest discover -s tests -p test_longcat_text.py"""
import importlib.util
from pathlib import Path
import re
import unittest

spec = importlib.util.spec_from_file_location('longcat_text', Path(__file__).resolve().parents[1] / 'longcat_runtime/text.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def estimate(text):
    return len(re.sub(r'\s+', '', text)) * 0.1


class SplitTests(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(module.split_script('Hello, this is a test.', estimate, 25), ['Hello, this is a test.'])

    def test_empty(self):
        self.assertEqual(module.split_script(' \n ', estimate, 25), [])

    def test_english_roundtrip(self):
        text = 'Check every word. Keep the original recording. Save a new version for the client. ' * 15
        pieces = module.split_script(text, estimate, 25)
        self.assertGreater(len(pieces), 1)
        self.assertEqual(re.sub(r'\s+', '', ''.join(pieces)), re.sub(r'\s+', '', text))
        self.assertTrue(all(estimate(p) <= 25 for p in pieces))

    def test_chinese_roundtrip(self):
        text = '这是一个语音测试。请保留完整的句子。' * 30
        pieces = module.split_script(text, estimate, 10)
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(all(estimate(p) <= 10 for p in pieces))

    def test_long_token_kept(self):
        text = 'A' * 800
        pieces = module.split_script(text, estimate, 25)
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(all(estimate(p) <= 25 for p in pieces))

    def test_small_budget(self):
        text = 'one two three four five'
        pieces = module.split_script(text, estimate, 0.5)
        self.assertEqual(re.sub(r'\s+', '', ''.join(pieces)), re.sub(r'\s+', '', text))
        self.assertTrue(all(estimate(p) <= 0.5 for p in pieces))

    def test_no_budget(self):
        with self.assertRaises(ValueError):
            module.split_script('test', estimate, 0)


if __name__ == '__main__':
    unittest.main()
