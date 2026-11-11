"""Actual loopback discovery without a ComfyUI or AE process."""
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink.routes import register


class StudioInstanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_unpaired_process_nonce_is_stable_shared_and_changes_on_restart(self):
        identities = []
        for _ in range(2):
            holder = types.SimpleNamespace(routes=web.RouteTableDef())
            with patch.dict(os.environ, {}, clear=True):
                register(holder, "test")
            app = web.Application()
            app.add_routes(holder.routes)
            async with TestClient(TestServer(app, host="127.0.0.1")) as client:
                first = await (await client.get("/zura/comfylink/v1/capabilities")).json()
                second = await (await client.get("/zura/comfylink/v1/capabilities")).json()
                nonce = first["studio"]["instanceId"]
                self.assertRegex(nonce, r"^[0-9a-f]{32}$")
                self.assertEqual(second["studio"]["instanceId"], nonce)
                self.assertEqual(holder._zura_comfylink_studio_sessions.instance_id, nonce)
                self.assertFalse(first["pairing_configured"])
                self.assertEqual((await client.get("/zura/comfylink/v1/identity")).status, 403)
                identities.append(nonce)
        self.assertNotEqual(*identities)

    async def test_nonce_does_not_expose_or_replace_managed_identity(self):
        holder = types.SimpleNamespace(routes=web.RouteTableDef())
        with patch.dict(os.environ, {"COMFYLINK_INSTANCE_ID": "private-managed-id",
                                    "COMFYLINK_TOKEN": "private-token",
                                    "COMFYLINK_CONFIG_FINGERPRINT": "private-fingerprint"}):
            register(holder, "test")
        app = web.Application()
        app.add_routes(holder.routes)
        async with TestClient(TestServer(app, host="127.0.0.1")) as client:
            response = await client.get("/zura/comfylink/v1/capabilities")
            text = await response.text()
            for value in ("private-managed-id", "private-token", "private-fingerprint"):
                self.assertNotIn(value, text)
            self.assertRegex((await response.json())["studio"]["instanceId"], r"^[0-9a-f]{32}$")


if __name__ == "__main__":
    unittest.main()
