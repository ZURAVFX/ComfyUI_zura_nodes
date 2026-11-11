"""CPU-only high-depth fixtures against the actual OIIO/torch dependencies."""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "assets/media/float_transfer.py"
if PRIVATE.exists():
    spec = importlib.util.spec_from_file_location("float_transfer", PRIVATE)
    fio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fio)
else:
    sys.path.insert(0, str(ROOT))
    fio = importlib.import_module("comfylink.float_io")

COLOUR = {"encoding": "unknown", "sceneLinear": False}
RATE = {"numerator": 24000, "denominator": 1001}


def fixture():
    # Non-contiguous (padded) source, sub-8-bit detail, signed zero, negative
    # HDR RGB, over-one alpha, and hidden RGB at alpha zero are intentional.
    padded = np.zeros((2, 2, 6, 4), dtype=np.float32)
    padded[:, :, :3, :] = np.array([[[[0.000001, -0.125, 10.0001, 0], [-0., 1.5, 0.50001, 1], [1, 2, 3, 0.2]],
                                     [[0.003, 0.004, 0.005, 1.2], [0.25, 0.5, 0.75, -0.1], [-2, 4, 0.001, 0.99999]]]], dtype=np.float32)
    return padded[:, :, :3, :]


class FloatTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = "ComfyLink/" + "a" * 32

    def write(self, array=None, **kwargs):
        return fio.write_transfer(self.root, self.folder, fixture() if array is None else array, colour=COLOUR, frame_rate=RATE, **kwargs)

    def alter_manifest(self, fn):
        path = self.root / self.folder / "manifest.json"
        m = json.loads(path.read_text())
        fn(m)
        path.write_bytes(fio.canonical_manifest_bytes(m))

    def test_float_payload_is_bit_exact_and_zero_based_timing(self):
        relative, manifest = self.write(source_start={"numerator": -1, "denominator": 2})
        actual, declared = fio.load_transfer(self.root, relative)
        self.assertEqual(actual.tobytes(), fixture().tobytes())
        self.assertEqual(manifest, declared)
        self.assertEqual(manifest["frames"][0]["index"], 0)
        self.assertEqual(manifest["frames"][0]["filename"], "000001.rgba32f")
        self.assertEqual(manifest["frames"][1]["time"], {"numerator": 1001, "denominator": 24000})
        self.assertFalse(declared["colour"]["sceneLinear"])
        for p in (self.root / self.folder).iterdir():
            self.assertEqual(p.stat().st_nlink, 1)

    def test_source_16_is_metadata_not_float_scaling(self):
        relative, manifest = self.write(source_bit_depth=16)
        actual, _ = fio.load_transfer(self.root, relative)
        self.assertEqual(actual.tobytes(), fixture().tobytes())
        self.assertEqual(manifest["sourceBitDepth"], 16)

    def test_ae_uint16_has_32768_white(self):
        rgba = np.array([[[0, 1, 65535/32768, 0.5]]], dtype=np.float32)
        relative, _ = self.write(rgba, source_bit_depth=16, sample_type="uint16_ae")
        actual, _ = fio.load_transfer(self.root, relative)
        self.assertEqual(actual.tobytes(), rgba.tobytes())
        payload = (self.root / self.folder / "000001.rgba16u").read_bytes()
        self.assertEqual(np.frombuffer(payload, dtype="<u2").tolist(), [0, 32768, 65535, 16384])

    def test_uint16_rejects_unrepresentable_without_clamp(self):
        with self.assertRaisesRegex(ValueError, "range"):
            self.write(source_bit_depth=16, sample_type="uint16_ae")
        self.assertFalse((self.root / self.folder).exists())

    def test_optional_manifest_canonical_sha_wrapper(self):
        relative, m = self.write()
        wrapper = {"manifest": m, "sha256": hashlib.sha256(fio.canonical_manifest_bytes(m)).hexdigest()}
        (self.root / relative).write_bytes(fio.canonical_manifest_bytes(wrapper))
        self.assertEqual(fio.load_transfer(self.root, relative)[0].tobytes(), fixture().tobytes())
        wrapper["sha256"] = "0" * 64
        (self.root / relative).write_bytes(fio.canonical_manifest_bytes(wrapper))
        with self.assertRaisesRegex(ValueError, "SHA256"):
            fio.load_transfer(self.root, relative)

    def test_malformed_fields_are_rejected(self):
        _, original = self.write()
        cases = [lambda m: m.update(schemaVersion=True), lambda m: m.update(width=0), lambda m: m.update(width=16385),
                 lambda m: m.update(byteOrder="big"), lambda m: m.update(layout="BGRA"), lambda m: m.update(sampleType="half"),
                 lambda m: m.update(frames=[]), lambda m: m["frames"][0].update(index=1),
                 lambda m: m["frames"][0].update(filename="../000001.rgba32f"),
                 lambda m: m["frames"][0].update(byteLength=1), lambda m: m["frames"][0].update(sha256="X"*64),
                 lambda m: m["frames"][0].update(time={"numerator": 1, "denominator": 24}),
                 lambda m: m.update(frameRate={"numerator": 1, "denominator": 0}),
                 lambda m: m.update(colour={"encoding": "acescg", "sceneLinear": False}),
                 lambda m: m.update(colour={"encoding": "acescct", "sceneLinear": True}),
                 lambda m: m.update(colour={"encoding": "ae_project_icc", "sceneLinear": False}),
                 lambda m: m.update(colour={"encoding": "unknown", "sceneLinear": 0}),
                 lambda m: m.update(sourceBitDepth=10)]
        for case in cases:
            m = copy.deepcopy(original)
            case(m)
            with self.subTest(manifest=m), self.assertRaises(ValueError):
                fio.validate_manifest(m)

    def test_arbitrary_paths_are_rejected(self):
        self.write()
        for relative in [str(self.root / self.folder / "manifest.json"), "../manifest.json", "ComfyLink/" + "a"*32 + "/../manifest.json", self.folder + "\\manifest.json", self.folder + "/other.json"]:
            with self.subTest(path=relative), self.assertRaises(ValueError):
                fio.load_transfer(self.root, relative)

    def test_tampered_and_inexact_payload_rejected(self):
        relative, _ = self.write()
        file = self.root / self.folder / "000001.rgba32f"
        original = file.read_bytes()
        for data in [original[:-1], original+b"\0", bytes([original[0]^1])+original[1:]]:
            file.write_bytes(data)
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                fio.load_transfer(self.root, relative)

    def test_nonfinite_even_with_valid_sha_rejected(self):
        relative, _ = self.write()
        file = self.root / self.folder / "000001.rgba32f"
        array = np.frombuffer(file.read_bytes(), dtype="<f4").copy()
        for bad in [np.nan, np.inf, -np.inf]:
            array[0] = bad
            file.write_bytes(array.tobytes())
            self.alter_manifest(lambda m: m["frames"][0].update(sha256=hashlib.sha256(array.tobytes()).hexdigest()))
            with self.subTest(sample=bad), self.assertRaisesRegex(ValueError, "Nonfinite"):
                fio.load_transfer(self.root, relative)

    def test_duplicate_json_and_nonfinite_json_rejected(self):
        relative, _ = self.write()
        path = self.root / relative
        for raw in [b'{"schemaVersion":1,"schemaVersion":1}', b'{"a":NaN}']:
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                fio.load_transfer(self.root, relative)

    def test_hard_link_file_rejected(self):
        relative, _ = self.write()
        file = self.root / self.folder / "000001.rgba32f"
        os.link(file, self.root / "shared")
        with self.assertRaisesRegex(ValueError, "hard links"):
            fio.load_transfer(self.root, relative)

    def test_symlink_parent_rejected(self):
        outside = self.root / "other"
        outside.mkdir()
        try:
            (self.root / "ComfyLink").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Account does not allow symlink creation")
        with self.assertRaisesRegex(ValueError, "Links"):
            self.write()

    def test_never_overwrites_and_failed_batch_has_no_commit(self):
        self.write()
        with self.assertRaises(FileExistsError):
            self.write()
        second = "ComfyLink/" + "b" * 32
        bad = fixture().copy()
        bad[0,0,0,0] = np.nan
        with self.assertRaises(ValueError):
            fio.write_transfer(self.root, second, bad, colour=COLOUR, frame_rate=RATE)
        self.assertFalse((self.root / second).exists())
        self.assertEqual(list((self.root / "ComfyLink").glob(".float-*")), [])

    def test_transfer_bounds_apply_before_payload_reads(self):
        _, m = self.write()
        m["width"], m["height"] = 16384, 16384
        with self.assertRaisesRegex(ValueError, "Pixel"):
            fio.validate_manifest(m)
        m["width"], m["height"] = 4096, 4096
        m["frames"] *= fio.MAX_TRANSFER_BYTES // (4096 * 4096 * 16) + 1
        with self.assertRaisesRegex(ValueError, "byte limit"):
            fio.validate_manifest(m)

    def test_float_exr_named_channels_bit_exact(self):
        for encoding, linear in [("unknown", False), ("scene_linear_rec709", True), ("acescg", True), ("acescct", False)]:
            path = self.root / (encoding + ".exr")
            colour = {"encoding": encoding, "sceneLinear": linear}
            side = fio.write_exr(path, fixture()[0], colour=colour)
            actual, received = fio.read_exr(path)
            self.assertEqual(actual.tobytes(), fixture()[0].tobytes())
            self.assertEqual(side, received)
            import OpenImageIO as oiio
            inp = oiio.ImageInput.open(str(path))
            spec = inp.spec()
            self.assertEqual(set(spec.channelnames), set("RGBA"))
            chroma = spec.getattribute("chromaticities")
            inp.close()
            if encoding == "unknown":
                self.assertIsNone(chroma)
            else:
                np.testing.assert_allclose(chroma, fio._PRIMARIES[encoding], rtol=0, atol=1e-6)

    def test_half_is_explicit_and_matches_declared_rounding(self):
        path = self.root / "half.exr"
        fio.write_exr(path, fixture()[0], colour=COLOUR, storage="half")
        actual, side = fio.read_exr(path)
        np.testing.assert_array_equal(actual, fixture()[0].astype(np.float16).astype(np.float32))
        self.assertEqual(side["storage"], "half")
        bad = fixture()[0].copy()
        bad[0,0,0] = 70000
        with self.assertRaisesRegex(ValueError, "HALF overflow"):
            fio.write_exr(self.root / "overflow.exr", bad, colour=COLOUR, storage="half")

    def test_premultiplied_exr_preserves_stored_rgb_even_at_zero_alpha(self):
        path = self.root / "premult.exr"
        fio.write_exr(path, fixture()[0], colour=COLOUR, alpha_association="premultiplied")
        actual, side = fio.read_exr(path)
        self.assertEqual(actual.tobytes(), fixture()[0].tobytes())
        self.assertEqual(side["alphaAssociation"], "premultiplied")

    def test_exr_sidecar_sha_and_storage_cannot_lie(self):
        path = self.root / "a.exr"
        fio.write_exr(path, fixture()[0], colour=COLOUR)
        sidepath = path.with_suffix(".exr.json")
        side = json.loads(sidepath.read_text())
        side["storage"] = "half"
        sidepath.write_bytes(fio.canonical_manifest_bytes(side))
        with self.assertRaisesRegex(ValueError, "storage"):
            fio.read_exr(path)
        side["storage"] = "float32"
        side["sha256"] = "0"*64
        sidepath.write_bytes(fio.canonical_manifest_bytes(side))
        with self.assertRaisesRegex(ValueError, "SHA256"):
            fio.read_exr(path)

    def test_batch_including_exr_commits_atomically(self):
        relative, _ = self.write(exr_storage="float32")
        actual, _ = fio.read_exr(self.root / self.folder / "000001.exr")
        self.assertEqual(actual.tobytes(), fixture()[0].tobytes())
        self.assertTrue((self.root / relative).exists())
        self.assertEqual(list((self.root / "ComfyLink").glob(".float-*")), [])


