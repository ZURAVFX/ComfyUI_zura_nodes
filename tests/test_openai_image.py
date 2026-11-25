import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree

from aiohttp import web
from PIL import Image
import torch


SPEC = importlib.util.spec_from_file_location("openai_image", Path(__file__).resolve().parents[1] / "openai_image.py")
node = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(node)


def image_bytes(size, mode="RGBA", colour=(20, 50, 100, 0)):
    with io.BytesIO() as buffer:
        Image.new(mode, size, colour).save(buffer, format="PNG")
        return buffer.getvalue()


def comfy_modules():
    progress = types.SimpleNamespace(update_absolute=lambda *args: None)
    return {
        "comfy": types.ModuleType("comfy"),
        "comfy.cli_args": types.SimpleNamespace(args=types.SimpleNamespace(listen="127.0.0.1")),
        "comfy.model_management": types.SimpleNamespace(throw_exception_if_processing_interrupted=lambda: None),
        "comfy.utils": types.SimpleNamespace(ProgressBar=lambda total: progress),
    }


class OpenAIImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_precise_native_size_and_alpha(self):
        call = AsyncMock(return_value=([image_bytes((1536, 864))], {"request_id": "test"}))
        with patch.dict(sys.modules, comfy_modules()), patch.object(node, "_call_images", call), patch.object(node, "_api_key", return_value="sk-test"):
            result = await node.ZuraOpenAIImage().generate(
                "A sunset", "gpt-image-2.6-flare", "Generate", "Custom", 1536, 864,
                "xhigh", complexity="low", background="transparent", save_original=False,
            )
        _, edit, body, *_ = call.await_args.args
        self.assertFalse(edit)
        self.assertEqual(body["json"]["size"], "1536x864")
        self.assertEqual(body["json"]["model"], "gpt-image-2.6-flare")
        self.assertEqual(body["json"]["complexity"], "low")
        images, masks, sizes, _, receipt = result["result"]
        self.assertEqual(tuple(images[0].shape), (1, 864, 1536, 4))
        self.assertTrue(torch.all(masks[0] == 1))
        self.assertEqual(sizes, ["1536x864"])
        self.assertNotIn("sk-test", receipt)

    async def test_non_native_edit_restores_delivery_dimensions(self):
        call = AsyncMock(return_value=([image_bytes((1024, 768), colour=(20, 50, 100, 73))], {}))
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {
            **comfy_modules(), "folder_paths": types.SimpleNamespace(get_output_directory=lambda: directory),
        }), patch.object(node, "_call_images", call), patch.object(node, "_api_key", return_value="sk-test"):
            result = await node.ZuraOpenAIImage().generate(
                "Edit the white area", "gpt-image-2.6-flare", "Edit", "Custom", 1021, 761,
                "auto", reference=torch.zeros((1, 761, 1021, 3)), edit_mask=torch.ones((1, 761, 1021)),
                api_references="file-other-reference", background="transparent",
            )
            images, masks, sizes, files, receipt = result["result"]
            with Image.open(files[0]) as output:
                self.assertEqual((output.size, output.mode), ((1021, 761), "RGBA"))
            body = call.await_args.args[2]["json"]
            self.assertEqual(body["size"], "1024x768")
            for uploaded in (body["images"][0], body["mask"]):
                data = base64.b64decode(uploaded["image_url"].split(",")[1])
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.size, (1024, 768))
            self.assertEqual(tuple(images[0].shape), (1, 761, 1021, 4))
            self.assertEqual(tuple(masks[0].shape), (1, 761, 1021))
            self.assertEqual(sizes, ["1021x761"])
            self.assertEqual(json.loads(receipt)["api_size"], "1024x768")

    def test_working_size_respects_alignment_and_api_bounds(self):
        cases = [
            ("1920x1080", "gpt-image-2", "1920x1088"),
            ("1080x1920", "gpt-image-2", "1088x1920"),
            ("512x512", "gpt-image-2", "816x816"),
            ("7680x4320", "gpt-image-2", "3840x2160"),
            ("1920x200", "gpt-image-2", "1920x640"),
            ("1920x1080", "gpt-image-1.5", "1536x1024"),
        ]
        for requested, model, expected in cases:
            with self.subTest(requested=requested, model=model):
                work, target = node._plan_size(requested, model)
                self.assertEqual(work, expected)
                self.assertEqual(target, tuple(map(int, requested.split("x"))))
                self.assertEqual(node._plan_size(work, model), (work, None))

    def test_restores_animation_size_and_timing(self):
        with io.BytesIO() as buffer:
            first = Image.new("RGB", (32, 16), "red")
            second = Image.new("RGB", (32, 16), "blue")
            first.save(buffer, format="GIF", save_all=True, append_images=[second], duration=[120, 270], loop=2)
            source = buffer.getvalue()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules, {"folder_paths": types.SimpleNamespace(get_output_directory=lambda: directory)}
        ):
            images, _, _, files = node._results([source], "gif", "32x16", False, (31, 15))
            self.assertEqual(tuple(images[0].shape), (2, 15, 31, 3))
            with Image.open(files[0]) as image:
                self.assertEqual((image.size, image.n_frames, image.info["loop"]), ((31, 15), 2, 2))
                self.assertEqual(image.info["duration"], 120)
                image.seek(1)
                self.assertEqual(image.info["duration"], 270)

    def test_restores_vector_canvas_without_rasterizing(self):
        drawing = b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16" viewBox="0 0 8 4"><path d="M0 0H8V4" /></svg>'
        resized = ElementTree.fromstring(node._resize_svg(drawing, (32, 16), (31, 15)))
        self.assertEqual((resized.get("width"), resized.get("height")), ("31", "15"))
        self.assertEqual(resized.get("preserveAspectRatio"), "none")
        self.assertEqual(resized[0].get("viewBox"), "0 0 8 4")
        self.assertEqual(resized[0][0].get("d"), "M0 0H8V4")

    async def test_edit_sizes_mask_and_mixed_references(self):
        call = AsyncMock(return_value=([image_bytes((32, 16))], {}))
        with patch.dict(sys.modules, comfy_modules()), patch.object(node, "_call_images", call), patch.object(node, "_api_key", return_value="sk-test"):
            await node.ZuraOpenAIImage().generate(
                "Edit the white area", "gpt-image-2.6-sunburst", "Auto", "auto", 1536, 864,
                "auto", reference=torch.zeros((1, 16, 32, 3)), edit_mask=torch.ones((1, 16, 32)),
                input_width=64, input_height=32, api_references="file-reference", save_original=False,
            )
        _, edit, body, *_ = call.await_args.args
        self.assertTrue(edit)
        self.assertEqual(body["json"]["images"][1], {"file_id": "file-reference"})
        for reference in (body["json"]["images"][0], body["json"]["mask"]):
            data = base64.b64decode(reference["image_url"].split(",")[1])
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.size, (64, 32))
                if reference == body["json"]["mask"]:
                    self.assertEqual(image.getchannel("A").getextrema(), (0, 0))

    async def test_key_route_never_returns_key(self):
        routes = web.RouteTableDef()
        node.register_credentials(routes)
        request = types.SimpleNamespace(
            host="localhost:8188", remote="127.0.0.1", method="POST",
            headers={"Origin": "http://localhost:8188"}, content_length=43,
            json=AsyncMock(return_value={"key": "sk-keyexample123456789"}),
        )
        with patch.dict(sys.modules, comfy_modules()), patch.object(node, "_session_key", ""):
            response = await list(routes)[0].handler(request)
            self.assertEqual(json.loads(response.body), {"source": "session"})
            self.assertEqual(node._api_key(), "sk-keyexample123456789")
            request.headers = {"Origin": "https://other.example"}
            with self.assertRaises(web.HTTPForbidden):
                await list(routes)[0].handler(request)

    async def test_model_choices_merge_documented_and_project_models(self):
        models = node._model_choices([
            {"id": "gpt-image-2.6-flare-2026-11-19"}, {"id": "gpt-image-1"},
            {"id": "gpt-image-1-2025-04-15"}, {"id": "gpt-6.2-astra"}, {"id": "gpt-image-2.6-flare"},
        ])
        expected = "gpt-image-2.6-flare-2026-11-19"
        self.assertEqual(models, [*node.MODELS, expected])
        self.assertIn("gpt-image-1.5-2025-12-16", models)
        self.assertTrue(node.ZuraOpenAIImage.VALIDATE_INPUTS(expected))
        self.assertNotEqual(node.ZuraOpenAIImage.VALIDATE_INPUTS("bad id"), True)

    async def test_extra_reference_sockets_feed_the_edit(self):
        call = AsyncMock(return_value=([image_bytes((32, 16))], {}))
        with patch.dict(sys.modules, comfy_modules()), patch.object(node, "_call_images", call), patch.object(node, "_api_key", return_value="sk-test"):
            await node.ZuraOpenAIImage().generate(
                "Edit with references", "gpt-image-2.6-flare", "Auto", "auto", 1536, 864,
                "auto", reference_16=torch.zeros((1, 16, 32, 3)), save_original=False,
            )
        self.assertTrue(call.await_args.args[1])
        self.assertIn("reference_16", node.ZuraOpenAIImage.INPUT_TYPES()["optional"])

    async def test_stream_parser_handles_large_fragmented_events(self):
        class Content:
            async def iter_any(self):
                yield b": keepalive\r\n\r\ndata: "
                yield b'{"chunk":"' + b"a" * 200_000
                yield b'"}\r\n\r\ndata: [DONE]\n\n'

        events = [event async for event in node._stream_events(Content())]
        self.assertEqual(events, [{"chunk": "a" * 200_000}])

    def test_preserves_svg_bytes_and_rejects_inexact_still(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules, {"folder_paths": types.SimpleNamespace(get_output_directory=lambda: directory)}
        ):
            images, masks, sizes, paths = node._results([svg], "svg", "auto", False)
            self.assertEqual((images, masks, sizes), ([], [], []))
            self.assertEqual(Path(paths[0]).read_bytes(), svg)
        with self.assertRaisesRegex(RuntimeError, "requested 1024x1024"):
            node._results([image_bytes((16, 16))], "png", "1024x1024", False)

    def test_keeps_straight_alpha_and_leaves_opaque_images_rgb(self):
        source = image_bytes((16, 16), colour=(202, 31, 10, 73))
        images, masks, _, _ = node._results([source], "png", "auto", False)
        pixel = (images[0][0, 0, 0] * 255).round().tolist()
        self.assertEqual(pixel, [202, 31, 10, 73])
        self.assertAlmostEqual(masks[0][0, 0, 0].item(), 1 - 73 / 255, places=6)
        opaque = image_bytes((16, 16), colour=(202, 31, 10, 255))
        images, _, _, _ = node._results([opaque], "png", "auto", False)
        self.assertEqual(tuple(images[0].shape), (1, 16, 16, 3))


if __name__ == "__main__":
    unittest.main()
