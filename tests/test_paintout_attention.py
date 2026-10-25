"""Compact guide masks must produce the same attention as the dense mask."""
import importlib.util
from pathlib import Path
import unittest
import torch
import torch.nn.functional as F

spec = importlib.util.spec_from_file_location('paintout_attention_test', Path(__file__).resolve().parents[1]/'paintout/attention.py')
attention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attention)


def native(q, k, v, heads, mask=None, **kwargs):
    batch, count, channels = q.shape
    def split(x):
        return x.reshape(batch, -1, heads, channels//heads).transpose(1, 2)
    return F.scaled_dot_product_attention(split(q), split(k), split(v), attn_mask=mask).transpose(1, 2).reshape(batch, count, channels)


class PaintoutAttentionTests(unittest.TestCase):
    def test_fractional_zero_and_full_masks_match_dense_attention(self):
        torch.manual_seed(42)
        q, k, v = [torch.randn(1, 19, 16) for _ in range(3)]
        for weights in ([0., .2, 1., .8], [0., 0., 0., 0.], [1., 1., 1., 1.]):
            compact = attention.CompactGuideMask(19, 9, 4, torch.tensor(weights))
            dense = torch.zeros(1, 1, 19, 19)
            dense[:, :, :9, :] = compact.noisy_mask
            dense[:, :, 9:13, :] = compact.rows(9, 13)
            expected = native(q, k, v, 2, mask=dense)
            for chunk in (2, 7, 1024):
                actual = attention.chunked_guide_attention(native, q, k, v, 2, mask=compact, chunk_size=chunk)
                torch.testing.assert_close(actual, expected, rtol=1e-5, atol=1e-6)

    def test_shape_changes_fail_rather_than_misaligning_the_removal(self):
        mask = attention.CompactGuideMask(19, 9, 4, torch.ones(4))
        with self.assertRaisesRegex(RuntimeError, 'token counts changed'):
            attention.chunked_guide_attention(native, torch.zeros(1, 18, 16), torch.zeros(1, 19, 16), torch.zeros(1, 19, 16), 2, mask=mask)


if __name__ == '__main__':
    unittest.main()