@unittest.skipIf(PRIVATE.exists(), "Comfy node tests are maintained in the public integration")
class FloatNodeTests(unittest.TestCase):
    write = FloatTransportTests.write

    def setUp(self):
        FloatTransportTests.setUp(self)
        import torch
        self.torch = torch
        sys.modules["folder_paths"] = types.SimpleNamespace(get_input_directory=lambda: str(self.root), get_output_directory=lambda: str(self.root))
        sys.modules.pop("comfylink.float_nodes", None)
        self.nodes = importlib.import_module("comfylink.float_nodes")

    def test_loader_preserves_rgb_and_metadata_alpha_mask(self):
        relative, m = self.write(alpha_association="premultiplied")
        rgb, mask, metadata = self.nodes.ZuraComfyLinkLoadFloatFrames().load(relative)
        self.assertEqual(rgb.numpy().tobytes(), fixture()[..., :3].tobytes())
        self.assertEqual(metadata["original_alpha"].numpy().tobytes(), fixture()[..., 3].tobytes())
        np.testing.assert_array_equal(mask.numpy(), 1.0-fixture()[..., 3])
        self.assertEqual(metadata["manifest"]["alphaAssociation"], "premultiplied")
        self.assertEqual(metadata["transformations"], [])

    def test_explicit_unpremultiply_recorded(self):
        relative, _ = self.write(alpha_association="premultiplied")
        rgb, _, metadata = self.nodes.ZuraComfyLinkLoadFloatFrames().load(relative, "unpremultiply")
        self.assertEqual(metadata["manifest"]["alphaAssociation"], "straight")
        self.assertEqual(metadata["transformations"][0]["operation"], "unpremultiply")
        np.testing.assert_array_equal(rgb[0,0,0].numpy(), fixture()[0,0,0,:3])
        np.testing.assert_array_equal(rgb[0,1,0].numpy(), fixture()[0,1,0,:3]/fixture()[0,1,0,3])

    def test_saver_roundtrip_keeps_original_alpha_without_mask_loss(self):
        relative, _ = self.write()
        rgb, _, metadata = self.nodes.ZuraComfyLinkLoadFloatFrames().load(relative)
        result = self.nodes.ZuraComfyLinkSaveFloatFrames().save(rgb, metadata)
        output_path, output_metadata = result["result"]
        actual, _ = fio.load_transfer(self.root, output_path)
        self.assertEqual(actual.tobytes(), fixture().tobytes())
        self.assertEqual(output_metadata["manifest"]["colour"], COLOUR)
        self.assertEqual(len(result["ui"]["comfylink_exr"]), 2)

    def test_float_invert_preserves_out_of_range_and_tiny_samples(self):
        values = np.array([[-0.125, 4.0, 16.0], [2.0**-20, 0.25, 0.75]], dtype=np.float32).reshape(1, 1, 2, 3)
        rgba = np.concatenate((values, np.ones((1, 1, 2, 1), dtype=np.float32)), axis=-1)
        relative, _ = fio.write_transfer(self.root, "ComfyLink/" + "f"*32, rgba, colour=COLOUR,
                                         frame_rate={"numerator":25,"denominator":1}, source_bit_depth=32,
                                         alpha_association="straight")
        rgb, _, metadata = self.nodes.ZuraComfyLinkLoadFloatFrames().load(relative)
        self.assertEqual(rgb.numpy().tobytes(), values.tobytes())
        # Comfy's ImageInvert performs 1.0 - image, without clipping.
        inverted = 1.0 - rgb
        result = self.nodes.ZuraComfyLinkSaveFloatFrames().save(inverted, metadata)
        actual, _ = fio.load_transfer(self.root, result["result"][0])
        np.testing.assert_array_equal(actual[..., :3], (np.float32(1) - values))
        np.testing.assert_array_equal(actual[..., 3], np.ones((1, 1, 2), dtype=np.float32))
        self.assertEqual(float(actual[0, 0, 0, 2]), -15.0)

    def test_saver_mask_and_optional_fps_are_explicit(self):
        relative, _ = self.write()
        rgb, mask, metadata = self.nodes.ZuraComfyLinkLoadFloatFrames().load(relative)
        mask[:] = 0.25
        result = self.nodes.ZuraComfyLinkSaveFloatFrames().save(rgb, metadata, alpha_mask=mask, fps=25.0)
        actual, wire = fio.load_transfer(self.root, result["result"][0])
        np.testing.assert_array_equal(actual[..., 3], np.full(actual.shape[:3], 0.75, np.float32))
        self.assertEqual(wire["frameRate"], {"numerator":25,"denominator":1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
