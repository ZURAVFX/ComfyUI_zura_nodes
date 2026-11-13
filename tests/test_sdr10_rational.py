"""Exact media clocks support both PyAV Fraction and AVRational releases."""
from fractions import Fraction
import importlib.util
from pathlib import Path
import unittest
import av

spec = importlib.util.spec_from_file_location('zura_sdr10_rational_test', Path(__file__).resolve().parents[1] / 'comfylink/sdr10_video.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExactClockTests(unittest.TestCase):
    def test_fraction_retains_exact_ntsc_clock(self):
        self.assertEqual(module._positive_fraction(Fraction(30000, 1001), 'invalid'), Fraction(30000, 1001))

    def test_current_pyav_exact_rational(self):
        rational = getattr(getattr(av, 'rational', None), 'AVRational', Fraction)
        value = module._positive_fraction(rational(1001, 30000), 'invalid')
        self.assertIs(type(value), Fraction)
        self.assertEqual(value, Fraction(1001, 30000))

    def test_missing_guessed_and_nonpositive_clocks_are_rejected(self):
        for value in (None, True, False, 24.0, float('nan'), float('inf'), '24/1', Fraction(0), Fraction(-24)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid'):
                module._positive_fraction(value, 'invalid')


if __name__ == '__main__':
    unittest.main()
