"""The fixed Studio host route exposes only its packaged manifest assets."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import types
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comfylink.routes import register
from comfylink.studio_host import _valid_name

VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
PREFIX = "/zura/comfylink/v1/studio-host/"


class StudioHostRouteTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        holder = types.SimpleNamespace(routes=web.RouteTableDef())
        register(holder, VERSION)
        app = web.Application()
        app.add_routes(holder.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_manifest_entries_and_runtime_assets_are_served_by_fixed_path(self):
        response = await self.client.get(PREFIX + "studio_host_manifest.json")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        manifest = await response.json()
        self.assertEqual(manifest["backendVersion"], VERSION)
        self.assertEqual(manifest["hostSchema"], 1)
        digest = hashlib.sha256()
        for name in manifest["sourceFiles"]:
            raw = (ROOT / "web" / name).read_bytes().replace(b"\r\n", b"\n")
            digest.update(name.encode("utf-8") + b"\0" + raw + b"\0")
        self.assertEqual(digest.hexdigest(), manifest["sourceSha256"])
        for name in ("studio_ae.html", "studio_ae_probe.js", "studio_ae_entry.js", "studio_host_version.js",
                     "vendor/studio-components.js", "vendor/paintaplate/canvas.mjs", "vendor/paintaplate/strokes.mjs", "assets/zura-logo.png", "flux3_prompt_upsampling.json"):
            response = await self.client.get(PREFIX + name)
            self.assertEqual(response.status, 200, name)
            raw = await response.read()
            if name.endswith(".mjs"):self.assertIn("javascript",response.headers["Content-Type"])
            expected = manifest["entrySha256"].get(name) or manifest["assetSha256"].get(name)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected, name)
        capabilities = await (await self.client.get("/zura/comfylink/v1/capabilities")).json()
        self.assertEqual(capabilities["zura_version"], VERSION)
        self.assertEqual(capabilities["studio_host"], {"hostSchema": 1, "prefix": PREFIX,
                                                     "manifest": PREFIX + "studio_host_manifest.json"})

    async def test_unknown_and_encoded_paths_cannot_escape_manifest(self):
        for name in ("private.json", "vendor/ELK-LICENSE.md", "workflows/secret.json", "studio_host_manifest.json?x=1",
                     "%2e%2e%2f__init__.py", "assets%2fzura-logo.png", "assets%5czura-logo.png"):
            response = await self.client.get(PREFIX + name)
            self.assertEqual(response.status, 404, name)
        self.assertFalse(_valid_name("../__init__.py"))
        self.assertFalse(_valid_name("assets\\zura-logo.png"))
        self.assertFalse(_valid_name("assets//zura-logo.png"))
        self.assertEqual((await self.client.get(PREFIX + "studio_ae.html", headers={"Origin": "https://attacker.invalid"})).status, 403)
        self.assertEqual((await self.client.get(PREFIX + "studio_ae.html", headers={"Host": "attacker.invalid"})).status, 403)


if __name__ == "__main__":
    unittest.main()
