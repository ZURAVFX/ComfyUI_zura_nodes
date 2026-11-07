"""Exercise the Studio upload bridge without downloading models or rendering."""
import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import test_artist_studio as fixtures

studio = fixtures.studio
if 'ComfyUI_zura_nodes.paintout' not in sys.modules:
    package = types.ModuleType('ComfyUI_zura_nodes.paintout')
    package.__path__ = [str(Path(__file__).resolve().parents[1] / 'paintout')]
    sys.modules[package.__name__] = package
_server = types.ModuleType('server')
_server.PromptServer = types.SimpleNamespace(instance=None)
with patch.dict(sys.modules, {'server': _server}):
    browser_module = importlib.import_module('ComfyUI_zura_nodes.paintout.browser')


class RippleSourceRouteTest(fixtures.unittest.IsolatedAsyncioTestCase):
    async def test_only_verified_video_uploads_are_handed_off_and_sdr_is_accepted(self):
        server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
        server_module = types.ModuleType('server')
        server_module.PromptServer = types.SimpleNamespace(instance=server)
        asset = {'asset_kind': 'video'}
        instance = types.SimpleNamespace(start_watcher=lambda: None,
            store=types.SimpleNamespace(load=lambda identity: asset))
        calls = []
        describe = lambda path: (calls.append(path) or {
            'path': path, 'kind': 'video', 'resolved_colour': 'srgb_display',
            'fps': 30, 'frames': 85, 'width': 1920, 'height': 1080})
        helper = studio.ripple_uploaded_source_info
        with patch.dict(sys.modules, {'server': server_module}), \
             patch.object(studio, 'Studio', return_value=instance), \
             patch.object(studio, 'check_asset', return_value='/verified/source.mp4'), \
             patch.object(studio, 'ripple_uploaded_source_info',
                          side_effect=lambda store, identity, validate, _describe:
                          helper(store, identity, validate, describe)):
            studio.register()
            handler = next(route.handler for route in server.routes
                           if route.path == '/zura/studio/assets/{identity}/ripple')
            request = types.SimpleNamespace(headers={}, host='localhost',
                                             match_info={'identity': 'one'})
            response = await handler(request)
            self.assertEqual(response.status, 200, response.body)
            data = json.loads(response.body)
            self.assertEqual((data['fps'], data['frames'], data['resolved_colour']),
                             (30, 85, 'srgb_display'))
            self.assertEqual(calls, ['/verified/source.mp4'])
            asset['asset_kind'] = 'image'
            response = await handler(request)
            self.assertEqual(response.status, 400)
            self.assertIn('uploaded video', json.loads(response.body)['error'])
            self.assertEqual(calls, ['/verified/source.mp4'])
            request.headers = {'Origin': 'https://elsewhere.example'}
            with self.assertRaises(studio.web.HTTPForbidden):
                await handler(request)


if __name__ == '__main__':
    fixtures.unittest.main()
